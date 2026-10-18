import csv
from datetime import date, timedelta
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace

from risk_calculator import DailyBar, calculate_historical_stress

APP = runpy.run_path(str(Path(__file__).with_name("risk_calculator_app.pyw")))
build_mt5_set_template = APP["build_mt5_set_template"]
parse_mt5_history_csv = APP["parse_mt5_history_csv"]
validate_scenario = APP["RiskCalculatorApp"]._validate_scenario
read_broker_contract_csv = APP["RiskCalculatorApp"]._read_broker_contract_csv
transaction_costs = APP["RiskCalculatorApp"]._transaction_costs
historical_mode = APP["HISTORICAL_STRESS_MODE"]
historical_drawdown_mode = APP["HISTORICAL_DRAWDOWN_MODE"]
historical_stress_move = APP["historical_stress_move"]
legacy_historical_mode = APP["LEGACY_HISTORICAL_STRESS_MODE"]


class MT5HistoryCsvTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
