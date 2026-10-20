import csv
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from risk_calculator import DailyBar, calculate_historical_stress
from advanced_risk import default_exposure, default_profile, parse_equity_csv

APP = runpy.run_path(str(Path(__file__).with_name("risk_calculator_app.pyw")))
APP["RiskCalculatorApp"].AUTOSAVE_ENABLED = False
APP["RiskCalculatorApp"].STARTUP_REFRESH_ENABLED = False
build_mt5_set_template = APP["build_mt5_set_template"]
parse_mt5_history_csv = APP["parse_mt5_history_csv"]
validate_scenario = APP["RiskCalculatorApp"]._validate_scenario
read_broker_contract_csv = APP["RiskCalculatorApp"]._read_broker_contract_csv
transaction_costs = APP["RiskCalculatorApp"]._transaction_costs
historical_mode = APP["HISTORICAL_STRESS_MODE"]
historical_drawdown_mode = APP["HISTORICAL_DRAWDOWN_MODE"]
historical_stress_move = APP["historical_stress_move"]
legacy_historical_mode = APP["LEGACY_HISTORICAL_STRESS_MODE"]


class PropWebsiteTests(unittest.TestCase):
    HTML = """
    <table><tr><th>Stage</th><th>Risk</th></tr>
    <tr><td>Evaluation</td><td>5,5% daily, 11% total</td></tr>
    <tr><td>Funded</td><td>4.5% daily, 11% total</td></tr></table>
    """

    @staticmethod
    def snapshot():
        return {
            "source": "https://example.com/program",
            "fetched_at": "2026-10-20T00:00:00+00:00",
            "candidates": APP["extract_prop_website_rules"](PropWebsiteTests.HTML),
        }

    def test_extracts_stages_without_mixing_them(self) -> None:
        rows = APP["extract_prop_website_rules"](self.HTML)
        self.assertEqual([row["daily_percent"] for row in rows], ["5.5", "4.5"])
        self.assertEqual([row["total_percent"] for row in rows], ["11", "11"])
        self.assertEqual(rows[0]["stage"], "Evaluation")
        self.assertIn("5,5% daily", rows[0]["evidence"])

    def test_extracts_separate_named_columns_and_ignores_scripts(self) -> None:
        html = """
        <script><table><tr><td>1% daily 99% total</td></tr></table></script>
        <table><tr><th>Plan</th><th>Daily loss</th><th>Total loss</th></tr>
        <tr><td>A</td><td><b>4%</b></td><td>10%</td></tr></table>
        """
        rows = APP["extract_prop_website_rules"](html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["daily_percent"], "4")

    def test_missing_ambiguous_and_invalid_percentage_rows_are_not_inferred(self) -> None:
        for html in (
            "<p>Daily 4%, Total 10%</p>",
            "<table><tr><td>Plan</td><td>4% daily</td></tr></table>",
            "<table><tr><th>Daily</th><th>Total</th></tr>"
            "<tr><td>4% or 5%</td><td>10%</td></tr></table>",
            "<table><tr><td>Plan</td><td>20% daily, 10% total</td></tr></table>",
            "<table><tr><td>Plan</td><td>4% daily or 5% daily, 10% total</td>"
            "</tr></table>",
        ):
            with self.subTest(html=html):
                self.assertEqual(APP["extract_prop_website_rules"](html), [])

    def test_fetch_validates_https_and_returns_source_and_date(self) -> None:
        fetch = APP["fetch_prop_website"]

        class Response(io.BytesIO):
            headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

            def geturl(self):
                return "https://example.com/program"

        with patch.dict(
            fetch.__globals__, urlopen=lambda *_args, **_kwargs: Response(
                self.HTML.encode("utf-8")
            )
        ):
            snapshot = fetch("https://example.com/program")
        self.assertEqual(snapshot["source"], "https://example.com/program")
        self.assertEqual(len(snapshot["candidates"]), 2)
        datetime.fromisoformat(snapshot["fetched_at"])
        for url in ("http://example.com", "https://user:pass@example.com", "file:///x"):
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                fetch(url)

    def test_no_table_response_reports_manual_entry_instead_of_default_limits(self) -> None:
        fetch = APP["fetch_prop_website"]

        class Response(io.BytesIO):
            headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

            def geturl(self):
                return "https://example.com/program"

        with patch.dict(
            fetch.__globals__, urlopen=lambda *_args, **_kwargs: Response(b"<p>Loading</p>")
        ):
            with self.assertRaisesRegex(ValueError, "manual entry"):
                fetch("https://example.com/program")

    def test_invalid_snapshot_is_rejected(self) -> None:
        snapshot = self.snapshot()
        snapshot["candidates"][0]["daily_percent"] = "NaN"
        with self.assertRaisesRegex(ValueError, "finite"):
            APP["RiskCalculatorApp"]._validate_prop_website_snapshot(snapshot)

    def test_fetch_failure_and_oversized_response_are_explicit(self) -> None:
        fetch = APP["fetch_prop_website"]

        class Response(io.BytesIO):
            headers = SimpleNamespace(get_content_charset=lambda: "utf-8")

            def geturl(self):
                return "https://example.com/program"

        with patch.dict(
            fetch.__globals__,
            urlopen=lambda *_args, **_kwargs: Response(b"x" * (2 * 1024 * 1024 + 1)),
        ):
            with self.assertRaisesRegex(ValueError, "2 MiB"):
                fetch("https://example.com/program")

        def offline(*_args, **_kwargs):
            raise OSError("offline")

        with patch.dict(fetch.__globals__, urlopen=offline):
            with self.assertRaisesRegex(ValueError, "offline"):
                fetch("https://example.com/program")


class MT5TerminalDataTests(unittest.TestCase):
    def test_inspection_returns_broker_symbols_when_existing_portfolio_symbol_is_missing(self) -> None:
        mt5 = SimpleNamespace(
            terminal_info=lambda: SimpleNamespace(path="MT5", connected=True),
            account_info=lambda: SimpleNamespace(currency="USD", trade_mode=0),
            symbols_get=lambda: [SimpleNamespace(name="US500.cash")],
            symbol_select=lambda *_args: False,
        )
        result = APP["inspect_mt5_terminal"](mt5_module=mt5, requested_symbols=("US500",))
        self.assertEqual(result["symbols"], "US500.cash")
        self.assertIn("WARNING", result["risk_details"])

    def test_inspection_reads_margin_estimates_and_raw_swap_without_sending_orders(self) -> None:
        calculate = unittest.mock.Mock(side_effect=[10, 12])
        mt5 = SimpleNamespace(
            terminal_info=lambda: SimpleNamespace(path="MT5", connected=True),
            account_info=lambda: SimpleNamespace(currency="USD", trade_mode=0),
            symbols_get=lambda: [SimpleNamespace(name="US500")],
            symbol_select=lambda *_args: True,
            symbol_info=lambda _symbol: SimpleNamespace(
                volume_min=.1, swap_long=-2, swap_short=1, swap_mode=1,
                swap_rollover3days=3, point=.01,
            ),
            symbol_info_tick=lambda _symbol: SimpleNamespace(ask=100, bid=99),
            order_calc_margin=calculate, ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
        )
        result = APP["inspect_mt5_terminal"](mt5_module=mt5, requested_symbols=("US500",))
        self.assertEqual(calculate.call_count, 2)
        self.assertIn("BUY margin/lot estimate=1.0E+2", result["risk_details"])
        self.assertIn("SELL margin/lot estimate=1.2E+2", result["risk_details"])
        self.assertIn("raw swap_long=-2", result["risk_details"])
        self.assertIn("NOT normalized cash", result["risk_details"])

    def test_inspection_identifies_demo_server_and_lists_exact_symbols_without_login(self) -> None:
        initialize = unittest.mock.Mock(return_value=True)
        shutdown = unittest.mock.Mock()
        mt5 = SimpleNamespace(
            terminal_info=lambda: SimpleNamespace(path=r"C:\MT5", connected=True),
            account_info=lambda: SimpleNamespace(
                company="Demo Broker", server="Demo-01", currency="EUR",
                trade_mode=0, leverage=30, margin_free=25000,
            ),
            symbols_get=lambda: [
                SimpleNamespace(name="US500.cash"), SimpleNamespace(name="DE40.demo"),
            ],
            initialize=initialize, shutdown=shutdown,
        )
        status = APP["inspect_mt5_terminal"](r"C:\MT5\terminal64.exe", mt5)
        initialize.assert_called_once_with(r"C:\MT5\terminal64.exe")
        shutdown.assert_called_once()
        self.assertEqual(status["account_type"], "DEMO")
        self.assertEqual(status["server"], "Demo-01")
        self.assertEqual(status["symbols"], "DE40.demo\nUS500.cash")
        self.assertNotIn("login", status)

    def test_inspection_reports_missing_terminal_and_releases_owned_connection(self) -> None:
        shutdown = unittest.mock.Mock()
        mt5 = SimpleNamespace(
            terminal_info=lambda: None,
            initialize=lambda: True,
            account_info=lambda: SimpleNamespace(currency="USD"),
            shutdown=shutdown,
        )
        with self.assertRaisesRegex(ValueError, "information is unavailable"):
            APP["inspect_mt5_terminal"](mt5_module=mt5)
        shutdown.assert_called_once()

    def test_reads_contract_quote_and_five_year_daily_bars_from_terminal_api(self) -> None:
        class Rate(dict):
            dtype = SimpleNamespace(
                names=("time", "open", "high", "low", "close", "spread")
            )

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        rates = [
            Rate(
                time=int((start + timedelta(days=index)).timestamp()),
                open=100,
                high=102,
                low=98,
                close=100,
                spread=8,
            )
            for index in range(20)
        ]
        mt5 = SimpleNamespace(
            TIMEFRAME_D1=1,
            terminal_info=lambda: object(),
            account_info=lambda: SimpleNamespace(currency="USD"),
            symbol_select=lambda _symbol, _visible: True,
            symbol_info=lambda _symbol: SimpleNamespace(
                point=0.01,
                trade_tick_size=0.01,
                trade_tick_value_profit=1,
                trade_tick_value=1,
                volume_step=0.01,
                volume_min=0.01,
                volume_max=100,
                currency_profit="USD",
            ),
            copy_rates_range=lambda *_args: rates,
            symbol_info_tick=lambda _symbol: SimpleNamespace(
                ask=100.2,
                bid=100.1,
                time=int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()),
            ),
            shutdown=lambda: None,
            last_error=lambda: (0, "ok"),
        )
        account_currency, data = APP["fetch_mt5_terminal_data"](
            ["US500.cash"],
            mt5_module=mt5,
        )

        symbol = data["US500.CASH"]
        self.assertEqual(account_currency, "USD")
        self.assertEqual(symbol.contract["point_value"], "1")
        self.assertEqual(symbol.contract["contract_currency"], "USD")
        self.assertEqual(symbol.contract["minimum_lot"], "0.01")
        self.assertEqual(symbol.quote[0], Decimal("100.2"))
        self.assertEqual(len(symbol.bars), 20)
        self.assertEqual(symbol.bars[0].spread_points, Decimal("8"))

    def test_rejects_terminal_that_cannot_initialize(self) -> None:
        mt5 = SimpleNamespace(
            terminal_info=lambda: None,
            initialize=lambda: False,
            last_error=lambda: (-10004, "no IPC connection"),
        )
        with self.assertRaisesRegex(ValueError, "no IPC connection"):
            APP["fetch_mt5_terminal_data"](["US500"], mt5_module=mt5)


class BrokerAPIDataTests(unittest.TestCase):
    @staticmethod
    def _payload(symbol: str = "US500") -> dict:
        bars = []
        start = date(2022, 1, 1)
        for index in range(20):
            close = Decimal("4000") + Decimal(index)
            bars.append({
                "date": (start + timedelta(days=index)).isoformat(),
                "open": str(close),
                "high": str(close + 2),
                "low": str(close - 2),
                "close": str(close + 1),
                "spread_points": "3",
                "spread_sample_count": 10,
            })
        return {
            "account_currency": "USD",
            "symbol": symbol,
            "quote": {
                "price": "4021",
                "currency": "USD",
                "time": "2026-10-20T10:00:00Z",
            },
            "contract": {
                "point_size": "0.1",
                "point_value_per_point_per_lot": "1.25",
                "points_per_ea_pip": "10",
                "lot_step": "0.01",
                "min_lot": "0.01",
                "max_lot": "100",
                "commission_per_lot": "2.5",
                "contract_currency": "USD",
            },
            "bars": bars,
        }

    def test_fetches_and_parses_normalized_https_api_response(self) -> None:
        response_payload = self._payload()
        response_body = json.dumps(response_payload).encode("utf-8")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return response_body

        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["headers"] = dict(request.header_items())
            observed["timeout"] = timeout
            return Response()

        fetch = APP["fetch_broker_api_data"]
        with patch.dict(fetch.__globals__, urlopen=fake_urlopen):
            currency, rows = fetch(
                "https://broker.example/history?symbol={symbol}&from={start}"
                "&to={end}&interval={interval}",
                "private-test-token",
                ["US500"],
            )

        symbol_data = rows["US500"]
        self.assertEqual(currency, "USD")
        self.assertEqual(symbol_data.contract["point_value"], "1.25")
        self.assertEqual(symbol_data.contract["maximum_lot"], "100")
        self.assertEqual(symbol_data.quote[0], Decimal("4021"))
        self.assertEqual(len(symbol_data.bars), 20)
        self.assertIn("symbol=US500", observed["url"])
        self.assertEqual(observed["timeout"], 30)
        self.assertEqual(
            observed["headers"]["Authorization"], "Bearer private-test-token"
        )

    def test_rejects_http_urls_and_credentials_in_query(self) -> None:
        validate = APP["validate_broker_api_endpoint"]
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate("http://broker.example/history?symbol={symbol}")
        with self.assertRaisesRegex(ValueError, "credentials"):
            validate(
                "https://broker.example/history?token=secret&symbol={symbol}"
            )

    def test_rejects_invalid_bars_and_contract_data(self) -> None:
        parse = APP["_parse_broker_api_symbol_data"]
        payload = self._payload()
        payload["bars"].pop()
        with self.assertRaisesRegex(ValueError, "20 valid daily bars"):
            parse(payload, "US500")

        payload = self._payload()
        payload["bars"][0]["close"] = "99999"
        with self.assertRaisesRegex(ValueError, "inconsistent OHLC"):
            parse(payload, "US500")

        payload = self._payload()
        payload["contract"]["point_size"] = "0"
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            parse(payload, "US500")

    def test_rejects_mismatched_symbol_and_account_currency(self) -> None:
        parse = APP["_parse_broker_api_symbol_data"]
        with self.assertRaisesRegex(ValueError, "does not match"):
            parse(self._payload("US100"), "US500")
        payload = self._payload()
        payload["contract"]["contract_currency"] = "EUR"
        with self.assertRaisesRegex(ValueError, "must match account_currency"):
            parse(payload, "US500")


class YahooQuoteTests(unittest.TestCase):
    def _fetch(self, chart: dict):
        fetch = APP["fetch_yahoo_quote"]
        with patch.dict(fetch.__globals__, _fetch_yahoo_chart=lambda *args: chart):
            return fetch("^GSPC")

    def test_fallback_close_must_be_an_array_not_text_or_mapping(self) -> None:
        for closes in ("123", {"100": 1}, None, 100):
            with self.subTest(closes=closes):
                with self.assertRaisesRegex(ValueError, "malformed.*quote"):
                    self._fetch({"indicators": {"quote": [{"close": closes}]}})

    def test_fallback_quote_container_requires_a_list(self) -> None:
        for quotes in ({0: {"close": [100]}}, "invalid", 100):
            with self.subTest(quotes=quotes):
                with self.assertRaisesRegex(ValueError, "malformed.*quote"):
                    self._fetch({"indicators": {"quote": quotes}})

    def test_valid_fallback_uses_last_nonempty_close(self) -> None:
        result = self._fetch({
            "meta": {"currency": "USD"},
            "indicators": {"quote": [{"close": [99, None, 101, None]}]},
        })
        self.assertEqual(result, (Decimal("101"), "USD", "^GSPC", "time unavailable"))

    def test_invalid_supplied_market_time_is_explicitly_rejected(self) -> None:
        for timestamp in (True, False, "invalid", [], float("inf"), 10**30):
            with self.subTest(timestamp=timestamp):
                with self.assertRaisesRegex(ValueError, "invalid.*time"):
                    self._fetch({"meta": {
                        "regularMarketPrice": 100, "regularMarketTime": timestamp,
                    }})

    def test_epoch_market_time_is_not_treated_as_missing(self) -> None:
        result = self._fetch({"meta": {
            "regularMarketPrice": 100, "regularMarketTime": 0,
        }})
        self.assertNotEqual(result[3], "time unavailable")

    def test_metadata_quote_does_not_require_fallback_arrays(self) -> None:
        result = self._fetch({
            "meta": {"regularMarketPrice": 100, "currency": "USD", "symbol": "^GSPC"},
            "indicators": None,
        })
        self.assertEqual(result, (Decimal("100"), "USD", "^GSPC", "time unavailable"))

    def test_malformed_quote_is_delivered_as_a_failed_request(self) -> None:
        request = APP["RiskCalculatorApp"]._request_yahoo_data
        with patch.dict(
            request.__globals__,
            _fetch_yahoo_chart=lambda *args: {"indicators": {"quote": [{"close": "123"}]}},
        ):
            result = request("allocation-1", "^GSPC")
        self.assertIsNone(result.quote)
        self.assertIsNone(result.history)
        self.assertIn("Price request failed", result.error)


class YahooHistoryTests(unittest.TestCase):
    def _chart(self) -> dict:
        return {
            "timestamp": [1767225600 + index * 86400 for index in range(21)],
            "indicators": {"quote": [{
                "high": [101] * 21, "low": [99] * 21, "close": [100] * 21,
            }]},
        }

    def _fetch(self, chart: dict):
        fetch = APP["fetch_yahoo_historical_stress"]
        with patch.dict(fetch.__globals__, _fetch_yahoo_chart=lambda *args: chart):
            return fetch("^GSPC")

    def test_complete_history_keeps_all_bars_and_extreme_move(self) -> None:
        chart = self._chart()
        chart["indicators"]["quote"][0]["low"][10] = 50
        stress = self._fetch(chart)
        self.assertEqual(stress.bar_count, 21)
        self.assertEqual(stress.long_adverse_pct, Decimal("51"))
        self.assertEqual(stress.long_observed_date, "2026-01-11")

    def test_truncated_price_arrays_are_not_silently_ignored(self) -> None:
        for field in ("high", "low", "close"):
            with self.subTest(field=field):
                chart = self._chart()
                chart["indicators"]["quote"][0][field].pop()
                with self.assertRaisesRegex(ValueError, "length"):
                    self._fetch(chart)

    def test_extra_price_values_are_rejected(self) -> None:
        chart = self._chart()
        chart["indicators"]["quote"][0]["high"].append(999)
        with self.assertRaisesRegex(ValueError, "length"):
            self._fetch(chart)

    def test_partial_missing_bar_is_not_dropped_from_stress_history(self) -> None:
        for field in ("high", "low", "close"):
            with self.subTest(field=field):
                chart = self._chart()
                chart["indicators"]["quote"][0][field][10] = None
                with self.assertRaisesRegex(ValueError, "bar 11.*missing"):
                    self._fetch(chart)

    def test_fully_missing_bar_is_reported_instead_of_dropped(self) -> None:
        chart = self._chart()
        for field in ("high", "low", "close"):
            chart["indicators"]["quote"][0][field][10] = None
        with self.assertRaisesRegex(ValueError, "bar 11.*missing"):
            self._fetch(chart)

    def test_invalid_timestamps_have_explicit_errors(self) -> None:
        for value in (True, None, "invalid", float("inf"), 10**30):
            with self.subTest(value=value):
                chart = self._chart()
                chart["timestamp"][10] = value
                with self.assertRaisesRegex(ValueError, "timestamp.*bar 11"):
                    self._fetch(chart)

    def test_duplicate_or_unordered_dates_are_rejected(self) -> None:
        for timestamp in (1767225600, 1767139200):
            with self.subTest(timestamp=timestamp):
                chart = self._chart()
                chart["timestamp"][10] = timestamp
                with self.assertRaisesRegex(ValueError, "ascending dates"):
                    self._fetch(chart)

    def test_incomplete_history_becomes_explicit_partial_request_result(self) -> None:
        chart = self._chart()
        chart["indicators"]["quote"][0]["close"][10] = None
        request = APP["RiskCalculatorApp"]._request_yahoo_data
        quote = (Decimal("100"), "USD", "^GSPC", "now")
        with patch.dict(
            request.__globals__,
            _fetch_yahoo_chart=lambda *args: chart,
            fetch_yahoo_quote=lambda ticker: quote,
        ):
            result = request("allocation-1", "^GSPC")
        self.assertEqual(result.quote, quote)
        self.assertIsNone(result.history)
        self.assertIn("bar 11", result.error)
        self.assertIn("missing prices", result.error)


class MT5HistoryCsvTests(unittest.TestCase):
    def test_rejects_duplicate_timestamp_instead_of_double_counting_samples(self) -> None:
        for second_close in ("100", "101"):
            with self.subTest(second_close=second_close):
                text = (
                    "symbol,date,time,high,low,close,spread_sample_count\n"
                    "US500,2026-01-01,10:00,101,99,100,10\n"
                    f"US500,2026-01-01,10:00,101,99,{second_close},10\n"
                )
                with self.assertRaisesRegex(ValueError, "duplicate timestamp"):
                    parse_mt5_history_csv(text)

    def test_same_timestamp_for_different_symbols_is_valid(self) -> None:
        lines = ["symbol,date,time,high,low,close"]
        for index in range(20):
            day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            for symbol in ("US500", "US100"):
                lines.append(f"{symbol},{day},10:00,101,99,100")
        histories = parse_mt5_history_csv("\n".join(lines))
        self.assertEqual(set(histories), {"US500", "US100"})

    def test_rejects_invalid_time_instead_of_silently_using_midnight(self) -> None:
        for time_text in ("invalid", "25:00", "12:99"):
            with self.subTest(time_text=time_text):
                text = (
                    "symbol,date,time,high,low,close\n"
                    f"US500,2026-01-01,{time_text},101,99,100\n"
                )
                with self.assertRaisesRegex(ValueError, "row 2.*date/time"):
                    parse_mt5_history_csv(text)

    def test_rejects_truncated_csv_row_with_explicit_error(self) -> None:
        text = "symbol,date,time,high,low,close,open\nUS500,2026-01-01\n"
        with self.assertRaisesRegex(ValueError, "row 2.*missing columns"):
            parse_mt5_history_csv(text)

    def test_rejects_duplicate_normalized_headers(self) -> None:
        text = (
            "symbol,date,high,<HIGH>,low,close\n"
            "US500,2026-01-01,101,120,99,100\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate.*header"):
            parse_mt5_history_csv(text)

    def test_rejects_timezone_offsets_instead_of_mixing_session_dates(self) -> None:
        for timestamp in ("2026-01-01T10:00:00Z", "2026-01-01T10:00:00+02:00"):
            with self.subTest(timestamp=timestamp):
                text = f"symbol,date,high,low,close\nUS500,{timestamp},101,99,100\n"
                with self.assertRaisesRegex(ValueError, "row 2.*broker-local"):
                    parse_mt5_history_csv(text)

    def test_spread_falls_back_per_row_when_maximum_column_is_empty(self) -> None:
        lines = ["symbol,date,high,low,close,spread_max_points,spread"]
        for index in range(20):
            day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            maximum = "" if index == 0 else "9"
            lines.append(f"US500,{day},101,99,100,{maximum},7")
        bars = parse_mt5_history_csv("\n".join(lines))["US500"]
        self.assertEqual(bars[0].spread_points, Decimal("7"))
        self.assertEqual(bars[1].spread_points, Decimal("9"))

    def test_invalid_nonempty_maximum_spread_does_not_fall_back(self) -> None:
        text = (
            "symbol,date,high,low,close,spread_max_points,spread\n"
            "US500,2026-01-01,101,99,100,invalid,7\n"
        )
        with self.assertRaisesRegex(ValueError, "row 2.*spread"):
            parse_mt5_history_csv(text)

    def test_rejects_mixed_timeframes_for_the_same_symbol(self) -> None:
        text = (
            "symbol,timeframe,date,time,high,low,close\n"
            "US500,PERIOD_D1,2026-01-01,00:00,101,99,100\n"
            "US500,PERIOD_H1,2026-01-01,01:00,101,99,100\n"
        )
        with self.assertRaisesRegex(ValueError, "row 3.*timeframes"):
            parse_mt5_history_csv(text)

    def test_imports_and_aggregates_intraday_rows_by_symbol_and_date(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            ("symbol", "timeframe", "date", "time", "open", "high", "low", "close")
        )
        start = date(2026, 1, 1)
        for index in range(20):
            day = (start + timedelta(days=index)).isoformat()
            writer.writerow(("US500", "PERIOD_H1", day, "10:00", 100, 101, 99, 100))
            if index == 5:
                writer.writerow(("US500", "PERIOD_H1", day, "11:00", 100, 104, 98, 103))

        histories = parse_mt5_history_csv(output.getvalue())

        self.assertEqual(len(histories["US500"]), 20)
        self.assertEqual(histories["US500"][5].high, 104)
        self.assertEqual(histories["US500"][5].low, 98)
        self.assertEqual(histories["US500"][5].close, 103)
        self.assertEqual(histories["US500"][5].open, 100)

    def test_daily_open_comes_from_earliest_row_even_when_csv_is_unsorted(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("symbol", "date", "time", "open", "high", "low", "close"))
        for index in range(20):
            day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            writer.writerow(("US500", day, "11:00", 102, 104, 98, 103))
            writer.writerow(("US500", day, "10:00", 100, 101, 99, 100))
            writer.writerow(("US500", day, "09:00", 99, 100, 98, 100))

        bar = parse_mt5_history_csv(output.getvalue())["US500"][0]

        self.assertEqual(bar.open, Decimal("99"))
        self.assertEqual(bar.close, Decimal("103"))

    def test_missing_first_intraday_open_is_not_replaced_with_a_later_open(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("symbol", "date", "time", "open", "high", "low", "close"))
        for index in range(20):
            day = (date(2026, 1, 1) + timedelta(days=index)).isoformat()
            writer.writerow(("US500", day, "11:00", 102, 104, 98, 103))
            writer.writerow(("US500", day, "10:00", "", 101, 99, 100))

        bar = parse_mt5_history_csv(output.getvalue())["US500"][0]

        self.assertIsNone(bar.open)

    def test_rejects_close_or_open_outside_individual_intraday_range(self) -> None:
        for opening, close in (("100", "102"), ("102", "100"), ("98", "100")):
            with self.subTest(opening=opening, close=close):
                text = (
                    "symbol,date,open,high,low,close\n"
                    f"US500,2026-01-01,{opening},101,99,{close}\n"
                )
                with self.assertRaisesRegex(ValueError, "invalid OHLC"):
                    parse_mt5_history_csv(text)

    def test_imports_maximum_intraday_spread_for_each_day(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                "symbol",
                "timeframe",
                "date",
                "time",
                "open",
                "high",
                "low",
                "close",
                "spread",
            )
        )
        start = date(2026, 1, 1)
        for index in range(20):
            day = (start + timedelta(days=index)).isoformat()
            writer.writerow(("US500", "PERIOD_H1", day, "10:00", 100, 101, 99, 100, 2))
            writer.writerow(("US500", "PERIOD_H1", day, "11:00", 100, 101, 99, 100, 7))

        histories = parse_mt5_history_csv(output.getvalue())

        self.assertEqual(histories["US500"][0].spread_points, Decimal("7"))

    def test_prefers_tick_max_spread_and_aggregates_sample_counts(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            (
                "symbol",
                "date",
                "time",
                "high",
                "low",
                "close",
                "spread",
                "spread_max_points",
                "spread_avg_points",
                "spread_sample_count",
            )
        )
        start = date(2026, 1, 1)
        for index in range(20):
            day = (start + timedelta(days=index)).isoformat()
            writer.writerow(("US500", day, "10:00", 101, 99, 100, 2, 8, 4, 12))
            if index == 0:
                writer.writerow(("US500", day, "11:00", 102, 98, 101, 3, 11, 5, 7))

        histories = parse_mt5_history_csv(output.getvalue())

        self.assertEqual(histories["US500"][0].spread_points, Decimal("11"))
        self.assertEqual(histories["US500"][0].spread_sample_count, 19)
        self.assertEqual(histories["US500"][0].high, Decimal("102"))
        self.assertEqual(histories["US500"][0].low, Decimal("98"))
        self.assertEqual(histories["US500"][0].close, Decimal("101"))

    def test_old_mt5_spread_column_remains_a_fallback(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("symbol", "date", "high", "low", "close", "spread"))
        start = date(2026, 1, 1)
        for index in range(20):
            writer.writerow(
                ("US500", (start + timedelta(days=index)).isoformat(), 101, 99, 100, 6)
            )

        histories = parse_mt5_history_csv(output.getvalue())

        self.assertEqual(histories["US500"][0].spread_points, Decimal("6"))
        self.assertIsNone(histories["US500"][0].spread_sample_count)
        self.assertIsNone(histories["US500"][0].open)

    def test_rejects_invalid_mt5_spread_sample_count(self) -> None:
        for value in ("-1", "1.5", "invalid"):
            with self.subTest(value=value):
                text = (
                    "symbol,date,high,low,close,spread_max_points,"
                    "spread_sample_count\n"
                    f"US500,2026-01-01,101,99,100,5,{value}\n"
                )
                with self.assertRaisesRegex(ValueError, "sample count"):
                    parse_mt5_history_csv(text)

    def test_rejects_negative_mt5_spread(self) -> None:
        text = "symbol,date,high,low,close,spread\nUS500,2026-01-01,101,99,100,-1\n"

        with self.assertRaisesRegex(ValueError, "negative spread"):
            parse_mt5_history_csv(text)

    def test_supports_mt5_angle_bracket_headers_and_single_symbol_default(self) -> None:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(("<DATE>", "<HIGH>", "<LOW>", "<CLOSE>"))
        start = date(2026, 1, 1)
        for index in range(20):
            writer.writerow(
                (
                    (start + timedelta(days=index)).strftime("%Y.%m.%d"),
                    101,
                    99,
                    100,
                )
            )

        histories = parse_mt5_history_csv(output.getvalue(), default_symbol="us500")

        self.assertEqual(len(histories["US500"]), 20)

    def test_requires_symbol_column_when_multiple_allocations_are_possible(self) -> None:
        text = "date,high,low,close\n2026-01-01,101,99,100\n"

        with self.assertRaisesRegex(ValueError, "needs a symbol column"):
            parse_mt5_history_csv(text)


class MT5ContractCsvTests(unittest.TestCase):
    def _read_text(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.csv"
            path.write_text(text, encoding="utf-8")
            return read_broker_contract_csv(str(path))

    def test_profit_currency_is_not_assumed_to_be_point_value_currency(self) -> None:
        contracts = self._read_text(
            "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot,profit_currency\n"
            "US500,0.1,1,0.01,0.01,USD\n"
        )
        self.assertEqual(contracts["US500"]["contract_currency"], "")

    def test_account_currency_is_distinct_from_profit_currency(self) -> None:
        contracts = self._read_text(
            "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot,"
            "account_currency,profit_currency\n"
            "US500,0.1,1,0.01,0.01,EUR,USD\n"
        )
        self.assertEqual(contracts["US500"]["contract_currency"], "EUR")

    def test_rejects_conflicting_alias_columns(self) -> None:
        text = (
            "symbol,point_size,point_value_per_point_per_lot,cash_per_point_per_lot,"
            "lot_step,min_lot\nUS500,0.1,1,10,0.01,0.01\n"
        )
        with self.assertRaisesRegex(ValueError, "row 2.*conflicting.*point_value"):
            self._read_text(text)

    def test_accepts_equivalent_numeric_aliases_and_blank_preferred_cells(self) -> None:
        text = (
            "symbol,point_size,point_value_per_point_per_lot,cash_per_point_per_lot,"
            "lot_step,min_lot\n"
            "US500,0.1,1,1.00,0.01,0.01\n"
            "US100,0.1,,2,0.01,0.01\n"
        )
        contracts = self._read_text(text)
        self.assertEqual(contracts["US500"]["point_value"], "1")
        self.assertEqual(contracts["US100"]["point_value"], "2")

    def test_rejects_conflicting_point_value_currency_columns(self) -> None:
        text = (
            "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot,"
            "account_currency,point_value_currency\n"
            "US500,0.1,1,0.01,0.01,EUR,USD\n"
        )
        with self.assertRaisesRegex(ValueError, "row 2.*conflicting.*contract_currency"):
            self._read_text(text)

    def test_rejects_duplicate_normalized_contract_headers(self) -> None:
        text = (
            "symbol,point_size,POINT-SIZE,point_value_per_point_per_lot,lot_step,min_lot\n"
            "US500,0.1,1,1,0.01,0.01\n"
        )
        with self.assertRaisesRegex(ValueError, "duplicate.*header"):
            self._read_text(text)

    def test_rejects_extra_or_missing_contract_columns(self) -> None:
        header = "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot\n"
        for row, message in (
            ("US500,0.1,1,0.01,0.01,extra\n", "too many columns"),
            ("US500,0.1,1,0.01\n", "missing columns"),
        ):
            with self.subTest(row=row):
                with self.assertRaisesRegex(ValueError, f"row 2.*{message}"):
                    self._read_text(header + row)

    def test_accepts_semicolon_csv_and_decimal_comma(self) -> None:
        contracts = self._read_text(
            "symbol;point_size;point_value_per_point_per_lot;lot_step;min_lot;account_currency\n"
            "US500;0,1;1,5;0,01;0,01;EUR\n"
        )
        self.assertEqual(contracts["US500"]["point_value"], "1.5")
        self.assertEqual(contracts["US500"]["point_size"], "0.1")

    def test_invalid_secondary_numeric_alias_is_not_ignored(self) -> None:
        for secondary in ("invalid", "NaN", "Infinity"):
            with self.subTest(secondary=secondary):
                text = (
                    "symbol,point_size,point_value_per_point_per_lot,cash_per_point_per_lot,"
                    f"lot_step,min_lot\nUS500,0.1,1,{secondary},0.01,0.01\n"
                )
                with self.assertRaisesRegex(ValueError, "row 2.*point_value"):
                    self._read_text(text)

    def test_equivalent_currency_aliases_ignore_case(self) -> None:
        contracts = self._read_text(
            "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot,"
            "account_currency,point_value_currency\n"
            "US500,0.1,1,0.01,0.01,eur,EUR\n"
        )
        self.assertEqual(contracts["US500"]["contract_currency"].upper(), "EUR")

    def test_imports_optional_broker_maximum_volume(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as source:
            source.write(
                "symbol,point_size,point_value_per_point_per_lot,lot_step,"
                "min_lot,max_lot,account_currency\n"
                "US500,0.1,1,0.01,0.01,50,USD\n"
            )
            path = source.name
        try:
            contracts = read_broker_contract_csv(path)
        finally:
            Path(path).unlink()

        self.assertEqual(contracts["US500"]["maximum_lot"], "50")

    def test_imports_per_symbol_commission_override(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as source:
            source.write(
                "symbol,point_size,point_value_per_point_per_lot,lot_step,"
                "min_lot,commission_per_lot\n"
                "US500,0.1,1,0.01,0.01,3.5\n"
            )
            path = source.name
        try:
            contracts = read_broker_contract_csv(path)
        finally:
            Path(path).unlink()

        self.assertEqual(contracts["US500"]["commission_per_lot"], "3.5")

    def test_rejects_maximum_volume_below_minimum(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", suffix=".csv", delete=False
        ) as source:
            source.write(
                "symbol,point_size,point_value_per_point_per_lot,lot_step,"
                "min_lot,max_lot\n"
                "US500,0.1,1,0.01,0.1,0.05\n"
            )
            path = source.name
        try:
            with self.assertRaisesRegex(ValueError, "maximum_lot cannot be below"):
                read_broker_contract_csv(path)
        finally:
            Path(path).unlink()


class MT5SetTemplateTests(unittest.TestCase):
    def test_builds_a_dca_template_with_enum_values(self) -> None:
        preset = build_mt5_set_template(
            "DCA",
            {
                "Magic Number": "10001",
                "Max Trades": "4",
                "Step Type": "enum_fixed_pips",
                "Step Value": "25",
                "Take Profit Type": "Enum_percentage_pips",
                "Take Profit Value": "0.5",
                "Risk Type": "Fixed lots",
                "Risk": "0.02",
                "Multiplier Factor": "1.0",
                "Entry on price break": "false",
                "InpPriceBreakType": "break Below",
                "Reference Price": "0",
                "Trade on new candle": "true",
                "Show Invested Money": "true",
            },
        )

        self.assertIn("StepType=1||0||0||0||N", preset)
        self.assertIn("TakeProfitType=0||0||0||0||N", preset)
        self.assertIn("InpPriceBreakType=0||0||0||0||N", preset)
        self.assertIn("EntryOnPriceBreak=false||0||0||0||N", preset)

    def test_builds_an_rsi_template_and_rejects_missing_settings(self) -> None:
        preset = build_mt5_set_template(
            "RSI",
            {
                "Magic Number": "10002",
                "Max Trades": "3",
                "Step Type": "Enum_percentage_pips",
                "Step Value": "0.5",
                "Take Profit Type": "enum_fixed_pips",
                "Take Profit Value": "20",
                "Risk Type": "Fixed lots",
                "Risk": "0.01",
                "Multiplier Factor": "1.0",
                "Close When Overbought": "true",
                "RSI oversold": "30",
                "RSI Overbought": "70",
                "RSI Period": "14",
                "Show Invested Money": "false",
            },
        )

        self.assertIn("StepType=0||0||0||0||N", preset)
        self.assertIn("TakeProfitType=1||0||0||0||N", preset)
        self.assertIn("RSIPeriod=14||0||0||0||N", preset)

        with self.assertRaisesRegex(ValueError, "missing 'Magic Number'"):
            build_mt5_set_template("RSI", {})


class ScenarioMigrationTests(unittest.TestCase):
    def test_account_allocation_percent_is_validated_and_legacy_capital_is_preserved(self) -> None:
        scenario = self._scenario(13)
        validated = validate_scenario(scenario)
        self.assertEqual(
            validated["allocations"][0]["allocation_percent"], ""
        )

        scenario["allocations"][0]["allocation_percent"] = "35"
        validated = validate_scenario(scenario)
        self.assertEqual(
            validated["allocations"][0]["allocation_percent"], "35"
        )

        for percentage in ("0", "-1", "100.01", "NaN", "Infinity"):
            with self.subTest(percentage=percentage):
                invalid = deepcopy(scenario)
                invalid["allocations"][0]["allocation_percent"] = percentage
                with self.assertRaises(ValueError):
                    validate_scenario(invalid)

    def test_account_allocation_percentages_cannot_exceed_100_percent(self) -> None:
        scenario = self._scenario(13)
        first = scenario["allocations"][0]
        first["allocation_percent"] = "60"
        second = deepcopy(first)
        scenario["allocations"].append(second)
        with self.assertRaisesRegex(ValueError, "cannot exceed 100%"):
            validate_scenario(scenario)

    def test_mt5_terminal_history_source_round_trips(self) -> None:
        scenario = self._history_scenario(13)
        scenario["allocations"][0]["history_source"] = "MT5 terminal"
        validated = validate_scenario(scenario)
        self.assertEqual(
            validated["allocations"][0]["history_source"], "MT5 terminal"
        )
        self.assertEqual(len(validated["allocations"][0]["history_bars"]), 20)

    def test_flat_mt5_history_round_trips_with_zero_stress(self) -> None:
        scenario = self._history_scenario(13)
        allocation = scenario["allocations"][0]
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("100"), Decimal("100"), Decimal("100"),
                spread_points=Decimal("5"), open=Decimal("100"),
            )
            for index in range(20)
        ]
        allocation["historical_stress"] = APP["RiskCalculatorApp"]._historical_stress_data(
            calculate_historical_stress(bars)
        )
        allocation["history_bars"] = [
            {
                "date": bar.date, "open": "100", "high": "100", "low": "100",
                "close": "100", "spread_points": "5",
            }
            for bar in bars
        ]
        validated = validate_scenario(scenario)
        stress = validated["allocations"][0]["historical_stress"]
        self.assertEqual(stress["long_adverse_pct"], "0")
        self.assertEqual(stress["short_adverse_pct"], "0")
        self.assertEqual(stress["long_observed_date"], "")
        self.assertEqual(stress["short_observed_date"], "")
        self.assertEqual(len(validated["allocations"][0]["history_bars"]), 20)

    def test_zero_daily_stress_requires_empty_observed_date(self) -> None:
        scenario = self._history_scenario(13)
        for field in ("long", "short"):
            with self.subTest(field=field):
                data = deepcopy(scenario)
                data["allocations"][0]["historical_stress"][f"{field}_adverse_pct"] = "0"
                with self.assertRaisesRegex(ValueError, "dates must be empty"):
                    validate_scenario(data)

    def test_positive_daily_stress_requires_observed_date(self) -> None:
        for direction in ("long", "short"):
            with self.subTest(direction=direction):
                data = self._history_scenario(13)
                data["allocations"][0]["historical_stress"][
                    f"{direction}_observed_date"
                ] = ""
                with self.assertRaisesRegex(ValueError, "needs an observed date"):
                    validate_scenario(data)

    def test_negative_daily_stress_is_rejected(self) -> None:
        for direction in ("long", "short"):
            with self.subTest(direction=direction):
                data = self._history_scenario(13)
                data["allocations"][0]["historical_stress"][
                    f"{direction}_adverse_pct"
                ] = "-1"
                with self.assertRaisesRegex(ValueError, "non-negative"):
                    validate_scenario(data)

    def test_mt5_bars_recompute_all_cached_history_statistics(self) -> None:
        scenario = self._history_scenario(13)
        cached = scenario["allocations"][0]["historical_stress"]
        cached.update(
            long_adverse_pct="99", short_adverse_pct="80",
            bar_count=999, start_date="2025-01-01", end_date="2027-01-01",
            long_observed_date="2025-01-02", short_observed_date="2025-01-03",
        )
        validated = validate_scenario(scenario)
        actual = validated["allocations"][0]["historical_stress"]
        expected = calculate_historical_stress([
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"), Decimal("99"), Decimal("100"),
                open=Decimal("99.5"),
            )
            for index in range(20)
        ])
        self.assertEqual(
            actual, APP["RiskCalculatorApp"]._historical_stress_data(expected)
        )

    def _history_scenario(self, version: int) -> dict[str, object]:
        scenario = self._scenario(version)
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"), Decimal("99"), Decimal("100"),
                open=Decimal("99.5"),
            )
            for index in range(20)
        ]
        allocation = scenario["allocations"][0]
        allocation["history_source"] = "MT5 CSV"
        allocation["quote"] = {
            "price": "100",
            "currency": "MT5 price",
            "symbol": "US500",
            "timestamp": bars[-1].date,
        }
        allocation["history_bars"] = [
            {
                "date": bar.date,
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                **({"open": str(bar.open)} if version >= 13 else {}),
            }
            for bar in bars
        ]
        allocation["historical_stress"] = APP["RiskCalculatorApp"]._historical_stress_data(
            calculate_historical_stress(bars)
        )
        return scenario

    def test_version_thirteen_preserves_optional_daily_opens(self) -> None:
        data = self._history_scenario(13)
        data["allocations"][0]["history_bars"][1]["open"] = ""

        validated = validate_scenario(data)
        bars = validated["allocations"][0]["history_bars"]

        self.assertEqual(bars[0]["open"], "99.5")
        self.assertEqual(bars[1]["open"], "")

    def test_old_scenarios_do_not_invent_missing_daily_opens(self) -> None:
        for version in range(7, 13):
            with self.subTest(version=version):
                validated = validate_scenario(self._history_scenario(version))
                self.assertEqual(
                    validated["allocations"][0]["history_bars"][0]["open"], ""
                )

    def test_scenario_rejects_invalid_open_or_close(self) -> None:
        for field, value in (("open", "102"), ("open", "NaN"), ("open", 100),
                             ("close", "98"), ("close", "102")):
            with self.subTest(field=field, value=value):
                data = self._history_scenario(13)
                data["allocations"][0]["history_bars"][0][field] = value
                with self.assertRaises(ValueError):
                    validate_scenario(data)

    def _scenario(self, version: int) -> dict[str, object]:
        contract = {
            "point_value": "",
            "point_size": "",
            "points_per_pip": "",
            "lot_increment": "",
            "minimum_lot": "",
            "contract_currency": "",
        }
        if version >= 10:
            contract["maximum_lot"] = ""
        if version >= 11:
            contract["commission_per_lot"] = ""
        text = {
            "magic_number": "10001",
            "step_type": "Percentage",
            "step_value": "0.5",
            "point_value": "",
            "point_size": "",
            "points_per_pip": "",
            "contract_currency": "",
            "stress_percent": "1",
            "stress_mode": legacy_historical_mode,
            "stress_target_price": "",
            "position_direction": "Long (price falls)",
            "lot_increment": "",
            "minimum_lot": "",
            "compare_trades": "10",
            "selected_trades": "3",
            "take_profit_type": "Fixed pips",
            "take_profit_value": "",
            "price_break_type": "break Below",
            "reference_price": "",
            "rsi_oversold": "30",
            "rsi_overbought": "70",
            "rsi_period": "14",
        }
        if version >= 7:
            text.update(
                {
                    "spread_points": "1",
                    "slippage_points": "2",
                    "commission_per_lot": "0.5",
                }
            )
        return {
            "format": "mt5-risk-planner-scenario",
            "version": version,
            "portfolio": {
                "account_capital": "10000",
                "currency": "USD",
                "daily_limit": "4.5",
                "limit_mode": "Percent of account",
                **(
                    {
                        "prop_total_loss_room": "",
                        "remaining_daily_loss_room": "",
                    }
                    if version >= 6
                    else {"prop_total_loss_room": ""}
                    if version >= 5
                    else {}
                ),
            },
            "new_allocation": {
                "symbol": "US500",
                "yahoo_ticker": "^GSPC",
                "robot": "DCA",
                "capital": "5000",
            },
            "allocations": [
                {
                    "symbol": "US500",
                    "yahoo_ticker": "^GSPC",
                    "robot": "DCA",
                    "capital": "5000",
                    "magic_number": None,
                    "broker_contract": contract,
                    "quote": None,
                    "historical_stress": None,
                    **(
                        {"history_source": "", "history_bars": []}
                        if version >= 7
                        else {}
                    ),
                }
            ],
            "settings": {
                "text": text,
                "options": {
                    "entry_on_price_break": False,
                    "trade_on_new_candle": True,
                    "show_dca_invested_money": True,
                    "close_when_overbought": True,
                    "show_rsi_invested_money": True,
                },
            },
            "selected_allocation": None,
        }

    def test_version_six_migrates_to_new_history_label_and_cost_defaults(self) -> None:
        scenario = validate_scenario(self._scenario(6))

        self.assertEqual(scenario["settings"]["text"]["stress_mode"], historical_mode)
        self.assertEqual(scenario["settings"]["text"]["spread_points"], "0")
        self.assertEqual(scenario["settings"]["text"]["commission_per_lot"], "0")

    def test_version_seven_validates_mt5_history_snapshot(self) -> None:
        scenario_data = self._scenario(7)
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
            )
            for index in range(20)
        ]
        stress = calculate_historical_stress(bars)
        allocation = scenario_data["allocations"][0]
        allocation["history_source"] = "MT5 CSV"
        allocation["quote"] = {
            "price": "100",
            "currency": "MT5 price",
            "symbol": "US500",
            "timestamp": bars[-1].date,
        }
        allocation["history_bars"] = [
            {
                "date": bar.date,
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
            }
            for bar in bars
        ]
        allocation["historical_stress"] = {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

        validated = validate_scenario(scenario_data)

        self.assertEqual(validated["allocations"][0]["history_source"], "MT5 CSV")
        self.assertEqual(len(validated["allocations"][0]["history_bars"]), 20)
        self.assertGreater(
            Decimal(
                validated["allocations"][0]["historical_stress"][
                    "long_drawdown_pct"
                ]
            ),
            Decimal("0"),
        )

    def test_peak_to_trough_mode_uses_the_multi_session_drawdown(self) -> None:
        start = date(2026, 1, 1)
        bars = [
            DailyBar(
                (start + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
            )
            for index in range(20)
        ]
        bars[5] = DailyBar(bars[5].date, Decimal("120"), Decimal("118"), Decimal("119"))
        bars[6] = DailyBar(bars[6].date, Decimal("119"), Decimal("90"), Decimal("95"))
        stress = calculate_historical_stress(bars)

        self.assertEqual(
            historical_stress_move(stress, historical_drawdown_mode, True),
            Decimal("25"),
        )
        self.assertEqual(
            historical_stress_move(stress, historical_mode, True),
            Decimal("2900") / Decimal("119"),
        )

    def test_version_eight_validates_historical_drawdown_fields(self) -> None:
        scenario_data = self._scenario(8)
        scenario_data["settings"]["text"]["stress_mode"] = historical_drawdown_mode
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
            )
            for index in range(20)
        ]
        bars[5] = DailyBar(bars[5].date, Decimal("120"), Decimal("118"), Decimal("119"))
        bars[6] = DailyBar(bars[6].date, Decimal("119"), Decimal("90"), Decimal("95"))
        stress = calculate_historical_stress(bars)
        allocation = scenario_data["allocations"][0]
        allocation["historical_stress"] = {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "long_drawdown_pct": str(stress.long_drawdown_pct),
            "long_drawdown_peak_date": stress.long_drawdown_peak_date,
            "long_drawdown_trough_date": stress.long_drawdown_trough_date,
            "short_rally_pct": str(stress.short_rally_pct),
            "short_rally_trough_date": stress.short_rally_trough_date,
            "short_rally_peak_date": stress.short_rally_peak_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

        validated = validate_scenario(scenario_data)

        self.assertEqual(
            validated["settings"]["text"]["stress_mode"],
            historical_drawdown_mode,
        )
        self.assertEqual(
            validated["allocations"][0]["historical_stress"]["long_drawdown_pct"],
            "25",
        )

    def test_version_nine_persists_optional_historical_spread(self) -> None:
        scenario_data = self._scenario(9)
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
                Decimal("3") if index == 4 else None,
            )
            for index in range(20)
        ]
        stress = calculate_historical_stress(bars)
        allocation = scenario_data["allocations"][0]
        allocation["history_source"] = "MT5 CSV"
        allocation["quote"] = {
            "price": "100",
            "currency": "MT5 price",
            "symbol": "US500",
            "timestamp": bars[-1].date,
        }
        allocation["history_bars"] = [
            {
                "date": bar.date,
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "spread_points": (
                    str(bar.spread_points) if bar.spread_points is not None else ""
                ),
            }
            for bar in bars
        ]
        allocation["historical_stress"] = {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "long_drawdown_pct": str(stress.long_drawdown_pct),
            "long_drawdown_peak_date": stress.long_drawdown_peak_date,
            "long_drawdown_trough_date": stress.long_drawdown_trough_date,
            "short_rally_pct": str(stress.short_rally_pct),
            "short_rally_trough_date": stress.short_rally_trough_date,
            "short_rally_peak_date": stress.short_rally_peak_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

        validated = validate_scenario(scenario_data)

        self.assertEqual(
            validated["allocations"][0]["history_bars"][4]["spread_points"],
            "3",
        )

    def test_version_ten_migrates_and_validates_optional_broker_maximum_volume(self) -> None:
        scenario_data = self._scenario(10)
        scenario_data["allocations"][0]["broker_contract"]["maximum_lot"] = "5"

        validated = validate_scenario(scenario_data)

        self.assertEqual(
            validated["allocations"][0]["broker_contract"]["maximum_lot"],
            "5",
        )

    def test_version_ten_rejects_broker_maximum_below_minimum(self) -> None:
        scenario_data = self._scenario(10)
        scenario_data["allocations"][0]["broker_contract"].update(
            {"minimum_lot": "0.1", "maximum_lot": "0.05"}
        )

        with self.assertRaisesRegex(ValueError, "cannot be below"):
            validate_scenario(scenario_data)

    def test_version_eleven_validates_per_symbol_commission(self) -> None:
        scenario_data = self._scenario(11)
        scenario_data["allocations"][0]["broker_contract"][
            "commission_per_lot"
        ] = "3.5"

        validated = validate_scenario(scenario_data)

        self.assertEqual(
            validated["allocations"][0]["broker_contract"]["commission_per_lot"],
            "3.5",
        )

    def test_version_eleven_rejects_negative_per_symbol_commission(self) -> None:
        scenario_data = self._scenario(11)
        scenario_data["allocations"][0]["broker_contract"][
            "commission_per_lot"
        ] = "-0.01"

        with self.assertRaisesRegex(ValueError, "commission must be non-negative"):
            validate_scenario(scenario_data)

    def test_version_twelve_persists_tick_spread_sample_counts(self) -> None:
        scenario_data = self._scenario(12)
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
                Decimal("7") if index == 4 else None,
                23 if index == 4 else 0,
            )
            for index in range(20)
        ]
        stress = calculate_historical_stress(bars)
        allocation = scenario_data["allocations"][0]
        allocation["history_source"] = "MT5 CSV"
        allocation["quote"] = {
            "price": "100",
            "currency": "MT5 price",
            "symbol": "US500",
            "timestamp": bars[-1].date,
        }
        allocation["history_bars"] = [
            {
                "date": bar.date,
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "spread_points": (
                    str(bar.spread_points) if bar.spread_points is not None else ""
                ),
                "spread_sample_count": (
                    str(bar.spread_sample_count)
                    if bar.spread_sample_count is not None
                    else ""
                ),
            }
            for bar in bars
        ]
        allocation["historical_stress"] = {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "long_drawdown_pct": str(stress.long_drawdown_pct),
            "long_drawdown_peak_date": stress.long_drawdown_peak_date,
            "long_drawdown_trough_date": stress.long_drawdown_trough_date,
            "short_rally_pct": str(stress.short_rally_pct),
            "short_rally_trough_date": stress.short_rally_trough_date,
            "short_rally_peak_date": stress.short_rally_peak_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

        validated = validate_scenario(scenario_data)

        self.assertEqual(
            validated["allocations"][0]["history_bars"][4][
                "spread_sample_count"
            ],
            "23",
        )

    def test_scenario_rejects_negative_tick_spread_sample_count(self) -> None:
        scenario_data = self._scenario(12)
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"),
                Decimal("99"),
                Decimal("100"),
            )
            for index in range(20)
        ]
        stress = calculate_historical_stress(bars)
        allocation = scenario_data["allocations"][0]
        allocation["history_source"] = "MT5 CSV"
        allocation["quote"] = {
            "price": "100",
            "currency": "MT5 price",
            "symbol": "US500",
            "timestamp": bars[-1].date,
        }
        allocation["history_bars"] = [
            {
                "date": bar.date,
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "spread_points": "",
                "spread_sample_count": "-1" if index == 0 else "0",
            }
            for index, bar in enumerate(bars)
        ]
        allocation["historical_stress"] = {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "long_drawdown_pct": str(stress.long_drawdown_pct),
            "long_drawdown_peak_date": stress.long_drawdown_peak_date,
            "long_drawdown_trough_date": stress.long_drawdown_trough_date,
            "short_rally_pct": str(stress.short_rally_pct),
            "short_rally_trough_date": stress.short_rally_trough_date,
            "short_rally_peak_date": stress.short_rally_peak_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

        with self.assertRaisesRegex(ValueError, "sample count must be non-negative"):
            validate_scenario(scenario_data)

    def test_symbol_commission_override_replaces_common_fallback(self) -> None:
        class Value:
            def __init__(self, text: str) -> None:
                self.text = text

            def get(self) -> str:
                return self.text

        app = SimpleNamespace(
            spread_points_var=Value("1"),
            slippage_points_var=Value("2"),
            commission_per_lot_var=Value("0.5"),
        )

        costs = transaction_costs(app, {"commission_per_lot": "3.5"})

        self.assertEqual(costs, (Decimal("1"), Decimal("2"), Decimal("3.5")))

    def test_rejects_negative_symbol_commission_override(self) -> None:
        class Value:
            def __init__(self, text: str) -> None:
                self.text = text

            def get(self) -> str:
                return self.text

        app = SimpleNamespace(
            spread_points_var=Value("1"),
            slippage_points_var=Value("2"),
            commission_per_lot_var=Value("0.5"),
        )

        with self.assertRaisesRegex(ValueError, "non-negative"):
            transaction_costs(app, {"commission_per_lot": "-1"})

    def test_blank_symbol_commission_uses_common_fallback(self) -> None:
        class Value:
            def __init__(self, text: str) -> None:
                self.text = text

            def get(self) -> str:
                return self.text

        app = SimpleNamespace(
            spread_points_var=Value("1"),
            slippage_points_var=Value("2"),
            commission_per_lot_var=Value("0.5"),
        )

        costs = transaction_costs(app, {"commission_per_lot": ""})

        self.assertEqual(costs, (Decimal("1"), Decimal("2"), Decimal("0.5")))


class CandidateGenerationTests(unittest.TestCase):
    def test_mt5_symbol_selection_only_prefills_new_allocation_without_mutating_existing(self) -> None:
        before = dict(self.app.allocations)
        self.app.mt5_connection = {"symbols": "US500.cash\nDE40.demo"}
        self.app._use_mt5_symbol("US500.cash")
        self.assertEqual(self.app.index_var.get(), "US500.cash")
        self.assertEqual(self.app.allocations, before)
        with patch.object(APP["messagebox"], "showerror") as error:
            self.app._use_mt5_symbol("not returned by broker")
        error.assert_called_once()
        self.assertEqual(self.app.index_var.get(), "US500.cash")

    def _enable_advanced_checks(self) -> None:
        profile = default_profile()
        profile.update(
            enabled=True, current_equity="9900", daily_start_equity="10000",
            daily_start_balance="10000", total_limit_pct="10", high_water_equity="10500",
            daily_session_date=datetime.now(timezone.utc).date().isoformat(),
            free_margin="9900", existing_margin="0", stopout_pct="50",
            idea_limit_pct="2", holding_days="3",
        )
        self.app.risk_profile = profile
        self.app.daily_limit_var.set("5")
        self.app.limit_mode_var.set("Percent of account")
        self.app.exposure_inputs[self.row] = {
            **default_exposure(), "margin_per_lot": "100",
            "swap_long_debit": "2", "swap_short_debit": "3", "idea_group": "US index",
        }

    def test_advanced_risk_profile_and_exposure_migrate_and_roundtrip(self) -> None:
        self._enable_advanced_checks()
        saved = self.app._scenario_data()
        self.assertEqual(saved["version"], 14)
        self.app._apply_scenario(validate_scenario(saved))
        row = next(iter(self.app.allocations))
        self.assertEqual(self.app.exposure_inputs[row]["swap_long_debit"], "2")
        self.assertTrue(self.app.risk_profile["enabled"])
        old = deepcopy(saved)
        old["version"] = 13
        self.app._apply_scenario(validate_scenario(old))
        self.assertFalse(self.app.risk_profile["enabled"])
        self.assertEqual(self.app.exposure_inputs[next(iter(self.app.allocations))],
                         default_exposure())

    def test_version_14_rejects_missing_or_invalid_advanced_fields(self) -> None:
        saved = self.app._scenario_data()
        del saved["risk_profile"]
        with self.assertRaisesRegex(ValueError, "profile"):
            validate_scenario(saved)
        saved = self.app._scenario_data()
        saved["allocations"][0]["exposure_inputs"]["swap_long_debit"] = "-1"
        with self.assertRaises(ValueError):
            validate_scenario(saved)

    def test_prepaid_swap_reserve_affects_both_directions_and_missing_cost_blocks(self) -> None:
        self._enable_advanced_checks()
        self.app.symbol_commission_per_lot_var.set("7")
        contract = self.app._contract_inputs_for_allocation(self.row)
        self.assertEqual(self.app._sizing_costs(self.row, contract)[2], Decimal("13"))
        self.app.position_direction_var.set("Short (price rises)")
        self.assertEqual(self.app._sizing_costs(self.row, contract)[2], Decimal("16"))
        self.app.exposure_inputs[self.row]["swap_short_debit"] = ""
        with self.assertRaisesRegex(ValueError, "verified swap_short"):
            self.app._sizing_costs(self.row, contract)

    def test_explicit_equity_rules_tighten_daily_and_total_rooms(self) -> None:
        self._enable_advanced_checks()
        self.app.risk_profile["idea_limit_pct"] = "10"
        limits = self.app._portfolio_risk_limits()
        self.assertEqual(limits[2:5], (Decimal("400"), Decimal("900"), Decimal("400")))
        self.app.risk_profile.update(overall_rule="Trailing equity", high_water_equity="10800")
        limits = self.app._portfolio_risk_limits()
        self.assertEqual(limits[3:5], (Decimal("100"), Decimal("100")))

    def test_correlated_idea_cap_restricts_candidate_budget_before_sizing(self) -> None:
        self._enable_advanced_checks()
        self.app.allocation_percentages[self.row] = Decimal("100")
        self.assertEqual(self.app._portfolio_risk_limits()[4], Decimal("200"))

    def test_advanced_margin_failure_rejects_candidate_and_blocks_full_suggestion(self) -> None:
        self._enable_advanced_checks()
        self.app.exposure_inputs[self.row]["margin_per_lot"] = "100000000"
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("PORTFOLIO VERDICT: REJECTED", report)
        self.assertIn("free margin", report)
        self.assertIn("Overnight debit reserve: 6", report)
        self.assertIn("ADVANCED PROP / MARGIN", report)
        with self.assertRaisesRegex(ValueError, "advanced constraints"):
            self.app._generate_settings_checked(show_errors=False, require_complete_portfolio=True)

    def test_advanced_missing_margin_input_is_explicitly_unverified(self) -> None:
        self._enable_advanced_checks()
        self.app.exposure_inputs[self.row]["margin_per_lot"] = ""
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("ADVANCED MISSING: US500", report)
        self.assertIn("margin per lot", report)
        self.assertIn("PORTFOLIO VERDICT: UNVERIFIED", report)

    def test_exhausted_prop_floor_stops_candidate_generation(self) -> None:
        self._enable_advanced_checks()
        self.app.risk_profile["current_equity"] = "9000"
        with patch.object(APP["messagebox"], "showerror"):
            self.assertFalse(self.app._calculate_portfolio())
        self.assertIn("already reached/breached", self.app.status_var.get())

    def test_equity_csv_report_is_saved_with_curve_and_assumptions_not_candidate_approval(self) -> None:
        self._enable_advanced_checks()
        samples = parse_equity_csv(
            "timestamp,balance,equity\n"
            "2026-10-19T00:00:00Z,10000,10000\n"
            "2026-10-19T01:00:00Z,10000,9400\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            self.app.equity_report_path = str(Path(directory) / "equity_validation.json")
            report = self.app._evaluate_and_save_equity_curve(samples)
            saved = json.loads(Path(self.app.equity_report_path).read_text(encoding="utf-8"))
        self.assertIn("SAMPLED EQUITY VERDICT: BREACHED", report)
        self.assertIn("NOT the planner candidate", report)
        self.assertEqual(len(saved["samples"]), 2)
        self.assertEqual(saved["daily_limit"], "500")
        self.assertEqual(saved["risk_profile"], self.app.risk_profile)

    def test_enabled_advanced_checks_can_accept_a_fully_specified_manual_stress(self) -> None:
        self._enable_advanced_checks()
        self.app.stress_mode_var.set("Adverse move (%)")
        self.app.stress_pct_var.set("10")
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("PORTFOLIO VERDICT: ACCEPTED", report)
        self.assertNotIn("ADVANCED MISSING:", report)
        self.assertNotIn("ADVANCED BREACH:", report)
        self.assertIn("Overnight debit reserve: 6", report)

    def test_equity_import_and_saved_report_reopen_are_connected_to_ui(self) -> None:
        self._enable_advanced_checks()
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "equity.csv"
            csv_path.write_text(
                "timestamp,balance,equity\n2026-10-19T00:00:00Z,10000,10000\n"
                "2026-10-19T01:00:00Z,10000,9900\n", encoding="utf-8",
            )
            self.app.equity_report_path = str(Path(directory) / "equity_validation.json")
            with patch.object(APP["filedialog"], "askopenfilename", return_value=str(csv_path)), \
                    patch.object(APP["messagebox"], "askyesno", return_value=True), \
                    patch.object(self.app, "_show_equity_report") as show:
                self.app._import_equity_curve()
                self.assertIn("NO SAMPLED BREACH", show.call_args.args[0])
                self.app._open_saved_equity_report()
                self.assertIn("OFFLINE SNAPSHOT", show.call_args.args[0])
            self.assertTrue(Path(self.app.equity_report_path).exists())

    def test_advanced_profile_and_per_robot_inputs_survive_actual_local_autosave(self) -> None:
        self._enable_advanced_checks()
        self.app.AUTOSAVE_ENABLED = True
        with tempfile.TemporaryDirectory() as directory:
            self.app.autosave_path = str(Path(directory) / "portfolio.json")
            self.assertTrue(self.app._save_autosave_scenario())
            self.app.risk_profile = default_profile()
            self.app.exposure_inputs.clear()
            self.app._load_autosave_scenario()
            row = next(iter(self.app.allocations))
            self.assertTrue(self.app.risk_profile["enabled"])
            self.assertEqual(self.app.exposure_inputs[row]["swap_long_debit"], "2")
            self.assertEqual(self.app.exposure_inputs[row]["idea_group"], "US index")

    def test_equity_report_atomic_replace_failure_preserves_previous_snapshot(self) -> None:
        self._enable_advanced_checks()
        samples = parse_equity_csv(
            "timestamp,balance,equity\n2026-10-19T00:00:00Z,10000,10000\n"
            "2026-10-19T01:00:00Z,10000,9900\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equity_validation.json"
            path.write_text("original snapshot", encoding="utf-8")
            self.app.equity_report_path = str(path)
            with patch.object(APP["os"], "replace", side_effect=OSError("locked")):
                with self.assertRaisesRegex(OSError, "locked"):
                    self.app._evaluate_and_save_equity_curve(samples)
            self.assertEqual(path.read_text(encoding="utf-8"), "original snapshot")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_mt5_preferences_store_only_executable_and_restore_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "terminal64.exe"
            executable.touch()
            self.app.mt5_config_path = str(Path(directory) / "mt5_connection.json")
            self.app.mt5_terminal_path_var.set(str(executable))
            self.app._save_mt5_config()
            config = json.loads(Path(self.app.mt5_config_path).read_text(encoding="utf-8"))
            self.assertEqual(config, {"terminal_path": str(executable)})
            self.app.mt5_terminal_path_var.set("")
            self.app._load_mt5_config()
            self.assertEqual(self.app.mt5_terminal_path_var.get(), str(executable))

    def test_failed_mt5_inspection_keeps_portfolio_and_stops_spinner(self) -> None:
        before = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put((
            "__mt5_status__", "mt5_status_done",
            APP["MT5InspectionResult"]({}, "No terminal"),
        ))
        with patch.object(APP["messagebox"], "showerror") as error:
            self.app._poll_quote_result()
        error.assert_called_once()
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app._scenario_data(), before)

    def test_scenario_reload_cancels_mt5_inspection_result(self) -> None:
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(self.app._scenario_data()))
        self.app.quote_messages.put((
            "__mt5_status__", "mt5_status_done", APP["MT5InspectionResult"]({"server": "old"})
        ))
        with patch.object(self.app, "_show_data_status") as show:
            self.app._poll_quote_result()
        show.assert_not_called()
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app.mt5_connection, {})

    def test_manual_broker_api_currency_mismatch_preserves_account_rooms_and_data(self) -> None:
        before = self.app._scenario_data()
        response = APP["MT5PortfolioResult"]({}, "EUR")
        self.app.quote_messages.put(("__broker_api__", "broker_api_done", response))
        with patch.object(APP["messagebox"], "showerror") as error:
            self.app._poll_quote_result()
        error.assert_called_once()
        self.assertEqual(self.app._scenario_data(), before)

    def test_manual_mt5_currency_mismatch_leaves_all_account_and_market_data_unchanged(self) -> None:
        before = self.app._scenario_data()
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](
                dict(self.app.contract_inputs[self.row]),
                self.app.history_bars[self.row], self.app.quotes[self.row],
            )},
            "EUR",
        )
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put(("__mt5__", "mt5_done", response))
        with patch.object(APP["messagebox"], "showerror") as error, patch.object(
            self.app, "_suggest_portfolio_downside"
        ) as suggest:
            self.app._poll_quote_result()
        self.assertEqual(self.app._scenario_data(), before)
        error.assert_called_once()
        suggest.assert_not_called()
        self.assertFalse(self.app.quote_busy)

    def test_manual_mt5_reconnect_preserves_commission_and_ea_pip_conversion(self) -> None:
        self.app.contract_inputs[self.row]["commission_per_lot"] = "7"
        self.app.symbol_commission_per_lot_var.set("7")
        incoming = dict(self.app.contract_inputs[self.row])
        incoming.update(points_per_pip="", commission_per_lot="")
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](
                incoming, self.app.history_bars[self.row], self.app.quotes[self.row]
            )}, "USD",
        )
        self.app.quote_messages.put(("__mt5__", "mt5_done", response))
        with patch.object(self.app, "_suggest_portfolio_downside"):
            self.app._poll_quote_result()
        self.assertEqual(self.app.contract_inputs[self.row]["commission_per_lot"], "7")
        self.assertEqual(self.app.contract_inputs[self.row]["points_per_pip"], "1")

    def test_changed_contract_does_not_reuse_manual_inputs_or_autogenerate(self) -> None:
        self.app.contract_inputs[self.row]["commission_per_lot"] = "7"
        self.app.symbol_commission_per_lot_var.set("7")
        incoming = dict(self.app.contract_inputs[self.row])
        incoming.update(point_size="0.01", points_per_pip="", commission_per_lot="")
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](
                incoming, self.app.history_bars[self.row], self.app.quotes[self.row]
            )}, "USD",
        )
        self.app.quote_messages.put(("__mt5__", "mt5_done", response))
        with patch.object(APP["messagebox"], "showwarning") as warning, patch.object(
            self.app, "_suggest_portfolio_downside"
        ) as suggest:
            self.app._poll_quote_result()
        warning.assert_called_once()
        suggest.assert_not_called()
        self.assertEqual(self.app.contract_inputs[self.row]["commission_per_lot"], "")

    def test_history_quality_checks_actual_dates_and_seven_day_freshness(self) -> None:
        stress = self.app.historical_stresses[self.row]
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        complete = replace(
            stress, start_date="2021-10-20", end_date="2026-10-13", bar_count=1300
        )
        self.assertEqual(APP["history_quality_warnings"](complete, now), ())
        incomplete = replace(
            stress, start_date="2026-09-01", end_date="2026-10-12"
        )
        warnings = APP["history_quality_warnings"](incomplete, now)
        self.assertEqual(len(warnings), 3)
        self.assertIn("five-year", warnings[0])
        self.assertIn("stale", warnings[1])

    def test_history_quality_exact_sample_coverage_and_future_date_boundaries(self) -> None:
        stress = replace(
            self.app.historical_stresses[self.row],
            start_date="2021-11-03", end_date="2026-10-20", bar_count=1000,
        )
        now = datetime(2026, 10, 20, tzinfo=timezone.utc)
        quality = APP["history_quality_warnings"]
        self.assertEqual(quality(stress, now), ())
        self.assertIn("sparse", quality(replace(stress, bar_count=999), now)[0])
        self.assertIn(
            "five-year", quality(replace(stress, start_date="2021-11-04"), now)[0]
        )
        self.assertIn(
            "future", quality(replace(stress, end_date="2026-10-21"), now)[0]
        )

    def test_data_status_and_report_include_actual_coverage_and_warnings(self) -> None:
        status = self.app._data_status_text()
        self.assertIn(self.app.history_sources[self.row], status)
        self.assertIn("20 daily bars", status)
        self.assertIn("less than", status)
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("Actual history:", report)
        self.assertIn("HISTORY WARNING:", report)

    def test_short_stale_history_cannot_receive_accepted_verdict_even_with_loss_room(self) -> None:
        self.app.prop_total_loss_room_var.set("2000")
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("PORTFOLIO VERDICT: UNVERIFIED", report)
        self.assertNotIn("PORTFOLIO VERDICT: ACCEPTED", report)
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            self.app._generate_settings_checked(
                show_errors=False, require_complete_portfolio=True,
            )

    def _open_prop_preview(self) -> None:
        self.app.prop_website_snapshot = PropWebsiteTests.snapshot()
        self.app._open_prop_website_import()
        self.app.prop_preview_tree.selection_set("0")
        self.app._select_prop_rule()

    def test_website_import_only_changes_limits_after_review_and_confirmation(self) -> None:
        before = self.app._scenario_data()
        self._open_prop_preview()
        with patch.object(APP["messagebox"], "showerror") as error:
            self.app._apply_prop_website_rules()
        error.assert_called_once()
        self.assertEqual(before, self.app._scenario_data())
        self.app.prop_reviewed_var.set(True)
        self.app.prop_new_account_var.set(True)
        self.app.account_capital_var.set("25000")
        with patch.object(APP["messagebox"], "askyesno", return_value=True), patch.object(
            self.app, "_suggest_portfolio_downside"
        ) as suggest:
            self.app._apply_prop_website_rules(suggest=True)
        self.assertEqual(self.app.daily_limit_var.get(), "5.5")
        self.assertEqual(Decimal(self.app.prop_total_loss_room_var.get()), Decimal("2750"))
        self.assertEqual(Decimal(self.app.remaining_daily_loss_room_var.get()), Decimal("1375"))
        self.assertEqual(self.app.limit_mode_var.get(), "Percent of account")
        suggest.assert_called_once()
        validate_scenario(self.app._scenario_data())

    def test_existing_account_requires_actual_rooms_before_applying(self) -> None:
        self._open_prop_preview()
        self.app.prop_reviewed_var.set(True)
        self.app.prop_total_loss_room_var.set("")
        with patch.object(APP["messagebox"], "showerror") as error, patch.object(
            APP["messagebox"], "askyesno"
        ) as confirm:
            self.app._apply_prop_website_rules()
        error.assert_called_once()
        confirm.assert_not_called()

    def test_existing_account_rooms_are_not_replaced_with_nominal_limits(self) -> None:
        self._open_prop_preview()
        self.app.prop_reviewed_var.set(True)
        self.app.remaining_daily_loss_room_var.set("200")
        self.app.prop_total_loss_room_var.set("500")
        with patch.object(APP["messagebox"], "askyesno", return_value=True):
            self.app._apply_prop_website_rules()
        self.assertEqual(self.app.remaining_daily_loss_room_var.get(), "200")
        self.assertEqual(self.app.prop_total_loss_room_var.get(), "500")

    def test_declining_prop_rules_preserves_account(self) -> None:
        self._open_prop_preview()
        self.app.prop_reviewed_var.set(True)
        self.app.prop_new_account_var.set(True)
        before = self.app._scenario_data()
        with patch.object(APP["messagebox"], "askyesno", return_value=False):
            self.app._apply_prop_website_rules()
        self.assertEqual(self.app._scenario_data(), before)

    def test_extracted_snapshot_is_saved_and_reloaded_offline_without_applying(self) -> None:
        before = self.app._scenario_data()
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            self.app._poll_quote_result.__globals__, APP_DATA_DIRECTORY=directory
        ):
            self.app._set_fetch_busy(True)
            self.app.quote_messages.put(
                ("__prop__", "prop_website_done", PropWebsiteTests.snapshot())
            )
            self.app._poll_quote_result()
            path = Path(directory) / "prop_website.json"
            self.assertTrue(path.is_file())
            self.app.prop_website_snapshot = None
            self.app._open_prop_website_import()
            self.assertEqual(len(self.app.prop_preview_tree.get_children()), 2)
            self.assertFalse(self.app.prop_reviewed_var.get())
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app._scenario_data(), before)

    def test_website_failure_stops_indicator_without_changing_account(self) -> None:
        before = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put(("__prop__", "prop_website_done", "HTTP 403"))
        with patch.object(APP["messagebox"], "showerror") as error:
            self.app._poll_quote_result()
        error.assert_called_once()
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app._scenario_data(), before)

    def test_late_website_response_is_cancelled_after_scenario_reload(self) -> None:
        scenario = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(scenario))
        self.app.quote_messages.put(
            ("__prop__", "prop_website_done", PropWebsiteTests.snapshot())
        )
        with patch.object(self.app, "_display_prop_website_snapshot") as display:
            self.app._poll_quote_result()
        display.assert_not_called()
        self.assertIsNone(self.app.prop_website_snapshot)
        self.assertFalse(self.app.quote_busy)

    def test_spiceprop_reference_is_available_offline_without_changing_account(self) -> None:
        before = self.app._scenario_data()
        rows = [
            self.app.spiceprop_reference_tree.item(row, "values")
            for row in self.app.spiceprop_reference_tree.get_children()
        ]
        self.assertEqual(rows, [
            ("25000 EUR", "Phase 1", "5.5% / 1375.0 EUR",
             "11% / 2750 EUR", "7.5% / 1875.0 EUR"),
            ("25000 EUR", "Phase 2", "4.5% / 1125.0 EUR",
             "11% / 2750 EUR", "5% / 1250 EUR"),
            ("25000 EUR", "Funded", "4.5% / 1125.0 EUR",
             "11% / 2750 EUR", "No evaluation target"),
        ])
        reference = APP["SPICEPROP_SWEET_REFERENCE"]
        self.assertNotIn(1000, reference["account_sizes"])
        self.assertIn(25000, reference["account_sizes"])
        self.assertEqual(reference["verified_on"], "2026-10-20")
        self.assertEqual(reference["funded_idea_risk_percent"], "2")
        self.assertEqual(
            reference["source"], "https://spiceprop.com/programs/sweet"
        )
        self.assertEqual(self.app._scenario_data(), before)

    def test_prop_account_fields_are_in_a_separate_tab(self) -> None:
        self.assertEqual(
            [self.app.notebook.tab(tab, "text") for tab in self.app.notebook.tabs()],
            ["Prop firm & account", "Portfolio", "Robot settings"],
        )
        variables = {
            str(variable)
            for variable in (
                self.app.account_capital_var,
                self.app.currency_var,
                self.app.daily_limit_var,
                self.app.limit_mode_var,
                self.app.remaining_daily_loss_room_var,
                self.app.prop_total_loss_room_var,
            )
        }

        def field_variables(widget):
            found = set()
            for child in widget.winfo_children():
                if "textvariable" in child.keys():
                    found.add(str(child.cget("textvariable")))
                found.update(field_variables(child))
            return found

        self.assertTrue(
            variables.issubset(field_variables(self.app.prop_account_tab))
        )
        self.assertTrue(variables.isdisjoint(field_variables(self.app.portfolio_tab)))
        self.app.notebook.select(self.app.prop_account_tab)
        self.app._main_tab_changed()
        self.assertEqual(
            self.app.notebook.select(), str(self.app.prop_account_tab)
        )

    def test_prop_account_changes_autosave_and_restore_on_next_launch(self) -> None:
        self.app.AUTOSAVE_ENABLED = True
        self.app._install_autosave_traces()
        expected = {
            "account_capital": "25000",
            "currency": "EUR",
            "daily_limit": "750",
            "limit_mode": "Cash amount",
            "remaining_daily_loss_room": "600",
            "prop_total_loss_room": "2000",
        }
        with tempfile.TemporaryDirectory() as directory:
            self.app.autosave_path = str(Path(directory) / "portfolio.json")
            for variable, value in (
                (self.app.account_capital_var, expected["account_capital"]),
                (self.app.currency_var, expected["currency"]),
                (self.app.daily_limit_var, expected["daily_limit"]),
                (self.app.limit_mode_var, expected["limit_mode"]),
                (
                    self.app.remaining_daily_loss_room_var,
                    expected["remaining_daily_loss_room"],
                ),
                (self.app.prop_total_loss_room_var, expected["prop_total_loss_room"]),
            ):
                variable.set(value)
            self.assertTrue(self.app._autosave_dirty)
            self.app.after(850, self.app.quit)
            self.app.mainloop()
            saved = json.loads(
                Path(self.app.autosave_path).read_text(encoding="utf-8")
            )
            for field, value in expected.items():
                self.assertEqual(saved["portfolio"][field], value)

            app_class = APP["RiskCalculatorApp"]
            with patch.dict(
                app_class.__init__.__globals__, APP_DATA_DIRECTORY=directory
            ), patch.object(app_class, "AUTOSAVE_ENABLED", True):
                restored = app_class()
            try:
                portfolio = restored._scenario_data()["portfolio"]
                for field, value in expected.items():
                    self.assertEqual(portfolio[field], value)
                self.assertEqual(
                    restored.notebook.select(), str(restored.prop_account_tab)
                )
            finally:
                restored._close_app()

    def test_constructor_schedules_refresh_after_building_ui(self) -> None:
        app_class = APP["RiskCalculatorApp"]
        with patch.object(app_class, "STARTUP_REFRESH_ENABLED", True), patch.object(
            app_class, "after", return_value="startup-refresh"
        ) as schedule, patch.object(app_class, "_load_broker_api_config"):
            app = app_class()
        try:
            schedule.assert_called_once_with(200, app._refresh_startup_data)
            self.assertEqual(app._startup_refresh_after_id, "startup-refresh")
            self.assertTrue(app.fetch_progress.winfo_exists())
        finally:
            app.destroy()

    def test_busy_indicator_runs_only_while_fetching(self) -> None:
        with patch.object(self.app.fetch_progress, "start") as start, patch.object(
            self.app.fetch_progress, "stop"
        ) as stop:
            self.app._set_fetch_busy(True)
            self.assertTrue(self.app.quote_busy)
            self.assertEqual(self.app.fetch_progress.winfo_manager(), "pack")
            start.assert_called_once_with(15)
            self.app._set_fetch_busy(False)
            stop.assert_called_once()
            self.assertFalse(self.app.quote_busy)
            self.assertEqual(self.app.fetch_progress.winfo_manager(), "")

    def test_loading_indicator_animates_without_blocking_tk_event_loop(self) -> None:
        self.app._set_fetch_busy(True)
        initial = self.app.fetch_progress["value"]
        self.app.after(70, self.app.quit)
        self.app.mainloop()
        self.assertNotEqual(self.app.fetch_progress["value"], initial)
        self.assertTrue(self.app.quote_busy)
        self.app._set_fetch_busy(False)

    def _run_startup_worker(self) -> None:
        refresh = self.app._refresh_startup_data
        with patch.object(
            APP["threading"], "Thread",
            side_effect=lambda *, target, daemon: SimpleNamespace(start=target),
        ), patch.object(self.app, "after"):
            refresh()

    def test_startup_refresh_uses_yahoo_for_saved_yahoo_data(self) -> None:
        self.app.history_sources[self.row] = "Yahoo"
        result = APP["YahooDataResult"](
            self.row, (Decimal("101"), "USD", "^GSPC", "now"),
            self.app.historical_stresses[self.row], None,
        )
        with patch.object(self.app, "_request_yahoo_data", return_value=result) as fetch:
            self._run_startup_worker()
        fetch.assert_called_once()
        with patch.object(self.app, "after"), patch.object(
            self.app, "_suggest_portfolio_downside"
        ) as suggest:
            self.app._poll_quote_result()
            self.assertTrue(self.app.quote_busy)
            self.app._poll_quote_result()
        suggest.assert_not_called()
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app.quotes[self.row][0], Decimal("101"))
        self.assertIn("completed", self.app.status_var.get())

    def test_startup_refresh_uses_saved_terminal_source_without_changing_account(self) -> None:
        self.app.history_sources[self.row] = "MT5 terminal"
        data = APP["MT5SymbolData"](
            self.app.contract_inputs[self.row],
            self.app.history_bars[self.row],
            (Decimal("102"), "USD", "US500", "now"),
        )
        refresh = self.app._refresh_startup_data
        with patch.dict(
            refresh.__globals__,
            fetch_mt5_terminal_data=lambda symbols: ("USD", {"US500": data}),
        ):
            self._run_startup_worker()
        with patch.object(self.app, "after"), patch.object(
            self.app, "_suggest_portfolio_downside"
        ) as suggest:
            self.app._poll_quote_result()
            self.assertTrue(self.app.quote_busy)
            self.app._poll_quote_result()
        suggest.assert_not_called()
        self.assertEqual(self.app.quotes[self.row][0], Decimal("102"))
        self.assertEqual(self.app.currency_var.get(), "USD")
        self.assertFalse(self.app.quote_busy)

    def test_startup_terminal_refresh_preserves_manual_commission_and_pip_conversion(self) -> None:
        self.app.contract_inputs[self.row]["commission_per_lot"] = "7"
        self.app.symbol_commission_per_lot_var.set("7")
        contract = dict(self.app.contract_inputs[self.row])
        contract.update(points_per_pip="", commission_per_lot="")
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](
                contract, self.app.history_bars[self.row], self.app.quotes[self.row]
            )},
            "USD",
        )
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put((self.row, "startup_mt5_done", response))
        with patch.object(self.app, "after"):
            self.app._poll_quote_result()
        self.assertEqual(
            self.app.contract_inputs[self.row]["commission_per_lot"], "7"
        )
        self.assertEqual(self.app.contract_inputs[self.row]["points_per_pip"], "1")

    def test_startup_refresh_keeps_csv_and_reports_that_it_was_not_refreshed(self) -> None:
        before = self.app.history_bars[self.row]
        with patch.object(self.app, "_request_yahoo_data") as fetch:
            self._run_startup_worker()
        fetch.assert_not_called()
        with patch.object(APP["messagebox"], "showwarning") as warning:
            self.app._poll_quote_result()
        self.assertEqual(self.app.history_bars[self.row], before)
        self.assertIn("CSV snapshot retained", warning.call_args.args[1])
        self.assertFalse(self.app.quote_busy)

    def test_startup_api_failure_keeps_saved_data_and_stops_indicator(self) -> None:
        self.app.history_sources[self.row] = "Broker API"
        self.app.broker_api_endpoint_var.set(
            "https://broker.example/history?symbol={symbol}"
        )
        before = self.app.quotes[self.row]
        refresh = self.app._refresh_startup_data
        with patch.dict(
            refresh.__globals__,
            fetch_broker_api_data=lambda *_args: (_ for _ in ()).throw(
                ValueError("HTTP 401")
            ),
        ):
            self._run_startup_worker()
        with patch.object(APP["messagebox"], "showwarning") as warning:
            self.app._poll_quote_result()
        self.assertIn("HTTP 401", warning.call_args.args[1])
        self.assertIn("token", warning.call_args.args[1])
        self.assertEqual(self.app.quotes[self.row], before)
        self.assertFalse(self.app.quote_busy)
        self.assertEqual(self.app.fetch_progress.winfo_manager(), "")

    def test_startup_api_uses_saved_endpoint_without_saving_or_requesting_a_token(self) -> None:
        self.app.history_sources[self.row] = "Broker API"
        endpoint = "https://broker.example/history?symbol={symbol}"
        self.app.broker_api_endpoint_var.set(endpoint)
        data = APP["MT5SymbolData"](
            self.app.contract_inputs[self.row],
            self.app.history_bars[self.row],
            (Decimal("103"), "USD", "US500", "now"),
        )
        fetch = unittest.mock.Mock(return_value=("USD", {"US500": data}))
        with patch.dict(
            self.app._refresh_startup_data.__globals__, fetch_broker_api_data=fetch
        ):
            self._run_startup_worker()
        fetch.assert_called_once_with(endpoint, "", ["US500"])
        with patch.object(self.app, "after"):
            self.app._poll_quote_result()
            self.app._poll_quote_result()
        self.assertEqual(self.app.quotes[self.row][0], Decimal("103"))
        self.assertFalse(self.app.quote_busy)

    def test_startup_failure_does_not_stop_other_allocations(self) -> None:
        self.app._insert_allocation("US100", "^NDX", "DCA", "1000")
        second = list(self.app.allocations)[-1]
        self.app.history_sources[self.row] = "Yahoo"
        before = self.app.quotes[self.row]
        results = [
            APP["YahooDataResult"](self.row, None, None, "Offline"),
            APP["YahooDataResult"](
                second, (Decimal("123"), "USD", "^NDX", "now"),
                self.app.historical_stresses[self.row], None,
            ),
        ]
        with patch.object(self.app, "_request_yahoo_data", side_effect=results):
            self._run_startup_worker()
        with patch.object(self.app, "after"), patch.object(
            APP["messagebox"], "showwarning"
        ) as warning:
            for _ in range(3):
                self.app._poll_quote_result()
        self.assertEqual(self.app.quotes[self.row], before)
        self.assertEqual(self.app.quotes[second][0], Decimal("123"))
        self.assertIn("Offline", warning.call_args.args[1])
        self.assertFalse(self.app.quote_busy)

    def test_scenario_reload_drains_startup_results_before_unlocking_fetch(self) -> None:
        scenario = self.app._scenario_data()
        self.app.history_sources[self.row] = "Yahoo"
        result = APP["YahooDataResult"](
            self.row, (Decimal("999"), "USD", "^GSPC", "old"),
            self.app.historical_stresses[self.row], None,
        )
        with patch.object(self.app, "_request_yahoo_data", return_value=result):
            self._run_startup_worker()
        self.app._apply_scenario(validate_scenario(scenario))
        with patch.object(self.app, "after"), patch.object(
            APP["messagebox"], "showwarning"
        ) as warning:
            self.app._poll_quote_result()
            self.assertTrue(self.app.quote_busy)
            self.app._poll_quote_result()
        warning.assert_not_called()
        self.assertFalse(self.app.quote_busy)
        self.assertNotIn(Decimal("999"), [q[0] for q in self.app.quotes.values()])

    def test_broker_api_endpoint_config_saves_without_credentials(self) -> None:
        endpoint = (
            "https://broker.example/history?symbol={symbol}&from={start}&to={end}"
        )
        with tempfile.TemporaryDirectory() as directory:
            self.app.broker_api_config_path = str(
                Path(directory) / "broker_api_config.json"
            )
            self.app._save_broker_api_config(endpoint)
            saved = json.loads(
                Path(self.app.broker_api_config_path).read_text(encoding="utf-8")
            )
        self.assertEqual(saved, {"endpoint_template": endpoint})
        self.assertNotIn("token", json.dumps(saved).lower())

    def test_broker_api_source_survives_scenario_validation(self) -> None:
        scenario = self.app._scenario_data()
        scenario["allocations"][0]["history_source"] = "Broker API"
        validated = validate_scenario(scenario)
        self.assertEqual(validated["allocations"][0]["history_source"], "Broker API")

    def test_local_json_autosave_restores_portfolio_contract_and_five_year_history(self) -> None:
        self.app.AUTOSAVE_ENABLED = True
        with tempfile.TemporaryDirectory() as directory:
            self.app.autosave_path = str(Path(directory) / "portfolio.json")
            self.assertTrue(self.app._save_autosave_scenario())
            saved = json.loads(Path(self.app.autosave_path).read_text(encoding="utf-8"))
            self.assertEqual(saved["format"], "mt5-risk-planner-scenario")
            self.assertEqual(len(saved["allocations"][0]["history_bars"]), 20)

            self.app.account_capital_var.set("12000")
            self.app.history_bars.clear()
            self.app.quotes.clear()
            self.app._load_autosave_scenario()

        self.assertEqual(self.app.account_capital_var.get(), "10000")
        restored_row = next(iter(self.app.allocations))
        self.assertEqual(len(self.app.history_bars[restored_row]), 20)
        self.assertEqual(self.app.quotes[restored_row][0], Decimal("100"))
        self.assertEqual(
            self.app.contract_inputs[restored_row]["point_value"], "1"
        )

    def test_portfolio_downside_refreshes_yahoo_but_preserves_mt5_history(self) -> None:
        self.app.history_sources[self.row] = "Yahoo"
        with patch.object(self.app, "_fetch_all_yahoo_data") as fetch:
            self.app._suggest_portfolio_downside()
        fetch.assert_called_once_with(only_missing=True)
        self.assertTrue(self.app.portfolio_suggestion_pending)

    def test_mt5_terminal_response_updates_contract_market_data_and_starts_suggestion(self) -> None:
        bars = self.app.history_bars[self.row]
        contract = dict(self.app.contract_inputs[self.row])
        quote = (Decimal("101"), "USD", "US500.cash", "2026-10-20 09:00")
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](contract, bars, quote)},
            "USD",
        )
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put(("__mt5__", "mt5_done", response))
        with patch.object(self.app, "_suggest_portfolio_downside") as suggest:
            self.app._poll_quote_result()

        self.assertEqual(self.app.history_sources[self.row], "MT5 terminal")
        self.assertEqual(self.app.quotes[self.row], quote)
        self.assertEqual(self.app.reference_price_var.get(), "101")
        self.assertEqual(self.app.currency_var.get(), "USD")
        suggest.assert_called_once()

    def test_broker_api_response_updates_contract_history_and_starts_suggestion(self) -> None:
        bars = self.app.history_bars[self.row]
        contract = dict(self.app.contract_inputs[self.row])
        quote = (Decimal("101"), "USD", "US500.cash", "2026-10-20 09:00")
        response = APP["MT5PortfolioResult"](
            {self.row: APP["MT5SymbolData"](contract, bars, quote)},
            "USD",
        )
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put(("__broker_api__", "broker_api_done", response))
        with patch.object(self.app, "_suggest_portfolio_downside") as suggest:
            self.app._poll_quote_result()

        self.assertEqual(self.app.history_sources[self.row], "Broker API")
        self.assertEqual(self.app.quotes[self.row], quote)
        suggest.assert_called_once()

    def test_rejected_yahoo_history_preserves_existing_snapshot_and_blocks_autogeneration(self) -> None:
        chart = YahooHistoryTests()._chart()
        chart["indicators"]["quote"][0]["low"].pop()
        before_quote = self.app.quotes[self.row]
        before_history = self.app.historical_stresses[self.row]
        before_bars = self.app.history_bars[self.row]
        request = self.app._request_yahoo_data
        with patch.dict(
            request.__globals__,
            _fetch_yahoo_chart=lambda *args: chart,
            fetch_yahoo_quote=lambda ticker: (Decimal("999"), "USD", ticker, "now"),
        ):
            result = request(self.row, "^GSPC")
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put((self.row, "one", result))
        with patch.object(APP["messagebox"], "showwarning") as warning, patch.object(
            self.app, "_main_tab_changed"
        ) as generate, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ):
            self.app._poll_quote_result()
        warning.assert_called_once()
        generate.assert_not_called()
        self.assertEqual(self.app.quotes[self.row], before_quote)
        self.assertEqual(self.app.historical_stresses[self.row], before_history)
        self.assertEqual(self.app.history_bars[self.row], before_bars)
        self.assertIn("array lengths", self.app.output_text.get("1.0", "end"))

    def test_flat_history_can_be_saved_reloaded_but_not_used_for_historical_sizing(self) -> None:
        bars = tuple(
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("100"), Decimal("100"), Decimal("100"),
                spread_points=Decimal("5"), open=Decimal("100"),
            )
            for index in range(20)
        )
        self.app.history_bars[self.row] = bars
        self.app.historical_stresses[self.row] = calculate_historical_stress(bars)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flat.json"
            self.app._write_scenario(str(path))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.app._apply_scenario(validate_scenario(data))
        row = next(iter(self.app.allocations))
        self.assertEqual(self.app.history_bars[row], bars)
        self.assertEqual(self.app.historical_stresses[row].long_adverse_pct, Decimal("0"))
        with self.assertRaisesRegex(ValueError, "No valid historical"):
            self.app._generate_settings_checked(show_errors=False)

    def test_failed_validation_does_not_create_new_scenario_file(self) -> None:
        self.app.symbol_commission_per_lot_var.set("invalid")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            with patch.object(APP["messagebox"], "showerror") as error:
                self.app._write_scenario(str(path))
            error.assert_called_once()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_invalid_scenario_save_does_not_replace_existing_file(self) -> None:
        self.app.symbol_commission_per_lot_var.set("-1")
        old_path = self.app.current_scenario_path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text("existing scenario", encoding="utf-8")
            with patch.object(APP["messagebox"], "showerror") as error:
                self.app._write_scenario(str(path))
            error.assert_called_once()
            self.assertEqual(path.read_text(encoding="utf-8"), "existing scenario")
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["scenario.json"])
        self.assertEqual(self.app.current_scenario_path, old_path)
        self.assertEqual(self.app.status_var.get(), "Scenario save failed.")

    def test_valid_scenario_is_saved_and_can_be_reloaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            self.app._write_scenario(str(path))
            data = json.loads(path.read_text(encoding="utf-8"))
            validated = validate_scenario(data)
            self.app._apply_scenario(validated)
            self.assertEqual(len(self.app.allocations), 1)
            self.assertEqual(self.app.history_bars[next(iter(self.app.allocations))][0].open,
                             Decimal("99.5"))
            self.assertEqual(self.app.current_scenario_path, str(path))
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["scenario.json"])

    def test_failed_atomic_replace_preserves_file_and_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text("existing scenario", encoding="utf-8")
            with patch.object(APP["os"], "replace", side_effect=OSError("file locked")), patch.object(
                APP["messagebox"], "showerror"
            ) as error:
                self.app._write_scenario(str(path))
            error.assert_called_once()
            self.assertEqual(path.read_text(encoding="utf-8"), "existing scenario")
            self.assertEqual([item.name for item in Path(directory).iterdir()], ["scenario.json"])

    def test_partial_yahoo_refresh_preserves_complete_yahoo_snapshot(self) -> None:
        old_history = self.app.historical_stresses[self.row]
        self.app.history_bars.pop(self.row)
        self.app.history_sources[self.row] = "Yahoo"
        self.app.saved_history_rows.add(self.row)
        self.app.saved_quote_rows.add(self.row)
        before_quote = self.app.quotes[self.row]
        result = APP["YahooDataResult"](
            row_id=self.row,
            quote=(Decimal("999"), "USD", "^GSPC", "new"),
            history=None,
            error="5-year history unavailable: timeout",
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[self.row], before_quote)
        self.assertEqual(self.app.historical_stresses[self.row], old_history)
        self.assertIn(self.row, self.app.saved_quote_rows)
        self.assertIn(self.row, self.app.saved_history_rows)

    def test_partial_yahoo_refresh_keeps_quote_when_no_history_exists(self) -> None:
        self.app.history_bars.pop(self.row)
        self.app.historical_stresses.pop(self.row)
        self.app.history_sources.pop(self.row)
        quote = (Decimal("999"), "USD", "^GSPC", "new")
        result = APP["YahooDataResult"](
            row_id=self.row, quote=quote, history=None, error="history unavailable",
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[self.row], quote)
        self.assertNotIn(self.row, self.app.historical_stresses)

    def test_complete_yahoo_refresh_replaces_broker_history(self) -> None:
        history = self.app.historical_stresses[self.row]
        quote = (Decimal("999"), "USD", "^GSPC", "new")
        result = APP["YahooDataResult"](
            row_id=self.row, quote=quote, history=history, error=None,
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[self.row], quote)
        self.assertEqual(self.app.history_sources[self.row], "Yahoo")
        self.assertNotIn(self.row, self.app.history_bars)
        self.assertNotIn(self.row, self.app.saved_quote_rows)
        self.assertNotIn(self.row, self.app.saved_history_rows)

    def test_partial_refresh_does_not_regenerate_settings_from_old_history(self) -> None:
        result = APP["YahooDataResult"](
            row_id=self.row,
            quote=(Decimal("999"), "USD", "^GSPC", "new"),
            history=None, error="history unavailable",
        )
        with patch.object(self.app, "_main_tab_changed") as generate, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ):
            self.app._apply_yahoo_data_result(result)
        generate.assert_not_called()

    def test_incomplete_batch_shows_error_instead_of_regenerating(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.app.batch_errors = ["US500: 5-year history unavailable"]
        self.app.quote_messages.put(("__all__", "batch_done", None))
        with patch.object(self.app, "_main_tab_changed") as generate, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ), patch.object(APP["messagebox"], "showwarning") as warning:
            self.app._poll_quote_result()
        generate.assert_not_called()
        warning.assert_called_once()
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("no settings regenerated", report)
        self.assertNotIn("SELECTED DCA EA SETTINGS", report)

    def test_complete_batch_still_regenerates_settings(self) -> None:
        self.app.batch_errors = []
        self.app.quote_messages.put(("__all__", "batch_done", None))
        with patch.object(self.app, "_main_tab_changed") as generate, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ):
            self.app._poll_quote_result()
        generate.assert_called_once()

    def test_partial_mt5_refresh_preserves_bars_quote_and_source(self) -> None:
        before_quote = self.app.quotes[self.row]
        before_bars = self.app.history_bars[self.row]
        result = APP["YahooDataResult"](
            row_id=self.row,
            quote=(Decimal("999"), "USD", "^GSPC", "new"),
            history=None, error="history unavailable",
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[self.row], before_quote)
        self.assertEqual(self.app.history_bars[self.row], before_bars)
        self.assertEqual(self.app.history_sources[self.row], "MT5 CSV")

    def test_missing_quote_does_not_overwrite_existing_snapshot(self) -> None:
        before_quote = self.app.quotes[self.row]
        before_bars = self.app.history_bars[self.row]
        result = APP["YahooDataResult"](
            row_id=self.row, quote=None, history=None, error="price unavailable",
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[self.row], before_quote)
        self.assertEqual(self.app.history_bars[self.row], before_bars)

    def _select_row(self, row: str) -> None:
        self.app.allocation_tree.selection_set(row)
        self.app._portfolio_row_selected()

    def test_duplicate_allocations_remain_individually_selectable(self) -> None:
        self.app._insert_allocation("US500", "^GSPC", "DCA", "1000")
        rows = list(self.app.allocations)
        self.assertEqual(len(self.app.selection_ids), len(rows))
        for row in rows:
            with self.subTest(row=row):
                self._select_row(row)
                self.assertEqual(self.app._selected_row_id(), row)

    def test_duplicate_allocations_keep_separate_contracts_and_capitals(self) -> None:
        self.app.point_value_var.set("2")
        first = self.row
        self.app._insert_allocation("US500", "^GSPC", "DCA", "1000")
        second = self.app._selected_row_id()
        self.app.point_value_var.set("7")
        self._select_row(first)
        self.assertEqual(self.app.point_value_var.get(), "2")
        self._select_row(second)
        self.assertEqual(self.app.point_value_var.get(), "7")
        self.assertEqual(self.app.allocations[first].capital, Decimal("5000"))
        self.assertEqual(self.app.allocations[second].capital, Decimal("1000"))

    def test_duplicate_allocations_scenario_restores_selected_index(self) -> None:
        original = self.app._scenario_data()
        other = deepcopy(original["allocations"][0])
        other["capital"] = "1000"
        other["broker_contract"]["point_value"] = "7"
        original["allocations"].append(other)
        for index in (0, 1):
            with self.subTest(index=index):
                scenario = deepcopy(original)
                scenario["selected_allocation"] = index
                scenario["settings"]["text"]["point_value"] = "1" if index == 0 else "7"
                self.app._apply_scenario(validate_scenario(scenario))
                expected = list(self.app.allocations)[index]
                self.assertEqual(self.app._selected_row_id(), expected)
                self.assertEqual(self.app._scenario_data()["selected_allocation"], index)

    def test_removing_one_duplicate_preserves_other_selection(self) -> None:
        first = self.row
        self.app._insert_allocation("US500", "^GSPC", "DCA", "1000")
        second = self.app._selected_row_id()
        self.app.allocation_tree.selection_set(second)
        self.app._remove_selected_allocation()
        self.assertEqual(self.app._selected_row_id(), first)
        self.assertEqual(set(self.app.selection_ids.values()), {first})

    def test_duplicate_allocations_are_both_reported_with_separate_budgets(self) -> None:
        scenario = self.app._scenario_data()
        other = deepcopy(scenario["allocations"][0])
        other["capital"] = "1000"
        other["broker_contract"]["point_value"] = "7"
        scenario["allocations"].append(other)
        scenario["selected_allocation"] = 0
        self.app._apply_scenario(validate_scenario(scenario))
        rows = list(self.app.allocations)
        for index, row in enumerate(rows):
            with self.subTest(row=row):
                self._select_row(row)
                self.app._generate_settings_checked(show_errors=False)
                report = self.app._validated_generated_output()
                self.assertIn(f"\nAllocation ID: {row}\n", report)
                self.assertIn(
                    f"Allocation ID: {rows[0]}; capital 5000 USD; risk allowance (80%): 180 USD.",
                    report,
                )
                self.assertIn(
                    f"Allocation ID: {rows[1]}; capital 1000 USD; risk allowance (80%): 36 USD.",
                    report,
                )
                self.assertEqual(
                    self.app._scenario_data()["selected_allocation"], index
                )
        self.assertEqual(len(set(self.app.magic_assignments.values())), 2)

    def test_missing_data_identifies_the_correct_duplicate_allocation(self) -> None:
        self.app._insert_allocation("US500", "^GSPC", "DCA", "1000")
        second = self.app._selected_row_id()
        self._select_row(self.row)
        self.app._generate_settings_checked(show_errors=False)
        report = self.app._validated_generated_output()
        self.assertIn(
            f"Not included (missing data): US500 [{second}]: market reference price not loaded",
            report,
        )

    def test_full_portfolio_requires_overall_room_and_outputs_each_robot_settings(self) -> None:
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            self.app._generate_settings_checked(
                show_errors=False,
                require_complete_portfolio=True,
            )

        scenario = self.app._scenario_data()
        scenario["allocations"][0]["robot"] = "RSI"
        second_allocation = deepcopy(scenario["allocations"][0])
        second_allocation["robot"] = "DCA"
        second_allocation["capital"] = "1000"
        second_allocation["allocation_percent"] = ""
        scenario["allocations"].append(second_allocation)
        self.app._apply_scenario(validate_scenario(scenario))
        self.app.prop_total_loss_room_var.set("2000")
        today = datetime.now(timezone.utc).date()
        bars = tuple(
            DailyBar(
                date=(today - timedelta(days=offset)).isoformat(),
                open=Decimal("100"), high=Decimal("105"), low=Decimal("90"),
                close=Decimal("100"),
            )
            for offset in range(1825, -1, -1)
            if (today - timedelta(days=offset)).weekday() < 5
        )
        for row_id in self.app.allocations:
            self.app.history_bars[row_id] = bars
            self.app.historical_stresses[row_id] = calculate_historical_stress(bars)

        self.app._generate_settings_checked(
            show_errors=False,
            require_complete_portfolio=True,
        )
        report = self.app._validated_generated_output()
        self.assertIn("PORTFOLIO VERDICT: ACCEPTED", report)
        self.assertIn("PER-ROBOT CANDIDATE SETTINGS", report)
        allocation_ids = list(self.app.allocations)
        self.assertIn(f"US500 | RSI | {allocation_ids[0]}", report)
        self.assertIn(f"US500 | DCA | {allocation_ids[1]}", report)
        self.assertEqual(
            len(set(self.app.magic_assignments.values())),
            2,
        )

    def setUp(self) -> None:
        self.app = APP["RiskCalculatorApp"]()
        self.app.withdraw()
        scenario = ScenarioMigrationTests()._history_scenario(13)
        scenario["selected_allocation"] = 0
        contract = scenario["allocations"][0]["broker_contract"]
        contract.update(
            point_value="1", point_size="1", points_per_pip="1",
            lot_increment="0.01", minimum_lot="0.01", maximum_lot="10",
            contract_currency="USD",
        )
        scenario["settings"]["text"].update(
            contract,
            step_type="Fixed pips", step_value="5", reference_price="100",
            take_profit_type="Fixed pips", take_profit_value="5",
            stress_mode=historical_drawdown_mode,
        )
        self.app._apply_scenario(validate_scenario(scenario))
        self.row = next(iter(self.app.allocations))

    def tearDown(self) -> None:
        self.app.fetch_progress.stop()
        self.app.destroy()

    def test_manual_and_target_modes_reject_mismatched_point_value_currency(self) -> None:
        for mode in ("Adverse move (%)", "Target price"):
            with self.subTest(mode=mode):
                self.app.stress_mode_var.set(mode)
                self.app.stress_target_price_var.set("90")
                self.app.contract_currency_var.set("EUR")
                with self.assertRaisesRegex(ValueError, "account currency"):
                    self.app._generate_settings_checked(show_errors=False)

    def test_rejects_missing_account_currency(self) -> None:
        self.app.currency_var.set("")
        with self.assertRaisesRegex(ValueError, "account currency"):
            self.app._generate_settings_checked(show_errors=False)

    def test_all_modes_require_explicit_point_value_currency(self) -> None:
        for mode in ("Adverse move (%)", "Target price", historical_drawdown_mode):
            with self.subTest(mode=mode):
                self.app.stress_mode_var.set(mode)
                self.app.stress_target_price_var.set("90")
                self.app.contract_currency_var.set("")
                self.app.contract_inputs[self.row]["contract_currency"] = ""
                with self.assertRaisesRegex(ValueError, "account currency"):
                    self.app._generate_settings_checked(show_errors=False)

    def test_historical_suggestion_respects_candidate_count(self) -> None:
        self.app.step_value_var.set("0.1")
        self.app.compare_trades_var.set("2")
        for mode in (historical_drawdown_mode, historical_mode):
            with self.subTest(mode=mode):
                self.app.stress_mode_var.set(mode)
                self.app._generate_settings_checked(show_errors=False)
                self.assertLessEqual(int(self.app.selected_trades_var.get()), 2)
                report = self.app.output_text.get("1.0", "end")
                self.assertIn("SELECTED DCA EA SETTINGS", report)
                portfolio_row = next(
                    line for line in report.splitlines()
                    if line.startswith("US500") and "within allowance" in line
                )
                self.assertLessEqual(int(portfolio_row.split()[3]), 2)

    def test_manual_short_stress_can_exceed_one_hundred_percent(self) -> None:
        self.app.stress_mode_var.set("Adverse move (%)")
        self.app.position_direction_var.set("Short (price rises)")
        for percent, target in (("100", "200"), ("150", "250")):
            with self.subTest(percent=percent):
                self.app.stress_pct_var.set(percent)
                self.app._generate_settings_checked(show_errors=False)
                report = self.app.output_text.get("1.0", "end")
                self.assertIn(f"Tested adverse target: {target}", report)
                self.assertIn(f"Adverse move: {percent}%", report)

    def test_historical_short_rally_can_exceed_one_hundred_percent(self) -> None:
        self.app.position_direction_var.set("Short (price rises)")
        history = self.app.historical_stresses[self.row]
        self.app.historical_stresses[self.row] = replace(
            history,
            short_rally_pct=Decimal("150"),
            short_rally_trough_date=history.start_date,
            short_rally_peak_date=history.end_date,
        )
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        self.assertIn("Tested adverse target: 250", report)
        self.assertNotIn("Not included (missing data):", report)
        self.assertIn("historical trough-to-peak rally", report)

    def test_short_target_suggestion_handles_rallies_above_one_hundred_percent(self) -> None:
        self.app.position_direction_var.set("Short (price rises)")
        self.app.stress_pct_var.set("150")
        self.app.auto_stress_target_price = None
        self.app.stress_target_price_var.set("")
        self.app._suggest_stress_target()
        self.assertEqual(self.app.stress_target_price_var.get(), "250")

    def test_long_stress_cannot_reach_or_exceed_one_hundred_percent(self) -> None:
        self.app.stress_mode_var.set("Adverse move (%)")
        for percent in ("100", "150"):
            with self.subTest(percent=percent):
                self.app.stress_pct_var.set(percent)
                with self.assertRaisesRegex(ValueError, "less than 100"):
                    self.app._generate_settings_checked(show_errors=False)

    def test_long_target_must_be_positive(self) -> None:
        self.app.stress_mode_var.set("Target price")
        for target in ("0", "-10"):
            with self.subTest(target=target):
                self.app.stress_target_price_var.set(target)
                with self.assertRaisesRegex(ValueError, "target price must be greater than zero"):
                    self.app._generate_settings_checked(show_errors=False)

    def test_manual_portfolio_report_caps_volume_at_broker_maximum(self) -> None:
        self.app.stress_mode_var.set("Adverse move (%)")
        self.app.maximum_lot_var.set("0.035")
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        portfolio_row = next(
            line for line in report.splitlines()
            if line.startswith("US500") and "within allowance" in line
        )
        self.assertEqual(Decimal(portfolio_row.split()[4]), Decimal("0.03"))
        self.assertIn("\nRisk: 0.03\n", report)
        self.assertIn("PORTFOLIO VERDICT: ", report)

    def test_invalid_portfolio_clears_previous_settings(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.assertIn(
            "SELECTED DCA EA SETTINGS", self.app.output_text.get("1.0", "end")
        )
        self.app.account_capital_var.set("0")
        self.app._generate_settings_checked(show_errors=False)
        self.assertEqual(self.app.output_text.get("1.0", "end").strip(), "")

    def test_export_rejects_settings_after_inputs_change(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.app.step_value_var.set("10")
        with patch.object(APP["filedialog"], "asksaveasfilename", return_value="") as save, patch.object(
            APP["messagebox"], "showerror"
        ) as error:
            self.app._export_set_template()
        save.assert_not_called()
        error.assert_called_once()
        self.assertIn("Regenerate", error.call_args.args[1])

    def test_export_rejects_manually_edited_report(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.app.output_text.insert("1.0", "Risk: 999\n")
        with patch.object(APP["filedialog"], "asksaveasfilename", return_value="") as save, patch.object(
            APP["messagebox"], "showerror"
        ) as error:
            self.app._export_set_template()
        save.assert_not_called()
        error.assert_called_once()

    def test_copy_rejects_old_settings_after_contract_change(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.app.point_value_var.set("10")
        with patch.object(self.app, "clipboard_clear") as clear, patch.object(
            APP["messagebox"], "showerror"
        ) as error:
            self.app._copy_output()
        clear.assert_not_called()
        error.assert_called_once()

    def test_export_current_settings_preserves_calculated_lot(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        report = self.app.output_text.get("1.0", "end")
        lot_line = next(line for line in report.splitlines() if line.startswith("Risk: "))
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "candidate.set")
            with patch.object(APP["filedialog"], "asksaveasfilename", return_value=path), patch.object(
                APP["messagebox"], "showwarning"
            ):
                self.app._export_set_template()
            preset = Path(path).read_text(encoding="utf-8")
        self.assertIn(f"Risk={lot_line.split(': ', 1)[1]}||", preset)

    def test_changed_market_data_invalidates_generated_output(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        price, currency, symbol, timestamp = self.app.quotes[self.row]
        self.app.quotes[self.row] = (price + 1, currency, symbol, timestamp)
        with self.assertRaisesRegex(ValueError, "Regenerate"):
            self.app._validated_generated_output()

    def test_changed_history_invalidates_generated_output(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        bars = self.app.history_bars[self.row]
        self.app.history_bars[self.row] = (
            replace(bars[0], spread_points=Decimal("20")), *bars[1:],
        )
        with self.assertRaisesRegex(ValueError, "Regenerate"):
            self.app._validated_generated_output()

    def test_changed_selection_invalidates_generated_output(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        with patch.object(self.app, "_selected_row_id", return_value=None):
            with self.assertRaisesRegex(ValueError, "Regenerate"):
                self.app._validated_generated_output()

    def test_changed_allocation_invalidates_generated_output(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        allocation = self.app.allocations[self.row]
        self.app.allocations[self.row] = replace(
            allocation, capital=allocation.capital + Decimal("1")
        )
        with self.assertRaisesRegex(ValueError, "Regenerate"):
            self.app._validated_generated_output()

    def test_reloading_scenario_requires_new_generation(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        saved = self.app._scenario_data()
        self.app._apply_scenario(validate_scenario(saved))
        with self.assertRaisesRegex(ValueError, "Generate candidate settings first"):
            self.app._validated_generated_output()

    def test_late_yahoo_result_cannot_overwrite_a_reloaded_scenario(self) -> None:
        old_row = self.row
        saved = self.app._scenario_data()
        old_history = self.app.historical_stresses[old_row]
        self.app._apply_scenario(validate_scenario(saved))
        new_row = next(iter(self.app.allocations))
        before_quote = self.app.quotes[new_row]
        before_bars = self.app.history_bars[new_row]
        result = APP["YahooDataResult"](
            row_id=old_row,
            quote=(Decimal("99999"), "USD", "^NDX", "late"),
            history=old_history,
            error=None,
        )
        self.app._apply_yahoo_data_result(result, refresh_settings=False)
        self.assertEqual(self.app.quotes[new_row], before_quote)
        self.assertEqual(self.app.history_bars[new_row], before_bars)
        self.assertEqual(self.app.history_sources[new_row], "MT5 CSV")

    def test_removed_allocation_id_is_not_reused(self) -> None:
        self.app.allocation_tree.selection_set(self.row)
        self.app._remove_selected_allocation()
        self.app._insert_allocation("US100", "^NDX", "DCA", "1000")
        self.assertNotIn(self.row, self.app.allocations)

    def test_scenario_reload_cancels_pending_portfolio_suggestion(self) -> None:
        saved = self.app._scenario_data()
        self.app.portfolio_suggestion_pending = True
        self.app._apply_scenario(validate_scenario(saved))
        self.assertFalse(self.app.portfolio_suggestion_pending)

    def test_old_batch_completion_does_not_regenerate_reloaded_scenario(self) -> None:
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(saved))
        self.app.status_var.set("Loaded another scenario")
        self.app.quote_messages.put(("__all__", "batch_done", None))
        with patch.object(self.app, "_main_tab_changed") as generate, patch.object(
            self.app, "_calculate_portfolio"
        ) as calculate, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ), patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        generate.assert_not_called()
        calculate.assert_not_called()
        schedule.assert_not_called()
        self.assertEqual(self.app.status_var.get(), "Loaded another scenario")
        self.assertFalse(self.app.quote_busy)

    def test_old_batch_errors_do_not_warn_after_scenario_reload(self) -> None:
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app.batch_errors = ["Old allocation: request failed"]
        self.app._apply_scenario(validate_scenario(saved))
        self.app.quote_messages.put(("__all__", "batch_done", None))
        with patch.object(APP["messagebox"], "showwarning") as warning:
            self.app._poll_quote_result()
        warning.assert_not_called()
        self.assertFalse(self.app.quote_busy)

    def test_old_single_request_error_preserves_new_scenario_output(self) -> None:
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(saved))
        self.app._generate_settings_checked(show_errors=False)
        before_output = self.app.output_text.get("1.0", "end")
        before_status = self.app.status_var.get()
        result = APP["YahooDataResult"](
            row_id=self.row, quote=None, history=None, error="Old request failed",
        )
        self.app.quote_messages.put((self.row, "one", result))
        with patch.object(APP["messagebox"], "showwarning") as warning, patch.object(
            self.app.notebook, "select", return_value=str(self.app.settings_tab)
        ), patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        warning.assert_not_called()
        schedule.assert_not_called()
        self.assertEqual(self.app.output_text.get("1.0", "end"), before_output)
        self.assertEqual(self.app.status_var.get(), before_status)
        self.assertFalse(self.app.quote_busy)

    def test_old_batch_item_is_drained_without_changing_new_scenario(self) -> None:
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._begin_yahoo_batch(1)
        self.app._apply_scenario(validate_scenario(saved))
        self.app.status_var.set("Loaded another scenario")
        result = APP["YahooDataResult"](
            row_id=self.row, quote=None, history=None, error="Old request failed",
        )
        self.app.quote_messages.put((self.row, "batch_item", result))
        with patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        schedule.assert_called_once()
        self.assertEqual(self.app.status_var.get(), "Loaded another scenario")
        self.assertEqual(self.app.batch_completed, 0)
        self.assertEqual(self.app.batch_errors, [])
        self.assertTrue(self.app.quote_busy)
        self.app.quote_messages.put(("__all__", "batch_done", None))
        self.app._poll_quote_result()
        self.assertFalse(self.app.quote_busy)

    def test_idle_quote_poll_does_not_schedule_another_poll(self) -> None:
        with patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        schedule.assert_not_called()

    def test_single_request_completion_stops_polling(self) -> None:
        self.app._set_fetch_busy(True)
        result = APP["YahooDataResult"](
            row_id=self.row, quote=self.app.quotes[self.row],
            history=self.app.historical_stresses[self.row], error=None,
        )
        self.app.quote_messages.put((self.row, "one", result))
        with patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        schedule.assert_not_called()
        self.assertFalse(self.app.quote_busy)

    def test_active_quote_poll_keeps_waiting_for_worker(self) -> None:
        self.app._set_fetch_busy(True)
        with patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        schedule.assert_called_once_with(100, self.app._poll_quote_result)
        self.assertTrue(self.app.quote_busy)

    def test_new_request_can_update_data_after_cancelled_request_finishes(self) -> None:
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(saved))
        self.app.quote_messages.put(("__all__", "batch_done", None))
        self.app._poll_quote_result()
        row = next(iter(self.app.allocations))
        history = self.app.historical_stresses[row]
        quote = (Decimal("123"), "USD", "^GSPC", "new request")
        result = APP["YahooDataResult"](
            row_id=row, quote=quote, history=history, error=None,
        )
        self.app._set_fetch_busy(True)
        self.app.quote_messages.put((row, "one", result))
        with patch.object(self.app, "after") as schedule:
            self.app._poll_quote_result()
        schedule.assert_not_called()
        self.assertEqual(self.app.quotes[row], quote)
        self.assertEqual(self.app.history_sources[row], "Yahoo")
        self.assertFalse(self.app.quote_busy)
        self.assertIn("Updated Yahoo", self.app.status_var.get())

    def test_cancelled_success_does_not_report_update_for_new_scenario(self) -> None:
        result = APP["YahooDataResult"](
            row_id=self.row, quote=self.app.quotes[self.row],
            history=self.app.historical_stresses[self.row], error=None,
        )
        saved = self.app._scenario_data()
        self.app._set_fetch_busy(True)
        self.app._apply_scenario(validate_scenario(saved))
        before_status = self.app.status_var.get()
        self.app.quote_messages.put((self.row, "one", result))
        with patch.object(self.app, "_apply_yahoo_data_result") as apply_result:
            self.app._poll_quote_result()
        apply_result.assert_not_called()
        self.assertEqual(self.app.status_var.get(), before_status)
        self.assertFalse(self.app.quote_busy)

    def test_conflicting_contract_import_preserves_existing_contract(self) -> None:
        before = dict(self.app.contract_inputs[self.row])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.csv"
            path.write_text(
                "symbol,point_size,point_value_per_point_per_lot,cash_per_point_per_lot,"
                "lot_step,min_lot,account_currency\nUS500,1,1,10,0.01,0.01,USD\n",
                encoding="utf-8",
            )
            with patch.object(APP["filedialog"], "askopenfilename", return_value=str(path)), patch.object(
                APP["messagebox"], "showerror"
            ) as error:
                self.app._import_broker_specs()
            error.assert_called_once()
        self.assertEqual(self.app.contract_inputs[self.row], before)

    def test_profit_currency_only_import_cannot_generate_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.csv"
            path.write_text(
                "symbol,point_size,point_value_per_point_per_lot,lot_step,min_lot,profit_currency\n"
                "US500,1,1,0.01,0.01,USD\n",
                encoding="utf-8",
            )
            with patch.object(APP["filedialog"], "askopenfilename", return_value=str(path)):
                self.app._import_broker_specs()
        self.assertEqual(self.app.contract_currency_var.get(), "")
        with self.assertRaisesRegex(ValueError, "account currency"):
            self.app._generate_settings_checked(show_errors=False)

    def test_regeneration_replaces_snapshot_with_new_inputs(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        self.app.step_value_var.set("10")
        self.app._generate_settings_checked(show_errors=False)
        report = self.app._validated_generated_output()
        self.assertIn("\nStep Value: 10\n", report)

    def test_copy_current_settings_uses_calculated_report(self) -> None:
        self.app._generate_settings_checked(show_errors=False)
        expected = self.app.output_text.get("1.0", "end").strip()
        with patch.object(self.app, "clipboard_clear"), patch.object(
            self.app, "clipboard_append"
        ) as append:
            self.app._copy_output()
        append.assert_called_once_with(expected)

    def test_export_without_generated_snapshot_is_blocked(self) -> None:
        self.app.output_text.insert("1.0", "SELECTED DCA EA SETTINGS\nRisk: 99")
        with patch.object(APP["filedialog"], "asksaveasfilename", return_value="") as save, patch.object(
            APP["messagebox"], "showerror"
        ) as error:
            self.app._export_set_template()
        save.assert_not_called()
        error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
