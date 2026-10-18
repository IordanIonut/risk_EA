"""Desktop MT5 risk planner with Yahoo Finance quotes and daily history."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import os
import queue
import re
import tempfile
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from risk_calculator import (
    Allocation,
    AllocationResult,
    DailyBar,
    HistoricalStress,
    ONE,
    ONE_HUNDRED,
    ZERO,
    calculate_historical_stress,
    calculate_grid_stress,
    calculate_portfolio,
    effective_portfolio_risk_cap,
    suggest_safe_grid_settings,
)


YAHOO_ALIASES = {
    "AUS200": "^AXJO",
    "AU200": "^AXJO",
    "ASX200": "^AXJO",
    "AEX": "^AEX",
    "BEL20": "^BFX",
    "CAC40": "^FCHI",
    "CHINA300": "000300.SS",
    "CH20": "^SSMI",
    "ESP35": "^IBEX",
    "EU50": "^STOXX50E",
    "EUSTX50": "^STOXX50E",
    "FRA40": "^FCHI",
    "FR40": "^FCHI",
    "FTSE100": "^FTSE",
    "GER30": "^GDAXI",
    "GER40": "^GDAXI",
    "HK50": "^HSI",
    "HSI": "^HSI",
    "IBEX35": "^IBEX",
    "IT40": "FTSEMIB.MI",
    "JPN225": "^N225",
    "JP225": "^N225",
    "KOSPI200": "^KS200",
    "NETHER25": "^AEX",
    "NIFTY50": "^NSEI",
    "NSEI": "^NSEI",
    "OMX30": "^OMX",
    "SA40": "^J203.JO",
    "JSE40": "^J203.JO",
    "TOP40": "^J203.JO",
    "SMI20": "^SSMI",
    "SPAIN35": "^IBEX",
    "SWI20": "^SSMI",
    "SWISS20": "^SSMI",
    "TAIEX": "^TWII",
    "TAIWAN": "^TWII",
    "UK100": "^FTSE",
    "UKX": "^FTSE",
    "US100": "^NDX",
    "US30": "^DJI",
    "US500": "^GSPC",
    "US2000": "^RUT",
    "USA30": "^DJI",
    "USA500": "^GSPC",
    "USTEC": "^NDX",
    "WALLST": "^DJI",
    "WS30": "^DJI",
    "XETRA40": "^GDAXI",
    "DAX": "^GDAXI",
    "DE30": "^GDAXI",
    "DE40": "^GDAXI",
    "DJ30": "^DJI",
    "DOW": "^DJI",
    "FTSE": "^FTSE",
    "GERMAN40": "^GDAXI",
    "NAS100": "^NDX",
    "NASDAQ100": "^NDX",
    "NASDAQ": "^IXIC",
    "SPX500": "^GSPC",
    "SP500": "^GSPC",
    "S&P500": "^GSPC",
    "USATECH": "^NDX",
    "VIX": "^VIX",
    "JAPAN225": "^N225",
    "NIKKEI225": "^N225",
    "NIKKEI": "^N225",
    "FTSEMIB": "FTSEMIB.MI",
    "IBEX": "^IBEX",
    "FRANCE40": "^FCHI",
    "EURO50": "^STOXX50E",
    "EUROSTOXX50": "^STOXX50E",
    "HANGSENG": "^HSI",
    "ASX": "^AXJO",
    "NIFTY": "^NSEI",
    "SENSEX": "^BSESN",
    "BSE30": "^BSESN",
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "SHANGHAI": "000001.SS",
    "SSE": "000001.SS",
    "SZSE": "399001.SZ",
    "CSI300": "000300.SS",
    "RUSSELL2000": "^RUT",
    "NASDAQCOMPOSITE": "^IXIC",
    "SPX": "^GSPC",
    "DOWJONES": "^DJI",
    "DJI": "^DJI",
    "NDX": "^NDX",
    "GDAXI": "^GDAXI",
    "N225": "^N225",
    "AXJO": "^AXJO",
    "STOXX50": "^STOXX50E",
    "STOXX50E": "^STOXX50E",
    "AUS200CASH": "^AXJO",
    "EU50CASH": "^STOXX50E",
    "FRA40CASH": "^FCHI",
    "GER40CASH": "^GDAXI",
    "JP225CASH": "^N225",
    "NAS100CASH": "^NDX",
    "UK100CASH": "^FTSE",
    "US100CASH": "^NDX",
    "US30CASH": "^DJI",
    "US500CASH": "^GSPC",
    "US2000CASH": "^RUT",
    "US500M": "^GSPC",
    "SPX500M": "^GSPC",
    "USTECM": "^NDX",
    "NAS100M": "^NDX",
    "US30M": "^DJI",
    "GER40M": "^GDAXI",
    "UK100M": "^FTSE",
    "JP225M": "^N225",
    "AUS200M": "^AXJO",
    "HK50M": "^HSI",
    "EU50M": "^STOXX50E",
    "FRA40M": "^FCHI",
    "ESP35M": "^IBEX",
    "CH20M": "^SSMI",
    "DAX40": "^GDAXI",
    "EUROPE50": "^STOXX50E",
    "US500INDEX": "^GSPC",
    "US100INDEX": "^NDX",
    "US30INDEX": "^DJI",
    "GER40INDEX": "^GDAXI",
    "UK100INDEX": "^FTSE",
    "JP225INDEX": "^N225",
}

QuoteData = tuple[Decimal, str, str, str]
ContractFields = dict[str, str]
HISTORICAL_STRESS_MODE = "Yahoo 5-year max daily range"


@dataclass(frozen=True)
class YahooDataResult:
    row_id: str
    quote: QuoteData | None
    history: HistoricalStress | None
    error: str | None


def decimal_value(value: str, label: str) -> Decimal:
    try:
        result = Decimal(value.strip().replace(",", "."))
    except InvalidOperation as error:
        raise ValueError(f"{label}: enter a valid number.") from error
    if not result.is_finite():
        raise ValueError(f"{label}: enter a finite number.")
    return result


def positive_integer(value: str, label: str) -> int:
    try:
        result = int(value.strip())
    except ValueError as error:
        raise ValueError(f"{label}: enter a whole number.") from error
    if result <= 0:
        raise ValueError(f"{label}: enter a number greater than zero.")
    return result


def format_decimal(value: Decimal, places: int | None = None) -> str:
    text = f"{value:.{places}f}" if places is not None else format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def yahoo_symbol_for(symbol: str, ticker: str) -> str:
    clean_ticker = ticker.strip()
    if clean_ticker:
        return clean_ticker
    clean_symbol = symbol.strip()
    upper_symbol = clean_symbol.upper()
    exact = YAHOO_ALIASES.get(upper_symbol)
    if exact:
        return exact
    normalized_symbol = re.sub(r"[^A-Z0-9&]", "", upper_symbol)
    normalized_match = YAHOO_ALIASES.get(normalized_symbol)
    if normalized_match:
        return normalized_match
    for suffix in ("MICRO", "MINI", "CASH", "INDEX", "PRO", "M", "I", "C"):
        if normalized_symbol.endswith(suffix):
            base_match = YAHOO_ALIASES.get(normalized_symbol[: -len(suffix)])
            if base_match:
                return base_match
    return clean_symbol


def _fetch_yahoo_chart(
    symbol: str,
    period: str,
    interval: str,
) -> dict[str, object]:
    yahoo_symbol = quote(symbol, safe="")
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{yahoo_symbol}?range={period}&interval={interval}"
    )
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 MT5RiskPlanner/1.0"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ValueError(f"Yahoo Finance returned HTTP {error.code}.") from error
    except URLError as error:
        raise ValueError(f"Could not connect to Yahoo Finance: {error.reason}") from error
    except TimeoutError as error:
        raise ValueError("Yahoo Finance request timed out.") from error
    except json.JSONDecodeError as error:
        raise ValueError("Yahoo Finance returned an unreadable response.") from error

    if not isinstance(payload, dict):
        raise ValueError("Yahoo Finance returned an invalid response.")
    chart = payload.get("chart", {})
    if not isinstance(chart, dict):
        raise ValueError("Yahoo Finance returned an invalid chart response.")
    chart_error = chart.get("error")
    if chart_error:
        message = (
            chart_error.get("description") or "symbol not found"
            if isinstance(chart_error, dict)
            else "symbol not found"
        )
        raise ValueError(f"Yahoo Finance: {message}")
    results = chart.get("result") or []
    if not isinstance(results, list) or not results:
        raise ValueError(f"No Yahoo Finance quote was found for {symbol}.")
    if not isinstance(results[0], dict):
        raise ValueError("Yahoo Finance returned an invalid chart result.")
    return results[0]


def fetch_yahoo_quote(symbol: str) -> tuple[Decimal, str, str, str]:
    chart_result = _fetch_yahoo_chart(symbol, "1d", "1m")

    metadata = chart_result.get("meta", {})
    if not isinstance(metadata, dict):
        metadata = {}
    price = metadata.get("regularMarketPrice")
    if price is None:
        indicators = chart_result.get("indicators", {})
        quote_data = indicators.get("quote", []) if isinstance(indicators, dict) else []
        closes = (
            quote_data[0].get("close", [])
            if quote_data and isinstance(quote_data[0], dict)
            else []
        )
        price = next((item for item in reversed(closes) if item is not None), None)
    if price is None:
        raise ValueError(f"Yahoo Finance did not return a current price for {symbol}.")
    try:
        price_value = Decimal(str(price))
    except InvalidOperation as error:
        raise ValueError(f"Yahoo Finance returned an invalid price for {symbol}.") from error
    if not price_value.is_finite() or price_value <= ZERO:
        raise ValueError(f"Yahoo Finance returned an invalid price for {symbol}.")

    timestamp = metadata.get("regularMarketTime")
    time_text = (
        datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M")
        if timestamp
        else "time unavailable"
    )
    return (
        price_value,
        str(metadata.get("currency") or "currency unavailable"),
        str(metadata.get("symbol") or symbol),
        time_text,
    )


def fetch_yahoo_historical_stress(symbol: str) -> HistoricalStress:
    chart_result = _fetch_yahoo_chart(symbol, "5y", "1d")
    timestamps = chart_result.get("timestamp", [])
    indicators = chart_result.get("indicators", {})
    quote_data = indicators.get("quote", []) if isinstance(indicators, dict) else []
    if (
        not isinstance(timestamps, list)
        or not timestamps
        or not isinstance(quote_data, list)
        or not quote_data
        or not isinstance(quote_data[0], dict)
    ):
        raise ValueError(f"Yahoo Finance returned no daily history for {symbol}.")

    bars_data = quote_data[0]
    highs = bars_data.get("high", [])
    lows = bars_data.get("low", [])
    closes = bars_data.get("close", [])
    if not all(isinstance(values, list) for values in (highs, lows, closes)):
        raise ValueError(f"Yahoo Finance returned malformed daily history for {symbol}.")
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        if index >= len(highs) or index >= len(lows) or index >= len(closes):
            continue
        if highs[index] is None or lows[index] is None or closes[index] is None:
            continue
        try:
            date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
            bars.append(
                DailyBar(
                    date=date,
                    high=Decimal(str(highs[index])),
                    low=Decimal(str(lows[index])),
                    close=Decimal(str(closes[index])),
                )
            )
        except (InvalidOperation, OverflowError, OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"Yahoo Finance returned invalid daily prices for {symbol}."
            ) from error
    return calculate_historical_stress(bars)


class RiskCalculatorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MT5 Portfolio Risk Planner")
        self.geometry("1180x850")
        self.minsize(980, 700)

        self.allocations: dict[str, Allocation] = {}
        self.allocation_results: dict[str, AllocationResult] = {}
        self.contract_inputs: dict[str, ContractFields] = {}
        self.quotes: dict[str, QuoteData] = {}
        self.historical_stresses: dict[str, HistoricalStress] = {}
        self.magic_assignments: dict[str, int] = {}
        self.quote_messages: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self.quote_busy = False
        self.fetch_all_button: ttk.Button | None = None
        self.batch_total = 0
        self.batch_completed = 0
        self.batch_errors: list[str] = []
        self.portfolio_suggestion_pending = False
        self.selection_ids: dict[str, str] = {}
        self.current_settings_row: str | None = None
        self.current_scenario_path: str | None = None
        self.saved_quote_rows: set[str] = set()
        self.saved_history_rows: set[str] = set()
        self.auto_stress_target_price: str | None = None

        self._build_ui()
        self._add_default_allocation()
        self._refresh_allocation_choices()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Section.TLabelframe.Label", font=("Segoe UI", 10, "bold"))

        header = ttk.Frame(self, padding=(16, 12, 16, 2))
        header.pack(fill="x")
        ttk.Label(
            header,
            text="MT5 Portfolio Risk Planner",
            style="Title.TLabel",
        ).pack(side="left")
        ttk.Label(
            header,
            text="Risk estimates using MT5 contracts and Yahoo 5-year history",
        ).pack(side="right", anchor="e")
        scenario_buttons = ttk.Frame(header)
        scenario_buttons.pack(side="right", padx=(0, 16))
        ttk.Button(
            scenario_buttons, text="Load scenario", command=self._load_scenario_dialog
        ).pack(side="left", padx=3)
        ttk.Button(
            scenario_buttons, text="Save scenario", command=self._save_scenario
        ).pack(side="left", padx=3)
        ttk.Button(
            scenario_buttons, text="Save as...", command=self._save_scenario_as
        ).pack(side="left", padx=3)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=10)
        self.portfolio_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.portfolio_tab, text="Portfolio")
        self.notebook.add(self.settings_tab, text="Robot settings")
        self._build_portfolio_tab()
        self._build_settings_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._main_tab_changed)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 5)).pack(
            fill="x", side="bottom"
        )

    def _scenario_string_settings(self) -> dict[str, tk.StringVar]:
        return {
            "magic_number": self.magic_var,
            "step_type": self.step_type_var,
            "step_value": self.step_value_var,
            "point_value": self.point_value_var,
            "point_size": self.point_size_var,
            "points_per_pip": self.points_per_pip_var,
            "contract_currency": self.contract_currency_var,
            "stress_percent": self.stress_pct_var,
            "stress_mode": self.stress_mode_var,
            "stress_target_price": self.stress_target_price_var,
            "position_direction": self.position_direction_var,
            "lot_increment": self.lot_step_var,
            "minimum_lot": self.minimum_lot_var,
            "compare_trades": self.compare_trades_var,
            "selected_trades": self.selected_trades_var,
            "take_profit_type": self.take_profit_type_var,
            "take_profit_value": self.take_profit_value_var,
            "price_break_type": self.price_break_type_var,
            "reference_price": self.reference_price_var,
            "rsi_oversold": self.rsi_oversold_var,
            "rsi_overbought": self.rsi_overbought_var,
            "rsi_period": self.rsi_period_var,
        }

    def _contract_input_variables(self) -> dict[str, tk.StringVar]:
        return {
            "point_value": self.point_value_var,
            "point_size": self.point_size_var,
            "points_per_pip": self.points_per_pip_var,
            "lot_increment": self.lot_step_var,
            "minimum_lot": self.minimum_lot_var,
            "contract_currency": self.contract_currency_var,
        }

    def _scenario_boolean_settings(self) -> dict[str, tk.BooleanVar]:
        return {
            "entry_on_price_break": self.entry_break_var,
            "trade_on_new_candle": self.trade_new_candle_var,
            "show_dca_invested_money": self.show_dca_invested_var,
            "close_when_overbought": self.close_overbought_var,
            "show_rsi_invested_money": self.show_rsi_invested_var,
        }

    @staticmethod
    def _historical_stress_data(
        stress: HistoricalStress | None,
    ) -> dict[str, object] | None:
        if stress is None:
            return None
        return {
            "long_adverse_pct": str(stress.long_adverse_pct),
            "long_observed_date": stress.long_observed_date,
            "short_adverse_pct": str(stress.short_adverse_pct),
            "short_observed_date": stress.short_observed_date,
            "bar_count": stress.bar_count,
            "start_date": stress.start_date,
            "end_date": stress.end_date,
        }

    def _scenario_data(self) -> dict[str, object]:
        allocation_rows = []
        row_ids = list(self.allocations)
        selected_id = self._selected_row_id()
        for row_id, allocation in self.allocations.items():
            values = self.allocation_tree.item(row_id, "values")
            quote_data = self.quotes.get(row_id)
            saved_quote = None
            if quote_data:
                price, currency, yahoo_symbol, timestamp = quote_data
                saved_quote = {
                    "price": str(price),
                    "currency": currency,
                    "symbol": yahoo_symbol,
                    "timestamp": timestamp,
                }
            allocation_rows.append(
                {
                    "symbol": allocation.index,
                    "yahoo_ticker": str(values[1]),
                    "robot": allocation.robot,
                    "capital": str(allocation.capital),
                    "magic_number": self.magic_assignments.get(row_id),
                    "broker_contract": (
                        {
                            key: variable.get().strip()
                            for key, variable in self._contract_input_variables().items()
                        }
                        if row_id == selected_id
                        else dict(self.contract_inputs.get(row_id, {}))
                    ),
                    "quote": saved_quote,
                    "historical_stress": self._historical_stress_data(
                        self.historical_stresses.get(row_id)
                    ),
                }
            )

        selected_index = row_ids.index(selected_id) if selected_id in row_ids else None
        return {
            "format": "mt5-risk-planner-scenario",
            "version": 6,
            "portfolio": {
                "account_capital": self.account_capital_var.get(),
                "currency": self.currency_var.get(),
                "daily_limit": self.daily_limit_var.get(),
                "remaining_daily_loss_room": (
                    self.remaining_daily_loss_room_var.get()
                ),
                "limit_mode": self.limit_mode_var.get(),
                "prop_total_loss_room": self.prop_total_loss_room_var.get(),
            },
            "new_allocation": {
                "symbol": self.index_var.get(),
                "yahoo_ticker": self.yahoo_ticker_var.get(),
                "robot": self.robot_var.get(),
                "capital": self.capital_var.get(),
            },
            "allocations": allocation_rows,
            "settings": {
                "text": {
                    name: variable.get()
                    for name, variable in self._scenario_string_settings().items()
                },
                "options": {
                    name: variable.get()
                    for name, variable in self._scenario_boolean_settings().items()
                },
            },
            "selected_allocation": selected_index,
        }

    @staticmethod
    def _validate_scenario(data: object) -> dict[str, object]:
        if not isinstance(data, dict):
            raise ValueError("Scenario root must be a JSON object.")
        version = data.get("version")
        if (
            data.get("format") != "mt5-risk-planner-scenario"
            or isinstance(version, bool)
            or not isinstance(version, int)
            or version not in (1, 2, 3, 4, 5, 6)
        ):
            raise ValueError("Unsupported or unrecognized scenario file format.")

        def required_mapping(parent: dict[str, object], key: str) -> dict[str, object]:
            value = parent.get(key)
            if not isinstance(value, dict):
                raise ValueError(f"Scenario section '{key}' must be an object.")
            return value

        def required_text(parent: dict[str, object], key: str) -> str:
            value = parent.get(key)
            if not isinstance(value, str):
                raise ValueError(f"Scenario field '{key}' must be text.")
            return value

        portfolio = required_mapping(data, "portfolio")
        for field in (
            "account_capital",
            "currency",
            "daily_limit",
            "limit_mode",
        ):
            required_text(portfolio, field)
        prop_loss_room_text = (
            ""
            if version < 5
            else required_text(portfolio, "prop_total_loss_room")
        )
        remaining_daily_room_text = (
            ""
            if version < 6
            else required_text(portfolio, "remaining_daily_loss_room")
        )
        portfolio["prop_total_loss_room"] = prop_loss_room_text
        portfolio["remaining_daily_loss_room"] = remaining_daily_room_text
        if portfolio["limit_mode"] not in ("Percent of account", "Cash amount"):
            raise ValueError("Scenario has an invalid daily limit mode.")
        account_capital = decimal_value(
            portfolio["account_capital"], "Scenario account capital"
        )
        prop_loss_room = prop_loss_room_text.strip()
        if prop_loss_room:
            parsed_room = decimal_value(
                prop_loss_room, "Scenario prop total-loss room"
            )
            if not ZERO < parsed_room <= account_capital:
                raise ValueError(
                    "Scenario prop total-loss room must be positive and no greater "
                    "than account capital."
                )
        remaining_daily_room = remaining_daily_room_text.strip()
        if remaining_daily_room:
            parsed_daily_room = decimal_value(
                remaining_daily_room, "Scenario remaining daily-loss room"
            )
            if not ZERO < parsed_daily_room <= account_capital:
                raise ValueError(
                    "Scenario remaining daily-loss room must be positive and no "
                    "greater than account capital."
                )

        new_allocation = required_mapping(data, "new_allocation")
        for field in ("symbol", "yahoo_ticker", "robot", "capital"):
            required_text(new_allocation, field)
        if new_allocation["robot"].upper() not in ("DCA", "RSI"):
            raise ValueError("New allocation robot must be DCA or RSI.")

        raw_allocations = data.get("allocations")
        if not isinstance(raw_allocations, list) or not raw_allocations:
            raise ValueError("Scenario must contain at least one allocation.")
        normalized_allocations: list[dict[str, object]] = []
        magic_numbers: set[int] = set()
        for position, raw in enumerate(raw_allocations, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"Allocation {position} must be an object.")
            symbol = required_text(raw, "symbol").strip()
            ticker = required_text(raw, "yahoo_ticker").strip()
            robot = required_text(raw, "robot").strip().upper()
            capital_text = required_text(raw, "capital")
            if not symbol or robot not in ("DCA", "RSI"):
                raise ValueError(f"Allocation {position} has an invalid symbol or robot.")
            if decimal_value(capital_text, f"Allocation {position} capital") <= ZERO:
                raise ValueError(f"Allocation {position} capital must be greater than zero.")

            raw_magic = raw.get("magic_number")
            if raw_magic is not None:
                if (
                    isinstance(raw_magic, bool)
                    or not isinstance(raw_magic, int)
                    or not 0 < raw_magic <= 2147483647
                ):
                    raise ValueError(f"Allocation {position} has an invalid Magic Number.")
                if raw_magic in magic_numbers:
                    raise ValueError("Scenario contains duplicate Magic Numbers.")
                magic_numbers.add(raw_magic)

            raw_quote = raw.get("quote")
            normalized_quote = None
            if raw_quote is not None:
                if not isinstance(raw_quote, dict):
                    raise ValueError(f"Allocation {position} quote must be an object.")
                price_text = required_text(raw_quote, "price")
                price = decimal_value(price_text, f"Allocation {position} quote price")
                if price <= ZERO:
                    raise ValueError(f"Allocation {position} quote price must be positive.")
                normalized_quote = {
                    "price": str(price),
                    "currency": required_text(raw_quote, "currency"),
                    "symbol": required_text(raw_quote, "symbol"),
                    "timestamp": required_text(raw_quote, "timestamp"),
                }
            raw_contract = raw.get("broker_contract", {})
            if not isinstance(raw_contract, dict):
                raise ValueError(f"Allocation {position} broker_contract must be an object.")
            contract_fields = (
                "point_value",
                "point_size",
                "points_per_pip",
                "lot_increment",
                "minimum_lot",
                "contract_currency",
            )
            if version >= 3 and "broker_contract" not in raw:
                raise ValueError(f"Allocation {position} is missing broker contract data.")
            normalized_contract = {
                field: (
                    required_text(raw_contract, field)
                    if version >= 3
                    else str(raw_contract.get(field, ""))
                )
                for field in contract_fields
            }
            for field in (
                "point_value",
                "point_size",
                "points_per_pip",
                "lot_increment",
                "minimum_lot",
            ):
                value = normalized_contract[field].strip()
                if value and decimal_value(
                    value, f"Allocation {position} broker {field}"
                ) <= ZERO:
                    raise ValueError(
                        f"Allocation {position} broker {field} must be positive."
                    )
            historical_stress = None
            if version >= 4:
                if "historical_stress" not in raw:
                    raise ValueError(
                        f"Allocation {position} is missing historical stress data."
                    )
                raw_stress = raw["historical_stress"]
                if raw_stress is not None:
                    if not isinstance(raw_stress, dict):
                        raise ValueError(
                            f"Allocation {position} historical_stress must be an object or null."
                        )
                    long_pct = required_text(raw_stress, "long_adverse_pct")
                    short_pct = required_text(raw_stress, "short_adverse_pct")
                    if (
                        decimal_value(
                            long_pct, f"Allocation {position} long historical stress"
                        )
                        <= ZERO
                        or decimal_value(
                            short_pct, f"Allocation {position} short historical stress"
                        )
                        <= ZERO
                    ):
                        raise ValueError(
                            f"Allocation {position} historical stress percentages must be positive."
                        )
                    raw_count = raw_stress.get("bar_count")
                    if (
                        isinstance(raw_count, bool)
                        or not isinstance(raw_count, int)
                        or raw_count < 20
                    ):
                        raise ValueError(
                            f"Allocation {position} historical stress needs at least 20 daily bars."
                        )
                    stress_dates = {
                        field: required_text(raw_stress, field)
                        for field in (
                            "long_observed_date",
                            "short_observed_date",
                            "start_date",
                            "end_date",
                        )
                    }
                    try:
                        parsed_dates = {
                            field: datetime.strptime(value, "%Y-%m-%d").date()
                            for field, value in stress_dates.items()
                        }
                    except ValueError as error:
                        raise ValueError(
                            f"Allocation {position} has an invalid historical date."
                        ) from error
                    if (
                        parsed_dates["start_date"] > parsed_dates["end_date"]
                        or not parsed_dates["start_date"]
                        <= parsed_dates["long_observed_date"]
                        <= parsed_dates["end_date"]
                        or not parsed_dates["start_date"]
                        <= parsed_dates["short_observed_date"]
                        <= parsed_dates["end_date"]
                    ):
                        raise ValueError(
                            f"Allocation {position} historical dates are inconsistent."
                        )
                    historical_stress = {
                        "long_adverse_pct": str(
                            decimal_value(
                                long_pct,
                                f"Allocation {position} long historical stress",
                            )
                        ),
                        "long_observed_date": stress_dates["long_observed_date"],
                        "short_adverse_pct": str(
                            decimal_value(
                                short_pct,
                                f"Allocation {position} short historical stress",
                            )
                        ),
                        "short_observed_date": stress_dates["short_observed_date"],
                        "bar_count": raw_count,
                        "start_date": stress_dates["start_date"],
                        "end_date": stress_dates["end_date"],
                    }
            normalized_allocations.append(
                {
                    "symbol": symbol,
                    "yahoo_ticker": ticker or yahoo_symbol_for(symbol, ""),
                    "robot": robot,
                    "capital": capital_text,
                    "magic_number": raw_magic,
                    "broker_contract": normalized_contract,
                    "quote": normalized_quote,
                    "historical_stress": historical_stress,
                }
            )

        settings = required_mapping(data, "settings")
        text_settings = dict(required_mapping(settings, "text"))
        option_settings = required_mapping(settings, "options")
        if version == 1:
            text_settings.setdefault("stress_mode", "Adverse move (%)")
            text_settings.setdefault("stress_target_price", "")
            text_settings.setdefault("position_direction", "Long (price falls)")
        if version < 3:
            text_settings.setdefault("contract_currency", "")
        string_keys = (
            "magic_number",
            "step_type",
            "step_value",
            "point_value",
            "point_size",
            "points_per_pip",
            "contract_currency",
            "stress_percent",
            "stress_mode",
            "stress_target_price",
            "position_direction",
            "lot_increment",
            "minimum_lot",
            "compare_trades",
            "selected_trades",
            "take_profit_type",
            "take_profit_value",
            "price_break_type",
            "reference_price",
            "rsi_oversold",
            "rsi_overbought",
            "rsi_period",
        )
        bool_keys = (
            "entry_on_price_break",
            "trade_on_new_candle",
            "show_dca_invested_money",
            "close_when_overbought",
            "show_rsi_invested_money",
        )
        clean_text = {
            key: required_text(text_settings, key) for key in string_keys
        }
        clean_options = {}
        for key in bool_keys:
            value = option_settings.get(key)
            if not isinstance(value, bool):
                raise ValueError(f"Scenario option '{key}' must be true or false.")
            clean_options[key] = value
        if clean_text["step_type"] not in ("Percentage", "Fixed pips"):
            raise ValueError("Scenario has an invalid Step Type.")
        if clean_text["take_profit_type"] not in ("Percentage", "Fixed pips"):
            raise ValueError("Scenario has an invalid Take Profit Type.")
        if clean_text["price_break_type"] not in ("break Below", "break Above"):
            raise ValueError("Scenario has an invalid price-break type.")
        if clean_text["stress_mode"] not in (
            "Target price",
            "Adverse move (%)",
            HISTORICAL_STRESS_MODE,
        ):
            raise ValueError("Scenario has an invalid stress-test mode.")
        if clean_text["position_direction"] not in (
            "Long (price falls)",
            "Short (price rises)",
        ):
            raise ValueError("Scenario has an invalid position direction.")

        selected_index = data.get("selected_allocation")
        if selected_index is not None and (
            isinstance(selected_index, bool)
            or not isinstance(selected_index, int)
            or not 0 <= selected_index < len(normalized_allocations)
        ):
            raise ValueError("Scenario selected allocation index is invalid.")

        return {
            "portfolio": portfolio,
            "new_allocation": new_allocation,
            "allocations": normalized_allocations,
            "settings": {"text": clean_text, "options": clean_options},
            "selected_allocation": selected_index,
        }

    def _save_scenario(self) -> None:
        if not self.current_scenario_path:
            self._save_scenario_as()
            return
        self._write_scenario(self.current_scenario_path)

    def _save_scenario_as(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save risk scenario",
            defaultextension=".json",
            filetypes=(("MT5 risk scenario", "*.json"), ("All files", "*.*")),
            initialfile="mt5_risk_scenario.json",
        )
        if path:
            self._write_scenario(path)

    def _write_scenario(self, path: str) -> None:
        temporary_path = ""
        try:
            directory = os.path.dirname(os.path.abspath(path))
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".mt5-scenario-",
                suffix=".tmp",
                dir=directory,
                text=True,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as scenario_file:
                json.dump(
                    self._scenario_data(),
                    scenario_file,
                    ensure_ascii=False,
                    indent=2,
                )
                scenario_file.write("\n")
            os.replace(temporary_path, path)
            temporary_path = ""
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror(
                "Could not save scenario", str(error), parent=self
            )
            self.status_var.set("Scenario save failed.")
            return
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        self.current_scenario_path = path
        self.title(f"MT5 Portfolio Risk Planner - {os.path.basename(path)}")
        self._update_robot_options()
        self.status_var.set(f"Scenario saved: {path}")

    def _load_scenario_dialog(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Load risk scenario",
            filetypes=(("MT5 risk scenario", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as scenario_file:
                data = json.load(scenario_file)
            scenario = self._validate_scenario(data)
            self._apply_scenario(scenario)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            messagebox.showerror(
                "Could not load scenario", str(error), parent=self
            )
            self.status_var.set("Scenario load failed; current values were kept.")
            return
        self.current_scenario_path = path
        self.title(f"MT5 Portfolio Risk Planner - {os.path.basename(path)}")
        self._update_robot_options()
        self.status_var.set(
            f"Scenario loaded: {path}. Saved quotes and Yahoo history are snapshots; "
            "refresh before relying on new suggestions."
        )

    def _apply_scenario(self, scenario: dict[str, object]) -> None:
        portfolio = scenario["portfolio"]
        new_allocation = scenario["new_allocation"]
        settings = scenario["settings"]
        raw_allocations = scenario["allocations"]
        assert isinstance(portfolio, dict)
        assert isinstance(new_allocation, dict)
        assert isinstance(settings, dict)
        assert isinstance(raw_allocations, list)

        self.account_capital_var.set(portfolio["account_capital"])
        self.currency_var.set(portfolio["currency"])
        self.daily_limit_var.set(portfolio["daily_limit"])
        self.remaining_daily_loss_room_var.set(
            str(portfolio.get("remaining_daily_loss_room", ""))
        )
        self.prop_total_loss_room_var.set(
            str(portfolio.get("prop_total_loss_room", ""))
        )
        self.limit_mode_var.set(portfolio["limit_mode"])
        self.index_var.set(new_allocation["symbol"])
        self.yahoo_ticker_var.set(new_allocation["yahoo_ticker"])
        self.auto_yahoo_ticker = YAHOO_ALIASES.get(
            self.index_var.get().strip().upper(), ""
        )
        self.robot_var.set(new_allocation["robot"])
        self.capital_var.set(new_allocation["capital"])

        for row_id in self.allocation_tree.get_children():
            self.allocation_tree.delete(row_id)
        self.allocations.clear()
        self.allocation_results.clear()
        self.quotes.clear()
        self.historical_stresses.clear()
        self.magic_assignments.clear()
        self.contract_inputs.clear()
        self.saved_quote_rows.clear()
        self.saved_history_rows.clear()
        self.current_settings_row = None
        contracts_to_restore: dict[str, ContractFields] = {}
        history_to_restore: dict[str, HistoricalStress] = {}
        for item in raw_allocations:
            assert isinstance(item, dict)
            self._insert_allocation(
                item["symbol"],
                item["yahoo_ticker"],
                item["robot"],
                item["capital"],
            )
            row_id = list(self.allocations)[-1]
            contracts_to_restore[row_id] = item["broker_contract"]
            history_data = item["historical_stress"]
            if history_data is not None:
                history_to_restore[row_id] = HistoricalStress(
                    long_adverse_pct=Decimal(history_data["long_adverse_pct"]),
                    long_observed_date=history_data["long_observed_date"],
                    short_adverse_pct=Decimal(history_data["short_adverse_pct"]),
                    short_observed_date=history_data["short_observed_date"],
                    bar_count=history_data["bar_count"],
                    start_date=history_data["start_date"],
                    end_date=history_data["end_date"],
                )
            magic_number = item["magic_number"]
            if magic_number is not None:
                self.magic_assignments[row_id] = magic_number
            quote_data = item["quote"]
            if quote_data is not None:
                quote_value: QuoteData = (
                    Decimal(quote_data["price"]),
                    quote_data["currency"],
                    quote_data["symbol"],
                    quote_data["timestamp"],
                )
                self.quotes[row_id] = quote_value
                self.saved_quote_rows.add(row_id)
                values = list(self.allocation_tree.item(row_id, "values"))
                values[4] = (
                    f"{format_decimal(quote_value[0])} {quote_value[1]} (saved)"
                )
                self.allocation_tree.item(row_id, values=values)

        self.contract_inputs.update(contracts_to_restore)
        self.historical_stresses.update(history_to_restore)
        self.saved_history_rows.update(history_to_restore)
        self.current_settings_row = None
        self.allocation_results.clear()
        selected_index = scenario["selected_allocation"]
        if selected_index is not None:
            selected_row = list(self.allocations)[selected_index]
            selected_item = self.allocations[selected_row]
            values = self.allocation_tree.item(selected_row, "values")
            selected_label = (
                f"{selected_item.index} | {selected_item.robot} | {values[1]}"
            )
            self.selected_allocation_var.set(selected_label)
            self.allocation_tree.selection_set(selected_row)
            self.allocation_tree.focus(selected_row)
        self._refresh_allocation_choices()
        selected_row = self._selected_row_id()
        if selected_row in self.allocations:
            self._load_contract_inputs(selected_row)
        text_settings = settings["text"]
        option_settings = settings["options"]
        assert isinstance(text_settings, dict)
        assert isinstance(option_settings, dict)
        for name, variable in self._scenario_string_settings().items():
            variable.set(text_settings[name])
        for name, variable in self._scenario_boolean_settings().items():
            variable.set(option_settings[name])
        self._update_stress_input_states()
        self._update_robot_options()
        self.output_text.delete("1.0", "end")

    def _build_portfolio_tab(self) -> None:
        account = ttk.LabelFrame(
            self.portfolio_tab,
            text="Account and daily drawdown limit",
            style="Section.TLabelframe",
            padding=10,
        )
        account.pack(fill="x", pady=(0, 10))

        self.account_capital_var = tk.StringVar(value="10000")
        self.currency_var = tk.StringVar(value="USD")
        self.daily_limit_var = tk.StringVar(value="4.5")
        self.remaining_daily_loss_room_var = tk.StringVar()
        self.prop_total_loss_room_var = tk.StringVar()
        self.limit_mode_var = tk.StringVar(value="Percent of account")

        fields = (
            ("Total account capital", self.account_capital_var, 16),
            ("Currency", self.currency_var, 10),
            ("Daily limit", self.daily_limit_var, 12),
        )
        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(account, text=label).grid(
                row=0, column=column * 2, sticky="w", padx=(0, 5), pady=3
            )
            ttk.Entry(account, textvariable=variable, width=width).grid(
                row=0, column=column * 2 + 1, sticky="w", padx=(0, 16), pady=3
            )
        ttk.Combobox(
            account,
            textvariable=self.limit_mode_var,
            values=("Percent of account", "Cash amount"),
            state="readonly",
            width=21,
        ).grid(row=0, column=6, sticky="w")
        ttk.Label(
            account,
            text="The limit is shared proportionally by each robot's allocated capital.",
        ).grid(row=1, column=0, columnspan=7, sticky="w", pady=(6, 0))
        ttk.Label(
            account,
            text="Remaining prop overall-loss room (cash; optional)",
        ).grid(row=2, column=0, columnspan=4, sticky="w", padx=(0, 5), pady=(5, 0))
        ttk.Entry(
            account, textvariable=self.prop_total_loss_room_var, width=18
        ).grid(row=2, column=4, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(
            account,
            text=(
                "Enter cash remaining before the prop firm's overall account-loss "
                "limit; it is applied alongside the daily rules."
            ),
            wraplength=1050,
        ).grid(row=3, column=0, columnspan=7, sticky="w", pady=(3, 0))
        ttk.Label(
            account,
            text="Remaining daily-loss room (cash; optional)",
        ).grid(row=4, column=0, columnspan=4, sticky="w", padx=(0, 5), pady=(5, 0))
        ttk.Entry(
            account, textvariable=self.remaining_daily_loss_room_var, width=18
        ).grid(row=4, column=4, columnspan=3, sticky="w", pady=(5, 0))
        ttk.Label(
            account,
            text=(
                "Enter daily room after today's realized losses and other open "
                "exposure; leave blank only when the full daily limit is available."
            ),
            wraplength=1050,
        ).grid(row=5, column=0, columnspan=7, sticky="w", pady=(3, 0))

        entry_box = ttk.LabelFrame(
            self.portfolio_tab,
            text="Add an index / robot allocation",
            style="Section.TLabelframe",
            padding=10,
        )
        entry_box.pack(fill="x", pady=(0, 10))
        self.index_var = tk.StringVar(value="US500")
        self.yahoo_ticker_var = tk.StringVar(value="^GSPC")
        self.auto_yahoo_ticker = "^GSPC"
        self.index_var.trace_add("write", self._suggest_yahoo_ticker)
        self.robot_var = tk.StringVar(value="RSI")
        self.capital_var = tk.StringVar(value="5000")
        for column, (label, variable, width) in enumerate(
            (
                ("Broker symbol", self.index_var, 13),
                ("Yahoo ticker", self.yahoo_ticker_var, 13),
                ("Robot", self.robot_var, 10),
                ("Capital assigned", self.capital_var, 14),
            )
        ):
            ttk.Label(entry_box, text=label).grid(
                row=0, column=column * 2, sticky="w", padx=(0, 5)
            )
            if label == "Robot":
                ttk.Combobox(
                    entry_box,
                    textvariable=variable,
                    values=("DCA", "RSI"),
                    state="readonly",
                    width=width,
                ).grid(row=0, column=column * 2 + 1, sticky="w", padx=(0, 12))
            else:
                ttk.Entry(entry_box, textvariable=variable, width=width).grid(
                    row=0, column=column * 2 + 1, sticky="w", padx=(0, 12)
                )
        ttk.Button(
            entry_box, text="Add allocation", command=self._add_allocation
        ).grid(row=0, column=8, padx=(8, 0))

        table_box = ttk.LabelFrame(
            self.portfolio_tab,
            text="Indexes and robots",
            style="Section.TLabelframe",
            padding=8,
        )
        table_box.pack(fill="both", expand=True)
        columns = ("symbol", "ticker", "robot", "capital", "quote", "daily")
        self.allocation_tree = ttk.Treeview(
            table_box, columns=columns, show="headings", height=9, selectmode="browse"
        )
        headings = {
            "symbol": "Broker symbol",
            "ticker": "Yahoo ticker",
            "robot": "Robot",
            "capital": "Capital",
            "quote": "Yahoo reference price",
            "daily": "Daily risk budget",
        }
        widths = {
            "symbol": 130,
            "ticker": 130,
            "robot": 85,
            "capital": 120,
            "quote": 180,
            "daily": 180,
        }
        for column in columns:
            self.allocation_tree.heading(column, text=headings[column])
            self.allocation_tree.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(
            table_box, orient="vertical", command=self.allocation_tree.yview
        )
        self.allocation_tree.configure(yscrollcommand=scrollbar.set)
        self.allocation_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.allocation_tree.bind("<<TreeviewSelect>>", self._portfolio_row_selected)

        actions = ttk.Frame(self.portfolio_tab)
        actions.pack(fill="x", pady=(10, 4))
        ttk.Button(
            actions,
            text="Remove selected",
            command=self._remove_selected_allocation,
        ).pack(side="left")
        ttk.Button(
            actions,
            text="Fetch price + 5y history for selected",
            command=self._fetch_selected_quote,
        ).pack(side="left", padx=8)
        self.fetch_all_button = ttk.Button(
            actions,
            text="Fetch Yahoo data for all",
            command=self._fetch_all_yahoo_data,
        )
        self.fetch_all_button.pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Import MT5 contract CSV",
            command=self._import_broker_specs,
        ).pack(side="left", padx=8)
        ttk.Button(
            actions,
            text="Calculate portfolio budgets",
            command=self._calculate_portfolio,
        ).pack(side="right")
        ttk.Label(
            self.portfolio_tab,
            text=(
                "Common symbols supported include US500, US100, US30, GER40, "
                "UK100, JP225, AUS200, HK50, EU50, FRA40, ESP35, CH20, "
                "NIFTY50 and more. Edit Yahoo ticker for broker-specific names; "
                "the Yahoo index may differ from your broker's CFD."
            ),
            wraplength=1080,
        ).pack(fill="x", pady=(7, 0))
        ttk.Label(
            self.portfolio_tab,
            text=(
                "MT5 CSV headers: symbol, point_size, "
                "point_value_per_point_per_lot (in account currency), "
                "account_currency, points_per_ea_pip, lot_step, min_lot. "
                "Fetch 5-year daily history to size fixed lots against each "
                "symbol's largest observed adverse daily range. Legacy "
                "profit_currency headers are accepted cautiously. "
                "You can create it with ExportMT5ContractSpecs.mq5 in MT5."
            ),
            wraplength=1080,
        ).pack(fill="x", pady=(3, 0))

    def _build_settings_tab(self) -> None:
        top = ttk.LabelFrame(
            self.settings_tab,
            text="Select robot and Yahoo reference price",
            style="Section.TLabelframe",
            padding=9,
        )
        top.pack(fill="x", pady=(0, 8))
        self.selected_allocation_var = tk.StringVar()
        self.allocation_combo = ttk.Combobox(
            top,
            textvariable=self.selected_allocation_var,
            state="readonly",
            width=36,
        )
        self.allocation_combo.pack(side="left", padx=(0, 8))
        self.allocation_combo.bind(
            "<<ComboboxSelected>>", self._allocation_combo_changed
        )
        self.fetch_button = ttk.Button(
            top,
            text="Fetch price + history",
            command=self._fetch_selected_quote,
        )
        self.fetch_button.pack(side="left")
        self.quote_label_var = tk.StringVar(value="No quote fetched")
        ttk.Label(top, textvariable=self.quote_label_var).pack(
            side="left", padx=12
        )
        self.robot_context_var = tk.StringVar(value="Select an allocation to load its scenario settings.")
        ttk.Label(
            top,
            textvariable=self.robot_context_var,
            wraplength=350,
        ).pack(side="right", padx=(8, 0))

        content = ttk.Frame(self.settings_tab)
        content.pack(fill="both", expand=True)
        controls_shell = ttk.Frame(content)
        controls_shell.pack(side="left", fill="y", padx=(0, 10))
        controls_canvas = tk.Canvas(
            controls_shell,
            width=650,
            highlightthickness=0,
            borderwidth=0,
        )
        controls_scrollbar = ttk.Scrollbar(
            controls_shell, orient="vertical", command=controls_canvas.yview
        )
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side="left", fill="y", expand=False)
        controls_scrollbar.pack(side="right", fill="y")
        controls = ttk.Frame(controls_canvas)
        controls_window = controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(
                scrollregion=controls_canvas.bbox("all")
            ),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(
                controls_window, width=event.width
            ),
        )
        def scroll_settings_controls(event: tk.Event) -> str | None:
            widget = self.winfo_containing(event.x_root, event.y_root)
            while widget is not None:
                if widget is controls_canvas:
                    controls_canvas.yview_scroll(int(-event.delta / 120), "units")
                    return "break"
                widget = widget.master
            return None

        controls_canvas.bind_all("<MouseWheel>", scroll_settings_controls, add="+")

        market = ttk.LabelFrame(
            controls,
            text="Market and broker contract values",
            style="Section.TLabelframe",
            padding=9,
        )
        market.pack(fill="x", pady=(0, 8))
        self.point_value_var = tk.StringVar()
        self.point_size_var = tk.StringVar()
        self.points_per_pip_var = tk.StringVar()
        self.contract_currency_var = tk.StringVar()
        self.step_type_var = tk.StringVar(value="Percentage")
        self.step_value_var = tk.StringVar(value="0.5")
        self.stress_pct_var = tk.StringVar(value="1")
        self.stress_mode_var = tk.StringVar(value=HISTORICAL_STRESS_MODE)
        self.stress_target_price_var = tk.StringVar()
        self.position_direction_var = tk.StringVar(value="Long (price falls)")
        self.stress_pct_var.trace_add("write", self._stress_percent_changed)
        self.lot_step_var = tk.StringVar()
        self.minimum_lot_var = tk.StringVar()
        self.compare_trades_var = tk.StringVar(value="10")
        self.selected_trades_var = tk.StringVar(value="3")

        self._add_entry(market, 0, "Value of 1 point per 1.00 lot (account currency)", self.point_value_var, 35)
        self._add_entry(market, 1, "MT5 point size (price increment)", self.point_size_var, 35)
        ttk.Label(market, text="Step Type").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(
            market,
            textvariable=self.step_type_var,
            values=("Percentage", "Fixed pips"),
            state="readonly",
            width=33,
        ).grid(row=2, column=1, sticky="ew", pady=3)
        self._add_entry(market, 3, "Step Value", self.step_value_var, 35)
        self._add_entry(market, 4, "Points per EA pip (fixed-pips only)", self.points_per_pip_var, 35)
        ttk.Label(market, text="Stress scenario").grid(row=5, column=0, sticky="w", pady=3)
        self.stress_mode_combo = ttk.Combobox(
            market,
            textvariable=self.stress_mode_var,
            values=(
                "Target price",
                "Adverse move (%)",
                HISTORICAL_STRESS_MODE,
            ),
            state="readonly",
            width=33,
        )
        self.stress_mode_combo.grid(row=5, column=1, sticky="ew", pady=3)
        self.stress_target_entry = self._add_entry(
            market, 6, "Price to withstand / stress target", self.stress_target_price_var, 35
        )
        self.target_suggestion_button = ttk.Button(
            market,
            text="Suggest target",
            command=self._suggest_target_from_ui,
        )
        self.target_suggestion_button.grid(row=6, column=2, padx=(6, 0), pady=3)
        self.stress_percent_entry = self._add_entry(
            market,
            7,
            "Adverse move % / historical stress used",
            self.stress_pct_var,
            35,
        )
        ttk.Label(market, text="Position direction").grid(row=8, column=0, sticky="w", pady=3)
        self.position_direction_combo = ttk.Combobox(
            market,
            textvariable=self.position_direction_var,
            values=("Long (price falls)", "Short (price rises)"),
            state="readonly",
            width=33,
        )
        self.position_direction_combo.grid(row=8, column=1, sticky="ew", pady=3)
        self.position_direction_combo.bind(
            "<<ComboboxSelected>>", self._position_direction_changed
        )
        self.stress_mode_combo.bind(
            "<<ComboboxSelected>>", self._update_stress_input_states
        )
        self._add_entry(market, 9, "Broker lot increment (e.g. 0.01)", self.lot_step_var, 35)
        self._add_entry(market, 10, "Broker minimum lot (e.g. 0.01)", self.minimum_lot_var, 35)
        self._add_entry(market, 11, "Max Trades candidates to compare (1-20)", self.compare_trades_var, 35)
        self._add_entry(market, 12, "Max Trades to output", self.selected_trades_var, 35)
        ttk.Label(market, text="Point-value currency (account currency)").grid(
            row=13, column=0, sticky="w", pady=3
        )
        ttk.Entry(
            market, textvariable=self.contract_currency_var, width=35, state="readonly"
        ).grid(row=13, column=1, sticky="ew", pady=3)

        ea = ttk.LabelFrame(
            controls,
            text="EA settings not determined by drawdown",
            style="Section.TLabelframe",
            padding=9,
        )
        ea.pack(fill="x", pady=(0, 8))
        self.magic_var = tk.StringVar(value="10001")
        self.take_profit_type_var = tk.StringVar(value="Fixed pips")
        self.take_profit_value_var = tk.StringVar()
        self._add_entry(ea, 0, "Magic Number (unique)", self.magic_var, 35)
        ttk.Label(ea, text="Take Profit Type").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(
            ea,
            textvariable=self.take_profit_type_var,
            values=("Fixed pips", "Percentage"),
            state="readonly",
            width=33,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        self._add_entry(ea, 2, "Take Profit Value", self.take_profit_value_var, 35)

        self.entry_break_var = tk.BooleanVar(value=False)
        self.price_break_type_var = tk.StringVar(value="break Below")
        self.reference_price_var = tk.StringVar()
        self.reference_price_var.trace_add("write", self._reference_price_changed)
        self.trade_new_candle_var = tk.BooleanVar(value=True)
        self.show_dca_invested_var = tk.BooleanVar(value=True)
        self.close_overbought_var = tk.BooleanVar(value=True)
        self.rsi_oversold_var = tk.StringVar(value="30")
        self.rsi_overbought_var = tk.StringVar(value="70")
        self.rsi_period_var = tk.StringVar(value="14")
        self.show_rsi_invested_var = tk.BooleanVar(value=True)

        self.robot_options_container = ttk.Frame(controls)
        self.robot_options_container.pack(fill="x", pady=(0, 8))
        dca = ttk.LabelFrame(
            self.robot_options_container,
            text="DCA options (used for DCA allocations)",
            style="Section.TLabelframe",
            padding=9,
        )
        self.dca_settings_frame = dca
        ttk.Checkbutton(
            dca, text="Entry on price break", variable=self.entry_break_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(dca, text="InpPriceBreakType").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(
            dca,
            textvariable=self.price_break_type_var,
            values=("break Below", "break Above"),
            state="readonly",
            width=33,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        self._add_entry(dca, 2, "Reference Price", self.reference_price_var, 35)
        ttk.Checkbutton(
            dca, text="Trade on new candle", variable=self.trade_new_candle_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(
            dca, text="Show Invested Money", variable=self.show_dca_invested_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)

        rsi = ttk.LabelFrame(
            self.robot_options_container,
            text="RSI options (used for RSI allocations)",
            style="Section.TLabelframe",
            padding=9,
        )
        self.rsi_settings_frame = rsi
        ttk.Checkbutton(
            rsi, text="Close When Overbought", variable=self.close_overbought_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=3)
        self._add_entry(rsi, 1, "RSI oversold", self.rsi_oversold_var, 35)
        self._add_entry(rsi, 2, "RSI Overbought", self.rsi_overbought_var, 35)
        self._add_entry(rsi, 3, "RSI Period", self.rsi_period_var, 35)
        ttk.Checkbutton(
            rsi, text="Show Invested Money", variable=self.show_rsi_invested_var
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)

        result_frame = ttk.LabelFrame(
            content,
            text="Candidate limits and complete EA configuration",
            style="Section.TLabelframe",
            padding=8,
        )
        result_frame.pack(side="left", fill="both", expand=True)
        self.output_text = tk.Text(
            result_frame,
            wrap="word",
            font=("Consolas", 10),
            height=28,
            width=60,
        )
        output_scroll = ttk.Scrollbar(
            result_frame, orient="vertical", command=self.output_text.yview
        )
        self.output_text.configure(yscrollcommand=output_scroll.set)
        self.output_text.pack(side="left", fill="both", expand=True)
        output_scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(self.settings_tab)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(
            buttons,
            text="Suggest all robots (price fall)",
            command=self._suggest_portfolio_downside,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons,
            text="Generate candidate settings",
            command=self._generate_settings,
        ).pack(side="right")
        ttk.Button(
            buttons, text="Copy output", command=self._copy_output
        ).pack(side="right", padx=8)
        ttk.Label(
            buttons,
            text=(
                "Yahoo prices are indicative, not your broker's CFD quote. "
                "Use MT5 contract specifications for point value and lot rules."
            ),
            wraplength=760,
        ).pack(side="left")
        self._update_stress_input_states()

    @staticmethod
    def _add_entry(
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        width: int,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 6), pady=3
        )
        entry = ttk.Entry(parent, textvariable=variable, width=width)
        entry.grid(
            row=row, column=1, sticky="ew", pady=3
        )
        return entry

    def _add_default_allocation(self) -> None:
        self._insert_allocation("US500", "^GSPC", "RSI", "5000")

    def _suggest_yahoo_ticker(self, *_args: str) -> None:
        current_ticker = self.yahoo_ticker_var.get().strip()
        suggested_ticker = YAHOO_ALIASES.get(self.index_var.get().strip().upper(), "")
        if not current_ticker or current_ticker == self.auto_yahoo_ticker:
            self.yahoo_ticker_var.set(suggested_ticker)
        self.auto_yahoo_ticker = suggested_ticker

    def _insert_allocation(
        self,
        symbol: str,
        ticker: str,
        robot: str,
        capital_text: str,
    ) -> None:
        symbol = symbol.strip()
        robot = robot.strip().upper()
        if not symbol:
            raise ValueError("Enter the broker symbol.")
        if robot not in {"DCA", "RSI"}:
            raise ValueError("Robot must be DCA or RSI.")
        capital = decimal_value(capital_text, "Allocated capital")
        if capital <= ZERO:
            raise ValueError("Allocated capital must be greater than zero.")
        ticker = yahoo_symbol_for(symbol, ticker)
        row_id = f"allocation-{len(self.allocations) + 1}"
        while row_id in self.allocations:
            row_id += "-new"
        allocation = Allocation(symbol, robot, capital)
        self.allocations[row_id] = allocation
        self.allocation_tree.insert(
            "",
            "end",
            iid=row_id,
            values=(symbol, ticker, robot, format_decimal(capital), "Not fetched", "Not calculated"),
        )
        self.allocation_results.clear()
        self._refresh_allocation_choices()
        self.allocation_tree.selection_set(row_id)
        self.allocation_tree.focus(row_id)
        label = next(
            label for label, allocation_id in self.selection_ids.items()
            if allocation_id == row_id
        )
        self.selected_allocation_var.set(label)
        self._selection_changed()

    def _add_allocation(self) -> None:
        try:
            self._insert_allocation(
                self.index_var.get(),
                self.yahoo_ticker_var.get(),
                self.robot_var.get(),
                self.capital_var.get(),
            )
            self.status_var.set("Allocation added.")
        except ValueError as error:
            messagebox.showerror("Invalid allocation", str(error), parent=self)

    def _remove_selected_allocation(self) -> None:
        selected = self.allocation_tree.selection()
        if not selected:
            messagebox.showinfo("Select an allocation", "Select a row to remove.", parent=self)
            return
        row_id = selected[0]
        self.allocation_tree.delete(row_id)
        self.allocations.pop(row_id, None)
        self.allocation_results.clear()
        self.quotes.pop(row_id, None)
        self.historical_stresses.pop(row_id, None)
        self.magic_assignments.pop(row_id, None)
        self.contract_inputs.pop(row_id, None)
        self.saved_quote_rows.discard(row_id)
        self.saved_history_rows.discard(row_id)
        if self.current_settings_row == row_id:
            self.current_settings_row = None
        self._refresh_allocation_choices()
        self.status_var.set("Allocation removed.")

    def _refresh_allocation_choices(self) -> None:
        choices = []
        self.selection_ids.clear()
        for row_id, allocation in self.allocations.items():
            values = self.allocation_tree.item(row_id, "values")
            ticker = values[1]
            label = f"{allocation.index} | {allocation.robot} | {ticker}"
            choices.append(label)
            self.selection_ids[label] = row_id
        self.allocation_combo["values"] = choices
        if choices and self.selected_allocation_var.get() not in self.selection_ids:
            self.selected_allocation_var.set(choices[0])
        self._selection_changed()

    def _selected_row_id(self) -> str | None:
        return self.selection_ids.get(self.selected_allocation_var.get())

    def _allocation_combo_changed(self, _event: object = None) -> None:
        self._selection_changed()
        if self.notebook.select() == str(self.settings_tab):
            self._main_tab_changed()

    def _portfolio_row_selected(self, _event: object = None) -> None:
        selected = self.allocation_tree.selection()
        if not selected:
            return
        row_id = selected[0]
        for label, allocation_id in self.selection_ids.items():
            if allocation_id == row_id:
                self.selected_allocation_var.set(label)
                self._selection_changed()
                return

    @staticmethod
    def _normalized_broker_symbol(symbol: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", symbol.strip().upper())

    @classmethod
    def _broker_symbol_base(cls, symbol: str) -> str:
        normalized = cls._normalized_broker_symbol(symbol)
        for suffix in ("MICRO", "MINI", "CASH", "INDEX", "PRO", "M", "I", "C"):
            if normalized.endswith(suffix):
                return normalized[: -len(suffix)]
        return normalized

    @classmethod
    def _read_broker_contract_csv(cls, path: str) -> dict[str, ContractFields]:
        with open(path, "r", encoding="utf-8-sig", newline="") as source:
            sample = source.read(4096)
            if not sample.strip():
                raise ValueError("The MT5 contract CSV is empty.")
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            source.seek(0)
            reader = csv.DictReader(source, dialect=dialect)
            if not reader.fieldnames:
                raise ValueError("The MT5 contract CSV must have a header row.")

            header_lookup = {
                re.sub(r"[^a-z0-9]", "", header.casefold()): header
                for header in reader.fieldnames
                if header
            }
            aliases = {
                "symbol": ("symbol", "brokersymbol"),
                "point_size": ("pointsize", "mt5pointsize"),
                "point_value": (
                    "pointvalueperpointperlot",
                    "pointvalueperpointperlotaccountcurrency",
                    "pointvalueaccountcurrencyperpointperlot",
                    "cashperpointperlot",
                ),
                "points_per_pip": ("pointspereapip", "pointsperpip"),
                "lot_increment": ("lotstep", "volumestep"),
                "minimum_lot": ("minlot", "volumemin"),
                "contract_currency": (
                    "accountcurrency",
                    "pointvaluecurrency",
                    "accountcurrencyforpointvalue",
                    "profitcurrency",
                    "contractcurrency",
                ),
            }
            selected_headers: dict[str, str] = {}
            for field, candidates in aliases.items():
                header = next(
                    (header_lookup[name] for name in candidates if name in header_lookup),
                    None,
                )
                if header:
                    selected_headers[field] = header
            required_fields = (
                "symbol",
                "point_size",
                "point_value",
                "lot_increment",
                "minimum_lot",
            )
            missing = [field for field in required_fields if field not in selected_headers]
            if missing:
                raise ValueError(
                    "Missing required CSV columns: "
                    + ", ".join(missing)
                    + ". See the CSV format note in the Portfolio tab."
                )

            contracts: dict[str, ContractFields] = {}
            for line_number, row in enumerate(reader, start=2):
                if not row or not any(value and value.strip() for value in row.values()):
                    continue
                symbol = (row.get(selected_headers["symbol"]) or "").strip()
                key = cls._normalized_broker_symbol(symbol)
                if not key:
                    raise ValueError(f"CSV row {line_number} has no symbol.")
                if key in contracts:
                    raise ValueError(f"CSV has duplicate symbol '{symbol}'.")

                contract: ContractFields = {}
                for field, header in selected_headers.items():
                    contract[field] = (row.get(header) or "").strip()
                contract["symbol"] = symbol
                for field in (
                    "point_size",
                    "point_value",
                    "lot_increment",
                    "minimum_lot",
                ):
                    value = decimal_value(
                        contract[field], f"CSV row {line_number} {field}"
                    )
                    if value <= ZERO:
                        raise ValueError(
                            f"CSV row {line_number} {field} must be greater than zero."
                        )
                    contract[field] = format_decimal(value)
                if contract.get("points_per_pip"):
                    points_per_pip = decimal_value(
                        contract["points_per_pip"],
                        f"CSV row {line_number} points_per_pip",
                    )
                    if points_per_pip <= ZERO:
                        raise ValueError(
                            f"CSV row {line_number} points_per_pip must be positive."
                        )
                    contract["points_per_pip"] = format_decimal(points_per_pip)
                contract.setdefault("points_per_pip", "")
                contract.setdefault("contract_currency", "")
                contracts[key] = contract

        if not contracts:
            raise ValueError("The MT5 contract CSV contains no symbol rows.")
        return contracts

    def _capture_contract_inputs(self, row_id: str) -> None:
        if row_id not in self.allocations:
            return
        self.contract_inputs[row_id] = {
            key: variable.get().strip()
            for key, variable in self._contract_input_variables().items()
        }

    def _contract_inputs_for_allocation(self, row_id: str) -> ContractFields:
        contract = dict(self.contract_inputs.get(row_id, {}))
        if row_id == self.current_settings_row:
            for key, variable in self._contract_input_variables().items():
                value = variable.get().strip()
                if value:
                    contract[key] = value
        return contract

    def _load_contract_inputs(self, row_id: str) -> None:
        fields = self.contract_inputs.get(row_id, {})
        for key, variable in self._contract_input_variables().items():
            variable.set(fields.get(key, ""))

    def _import_broker_specs(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Import MT5 contract specifications",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            contracts = self._read_broker_contract_csv(path)
            unmatched: list[str] = []
            matched = 0
            for row_id, allocation in self.allocations.items():
                exact_key = self._normalized_broker_symbol(allocation.index)
                contract = contracts.get(exact_key)
                if contract is None:
                    base_key = self._broker_symbol_base(allocation.index)
                    candidates = [
                        item
                        for item in contracts.values()
                        if self._broker_symbol_base(item["symbol"]) == base_key
                    ]
                    if len(candidates) == 1:
                        contract = candidates[0]
                    elif len(candidates) > 1:
                        unmatched.append(f"{allocation.index} (ambiguous symbol match)")
                        continue
                if contract is None:
                    unmatched.append(allocation.index)
                    continue
                self.contract_inputs[row_id] = {
                    key: contract.get(key, "")
                    for key in self._contract_input_variables()
                }
                matched += 1

            if matched == 0:
                raise ValueError(
                    "No CSV symbol matched the current portfolio. Check that the "
                    "CSV contains the exact MT5 Market Watch symbols."
                )
            selected = self._selected_row_id()
            if selected in self.allocations:
                self._load_contract_inputs(selected)
            self.status_var.set(
                f"Imported broker specifications for {matched} allocation(s)."
            )
            if unmatched:
                messagebox.showwarning(
                    "Some symbols were not matched",
                    f"Imported {matched} symbol(s). Add or correct CSV data for: "
                    + ", ".join(unmatched),
                    parent=self,
                )
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            self.status_var.set("MT5 contract import failed.")
            messagebox.showerror("Could not import MT5 data", str(error), parent=self)

    def _main_tab_changed(self, _event: object = None) -> None:
        if self.notebook.select() != str(self.settings_tab):
            return
        self._selection_changed()
        row_id = self._selected_row_id()
        if row_id is None:
            self._show_settings_hint(
                "Load a JSON scenario or add an allocation in the Portfolio tab."
            )
            return
        self.output_text.delete("1.0", "end")
        try:
            self._generate_settings_checked(show_errors=False)
        except (ValueError, InvalidOperation, ZeroDivisionError) as error:
            self._show_settings_hint(
                f"Scenario loaded for {self.allocations[row_id].index} / "
                f"{self.allocations[row_id].robot}.\n\n{error}"
            )
        else:
            if not self.output_text.get("1.0", "end").strip():
                self._show_settings_hint(
                    f"Scenario loaded for {self.allocations[row_id].index} / "
                    f"{self.allocations[row_id].robot}.\n\n"
                    "Import the MT5 contract CSV and fetch Yahoo price plus "
                    "5-year daily history. Set a strategy-specific Take Profit "
                    "value if you want a complete EA configuration."
                )

    def _show_settings_hint(self, text: str) -> None:
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", text)
        self.status_var.set(text.replace("\n", " ")[:180])

    def _update_robot_options(self, row_id: str | None = None) -> None:
        row_id = row_id or self._selected_row_id()
        self.dca_settings_frame.pack_forget()
        self.rsi_settings_frame.pack_forget()
        if row_id is None or row_id not in self.allocations:
            self.robot_context_var.set(
                "Select or load an allocation to display its robot settings."
            )
            return
        allocation = self.allocations[row_id]
        selected_frame = (
            self.dca_settings_frame
            if allocation.robot.upper() == "DCA"
            else self.rsi_settings_frame
        )
        selected_frame.pack(fill="x", pady=(0, 8))
        scenario_name = (
            os.path.basename(self.current_scenario_path)
            if self.current_scenario_path
            else "current scenario"
        )
        self.robot_context_var.set(
            f"{scenario_name} | {allocation.index} / {allocation.robot} settings"
        )

    def _update_stress_input_states(self, _event: object = None) -> None:
        if not hasattr(self, "stress_target_entry"):
            return
        mode = self.stress_mode_var.get()
        if mode == HISTORICAL_STRESS_MODE:
            self.stress_target_entry.configure(state="readonly")
            self.stress_percent_entry.configure(state="readonly")
            self.target_suggestion_button.configure(state="disabled")
            self.auto_stress_target_price = None
            self.stress_target_price_var.set("")
            row_id = self._selected_row_id()
            historical = self.historical_stresses.get(row_id) if row_id else None
            if historical is None:
                self.stress_pct_var.set("")
                return
            stress_percent = (
                historical.short_adverse_pct
                if self.position_direction_var.get() == "Short (price rises)"
                else historical.long_adverse_pct
            )
            self.stress_pct_var.set(format_decimal(stress_percent))
            self._suggest_stress_target()
            return
        if mode == "Target price":
            self.stress_target_entry.configure(state="normal")
        else:
            self.stress_target_entry.configure(state="readonly")
        self.stress_percent_entry.configure(state="normal")
        self.target_suggestion_button.configure(state="normal")

    def _suggest_target_from_ui(self) -> None:
        self.auto_stress_target_price = None
        self.stress_target_price_var.set("")
        self._suggest_stress_target()
        if self.stress_target_price_var.get():
            self.status_var.set(
                f"Suggested adverse target price: {self.stress_target_price_var.get()}"
            )
        else:
            self.status_var.set("Fetch a Yahoo price or enter a reference price first.")

    def _suggest_stress_target(self, base_price: Decimal | None = None) -> None:
        current_value = self.stress_target_price_var.get().strip()
        if (
            current_value
            and current_value != self.auto_stress_target_price
        ):
            return
        try:
            if base_price is None:
                base_price = decimal_value(
                    self.reference_price_var.get(), "Reference price"
                )
            percent = decimal_value(
                self.stress_pct_var.get(), "Adverse move percent"
            )
        except ValueError:
            return
        if base_price <= ZERO or not ZERO < percent < ONE_HUNDRED:
            return
        factor = ONE - percent / ONE_HUNDRED
        if self.position_direction_var.get() == "Short (price rises)":
            factor = ONE + percent / ONE_HUNDRED
        suggested = format_decimal(base_price * factor)
        self.auto_stress_target_price = suggested
        self.stress_target_price_var.set(suggested)

    def _stress_percent_changed(self, *_args: str) -> None:
        if not hasattr(self, "stress_target_price_var"):
            return
        current = self.stress_target_price_var.get().strip()
        if not current or current == self.auto_stress_target_price:
            self.stress_target_price_var.set("")
            self.auto_stress_target_price = None
            self._suggest_stress_target()

    def _reference_price_changed(self, *_args: str) -> None:
        if not hasattr(self, "stress_target_price_var"):
            return
        current = self.stress_target_price_var.get().strip()
        if not current or current == self.auto_stress_target_price:
            self.stress_target_price_var.set("")
            self.auto_stress_target_price = None
            self._suggest_stress_target()

    def _position_direction_changed(self, _event: object = None) -> None:
        if self.stress_mode_var.get() == HISTORICAL_STRESS_MODE:
            self._update_stress_input_states()
        else:
            self._suggest_stress_target()

    def _selection_changed(self, _event: object = None) -> None:
        row_id = self._selected_row_id()
        if not row_id:
            self.quote_label_var.set("No allocation selected")
            self._update_robot_options()
            return
        changed_selection = row_id != self.current_settings_row
        if changed_selection:
            if self.current_settings_row in self.allocations:
                self._capture_contract_inputs(self.current_settings_row)
            self.current_settings_row = row_id
            magic_number = self.magic_assignments.get(row_id)
            if magic_number is None:
                used_numbers = set(self.magic_assignments.values())
                magic_number = 10001
                while magic_number in used_numbers:
                    magic_number += 1
            self.magic_var.set(str(magic_number))
            self.reference_price_var.set("")
            self.stress_target_price_var.set("")
            self.auto_stress_target_price = None
            self._load_contract_inputs(row_id)
        quote_data = self.quotes.get(row_id)
        if quote_data:
            price, currency, yahoo_symbol, timestamp = quote_data
            saved_mark = " (saved snapshot)" if row_id in self.saved_quote_rows else ""
            historical = self.historical_stresses.get(row_id)
            history_mark = (
                f" | 5y history: {historical.bar_count} bars"
                + (" (saved snapshot)" if row_id in self.saved_history_rows else "")
                if historical is not None
                else " | no 5y history"
            )
            self.quote_label_var.set(
                f"{yahoo_symbol}: {format_decimal(price)} {currency} "
                f"({timestamp}){saved_mark}{history_mark}"
            )
            if changed_selection or not self.reference_price_var.get().strip():
                self.reference_price_var.set(format_decimal(price))
            if changed_selection or not self.stress_target_price_var.get().strip():
                self._suggest_stress_target(price)
        else:
            self.quote_label_var.set("No quote fetched")
        self._update_stress_input_states()
        self._update_robot_options(row_id)

    def _portfolio_risk_limits(
        self,
    ) -> tuple[
        Decimal, Decimal, Decimal | None, Decimal | None, Decimal
    ]:
        account_capital = decimal_value(
            self.account_capital_var.get(), "Total account capital"
        )
        daily_value = decimal_value(self.daily_limit_var.get(), "Daily limit")
        if self.limit_mode_var.get() == "Percent of account":
            if not ZERO < daily_value <= ONE_HUNDRED:
                raise ValueError("Daily limit percent must be between 0 and 100.")
            daily_limit = account_capital * daily_value / ONE_HUNDRED
        else:
            daily_limit = daily_value
        if daily_limit > account_capital:
            raise ValueError("Daily loss limit cannot exceed account capital.")

        daily_room_text = self.remaining_daily_loss_room_var.get().strip()
        remaining_daily_room = (
            decimal_value(daily_room_text, "Remaining daily-loss room")
            if daily_room_text
            else None
        )
        if remaining_daily_room is not None and remaining_daily_room > daily_limit:
            raise ValueError(
                "Remaining daily-loss room cannot exceed the configured daily limit."
            )

        room_text = self.prop_total_loss_room_var.get().strip()
        prop_loss_room = (
            decimal_value(room_text, "Remaining prop total-loss room")
            if room_text
            else None
        )
        if prop_loss_room is not None and prop_loss_room > account_capital:
            raise ValueError(
                "Remaining prop total-loss room cannot exceed total account capital."
            )
        effective_cap = effective_portfolio_risk_cap(
            daily_limit,
            remaining_daily_room,
            prop_loss_room,
        )
        return (
            account_capital,
            daily_limit,
            remaining_daily_room,
            prop_loss_room,
            effective_cap,
        )

    def _calculate_portfolio(self, show_error: bool = True) -> bool:
        try:
            account_capital, daily_limit, _daily_room, _prop_room, effective_cap = (
                self._portfolio_risk_limits()
            )
            result = calculate_portfolio(
                account_capital,
                effective_cap,
                tuple(self.allocations.values()),
            )
            self.allocation_results = dict(
                zip(self.allocations.keys(), result.allocations)
            )
            for row_id, allocation_result in self.allocation_results.items():
                values = list(self.allocation_tree.item(row_id, "values"))
                quote_data = self.quotes.get(row_id)
                values[4] = (
                    f"{format_decimal(quote_data[0])} {quote_data[1]}"
                    if quote_data
                    else "Not fetched"
                )
                if quote_data and row_id in self.saved_quote_rows:
                    values[4] += " (saved)"
                values[5] = (
                    f"{format_decimal(allocation_result.daily_loss_budget, 2)} "
                    f"{self.currency_var.get().strip() or 'account currency'}"
                )
                self.allocation_tree.item(row_id, values=values)
            self.status_var.set(
                f"Daily limit: {format_decimal(daily_limit, 2)}; effective "
                f"portfolio risk cap: {format_decimal(effective_cap, 2)} "
                f"{self.currency_var.get().strip() or 'account currency'}; "
                f"{len(self.allocations)} allocation(s)."
            )
            self._refresh_allocation_choices()
            return True
        except ValueError as error:
            self.allocation_results.clear()
            self.status_var.set(str(error))
            if show_error:
                messagebox.showerror("Cannot calculate portfolio", str(error), parent=self)
            return False

    def _fetch_selected_quote(self) -> None:
        if self.quote_busy:
            return
        row_id = self._selected_row_id()
        if row_id is None:
            messagebox.showinfo(
                "Select an allocation",
                "Add and select an allocation first.",
                parent=self,
            )
            return
        allocation = self.allocations[row_id]
        values = self.allocation_tree.item(row_id, "values")
        ticker = yahoo_symbol_for(allocation.index, values[1])
        self._set_fetch_busy(True)
        self.status_var.set(f"Fetching {ticker} price and 5-year daily history...")

        def worker() -> None:
            self.quote_messages.put(
                (row_id, "one", self._request_yahoo_data(row_id, ticker))
            )

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _fetch_all_yahoo_data(self) -> None:
        if self.quote_busy:
            return
        requests = []
        for row_id, allocation in self.allocations.items():
            values = self.allocation_tree.item(row_id, "values")
            requests.append(
                (row_id, yahoo_symbol_for(allocation.index, values[1]))
            )
        if not requests:
            messagebox.showinfo(
                "No allocations",
                "Add at least one robot allocation first.",
                parent=self,
            )
            return
        self._set_fetch_busy(True)
        self._begin_yahoo_batch(len(requests))
        self.status_var.set(
            f"Fetching Yahoo prices and 5-year history for {len(requests)} allocation(s)..."
        )

        def worker() -> None:
            for row_id, ticker in requests:
                result = self._request_yahoo_data(row_id, ticker)
                self.quote_messages.put((row_id, "batch_item", result))
            self.quote_messages.put(("__all__", "batch_done", None))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    @staticmethod
    def _request_yahoo_data(row_id: str, ticker: str) -> YahooDataResult:
        try:
            quote_data = fetch_yahoo_quote(ticker)
        except (ValueError, OSError, KeyError, TypeError, OverflowError) as error:
            return YahooDataResult(
                row_id=row_id,
                quote=None,
                history=None,
                error=f"Price request failed: {error}",
            )
        try:
            history = fetch_yahoo_historical_stress(ticker)
        except (
            ValueError,
            OSError,
            KeyError,
            TypeError,
            IndexError,
            OverflowError,
        ) as error:
            return YahooDataResult(
                row_id=row_id,
                quote=quote_data,
                history=None,
                error=f"5-year history unavailable: {error}",
            )
        return YahooDataResult(
            row_id=row_id,
            quote=quote_data,
            history=history,
            error=None,
        )

    def _set_fetch_busy(self, busy: bool) -> None:
        self.quote_busy = busy
        state = "disabled" if busy else "normal"
        self.fetch_button.configure(state=state)
        if self.fetch_all_button is not None:
            self.fetch_all_button.configure(state=state)

    def _poll_quote_result(self) -> None:
        try:
            row_id, status, result = self.quote_messages.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_quote_result)
            return
        if status == "one":
            self._set_fetch_busy(False)
            if isinstance(result, YahooDataResult):
                self._apply_yahoo_data_result(result)
                if result.error:
                    if self.notebook.select() == str(self.settings_tab):
                        self.output_text.delete("1.0", "end")
                        self.output_text.insert(
                            "1.0",
                            "NO SETTINGS GENERATED\n\n"
                            f"{result.error}\n\n"
                            "Check the Yahoo ticker and internet connection, then "
                            "retry the suggestion.",
                        )
                    self.status_var.set(result.error)
                    messagebox.showwarning(
                        "Yahoo Finance data incomplete",
                        result.error,
                        parent=self,
                    )
                else:
                    self.status_var.set(
                        f"Updated Yahoo price and 5-year daily history for {result.row_id}."
                    )
            self.after(100, self._poll_quote_result)
            return
        if status == "batch_item":
            if isinstance(result, YahooDataResult):
                self._apply_yahoo_data_result(result, refresh_settings=False)
                self.batch_completed += 1
                if result.error:
                    allocation = self.allocations.get(row_id)
                    symbol = allocation.index if allocation is not None else row_id
                    self.batch_errors.append(
                        f"{symbol}: {result.error}"
                    )
                self.status_var.set(
                    f"Fetched Yahoo data for {self.batch_completed} of "
                    f"{self.batch_total} allocation(s)..."
                )
            self.after(100, self._poll_quote_result)
            return
        if status == "batch_done":
            self._set_fetch_busy(False)
            self._calculate_portfolio(show_error=False)
            portfolio_suggestion = self.portfolio_suggestion_pending
            self.portfolio_suggestion_pending = False
            if portfolio_suggestion and self.batch_errors:
                self._show_portfolio_suggestion_error(
                    "Yahoo data is incomplete for one or more allocations:\n"
                    + "\n".join(self.batch_errors)
                )
            elif portfolio_suggestion:
                self._generate_portfolio_settings_checked()
            elif self.notebook.select() == str(self.settings_tab):
                self._main_tab_changed()
            if self.batch_errors:
                self.status_var.set(
                    f"Yahoo data fetched with {len(self.batch_errors)} incomplete allocation(s)."
                )
                messagebox.showwarning(
                    "Some Yahoo data is incomplete",
                    "\n".join(self.batch_errors),
                    parent=self,
                )
            elif not portfolio_suggestion:
                self.status_var.set(
                    f"Fetched current prices and 5-year daily history for "
                    f"{self.batch_completed} allocation(s)."
                )
            return
        self._set_fetch_busy(False)
        self.status_var.set("Yahoo Finance returned an invalid response.")
        messagebox.showerror(
            "Yahoo Finance",
            "The returned result had an invalid format.",
            parent=self,
        )

    def _apply_yahoo_data_result(
        self,
        result: YahooDataResult,
        refresh_settings: bool = True,
    ) -> None:
        row_id = result.row_id
        if row_id not in self.allocations:
            return
        if result.quote is None:
            return
        self.quotes[row_id] = result.quote
        self.saved_quote_rows.discard(row_id)
        if result.history is not None:
            self.historical_stresses[row_id] = result.history
            self.saved_history_rows.discard(row_id)
        price, currency, yahoo_symbol, timestamp = result.quote
        values = list(self.allocation_tree.item(row_id, "values"))
        values[4] = f"{format_decimal(price)} {currency}"
        self.allocation_tree.item(row_id, values=values)
        if self._selected_row_id() == row_id:
            historical = self.historical_stresses.get(row_id)
            history_label = (
                f" | Yahoo 5y history ({historical.bar_count} bars)"
                + (
                    " (saved snapshot)"
                    if row_id in self.saved_history_rows
                    else ""
                )
                if historical is not None
                else " | no 5y history"
            )
            self.quote_label_var.set(
                f"{yahoo_symbol}: {format_decimal(price)} {currency} "
                f"({timestamp}){history_label}"
            )
            self.reference_price_var.set(format_decimal(price))
            self._update_stress_input_states()
        if refresh_settings:
            self._calculate_portfolio(show_error=False)
            if self.notebook.select() == str(self.settings_tab):
                self._main_tab_changed()

    def _begin_yahoo_batch(self, allocation_count: int) -> None:
        self.batch_total = allocation_count
        self.batch_completed = 0
        self.batch_errors: list[str] = []

    def _generate_settings(self) -> None:
        row_id = self._selected_row_id()
        needs_history = self.stress_mode_var.get() == HISTORICAL_STRESS_MODE
        if row_id is not None and (
            row_id not in self.quotes
            or (needs_history and row_id not in self.historical_stresses)
        ):
            if self.quote_busy:
                self.status_var.set(
                    "Yahoo data is already being fetched; wait for it to finish."
                )
                return
            self.output_text.delete("1.0", "end")
            self.output_text.insert(
                "1.0",
                "Fetching Yahoo's current price and 5-year daily history. "
                "Settings will be generated automatically when the download finishes.\n",
            )
            self._fetch_selected_quote()
            return
        try:
            self._generate_settings_checked(show_errors=True)
        except (ValueError, InvalidOperation, ZeroDivisionError) as error:
            self.output_text.delete("1.0", "end")
            self.output_text.insert(
                "1.0",
                "NO SETTINGS GENERATED\n\n"
                f"{error}\n\n"
                "The previous settings were cleared. Correct the missing or "
                "incompatible inputs before using this robot configuration.",
            )
            self.status_var.set("Settings were not generated; review the error.")
            messagebox.showerror("Cannot generate settings", str(error), parent=self)

    def _suggest_portfolio_downside(self) -> None:
        if not self.allocations:
            self._show_portfolio_suggestion_error(
                "Add at least one index/robot allocation before requesting a suggestion."
            )
            return
        if self.quote_busy:
            self.status_var.set(
                "Wait for the current Yahoo download to finish before requesting "
                "the full-portfolio suggestion."
            )
            return

        self.stress_mode_var.set(HISTORICAL_STRESS_MODE)
        self.position_direction_var.set("Long (price falls)")
        self._update_stress_input_states()
        self.portfolio_suggestion_pending = True
        self.output_text.delete("1.0", "end")
        self.output_text.insert(
            "1.0",
            "Refreshing Yahoo prices and 5-year histories for every allocation. "
            "The combined downside suggestion will be generated when all "
            "downloads finish.\n",
        )
        self._fetch_all_yahoo_data()

    def _show_portfolio_suggestion_error(self, error: str) -> None:
        self.output_text.delete("1.0", "end")
        self.output_text.insert(
            "1.0",
            "NO FULL-PORTFOLIO SETTINGS GENERATED\n\n"
            f"{error}\n\n"
            "No partial or stale suggestion is safe to use. Import matching MT5 "
            "contract data and resolve every listed allocation before retrying.",
        )
        self.status_var.set("Full-portfolio suggestion unavailable; see details.")

    def _generate_portfolio_settings_checked(self) -> None:
        self.output_text.delete("1.0", "end")
        try:
            self._generate_settings_checked(
                show_errors=False,
                require_complete_portfolio=True,
            )
        except (ValueError, InvalidOperation, ZeroDivisionError) as error:
            self._show_portfolio_suggestion_error(str(error))
            messagebox.showerror(
                "Cannot suggest full-portfolio settings",
                str(error),
                parent=self,
            )

    def _portfolio_stress_report(
        self,
        selected_row: str,
        step_type: str,
        step_value: Decimal,
        stress_percent: Decimal,
        max_trades: int,
    ) -> list[str]:
        currency = self.currency_var.get().strip() or "account currency"
        historical_mode = self.stress_mode_var.get() == HISTORICAL_STRESS_MODE
        is_long = self.position_direction_var.get() == "Long (price falls)"
        rows: list[
            tuple[str, str, Decimal, int, Decimal, Decimal, str, str, int]
        ] = []
        missing: list[str] = []
        total_estimated_loss = ZERO
        account_currency = self.currency_var.get().strip().upper()

        for row_id, allocation_result in self.allocation_results.items():
            allocation = allocation_result.allocation
            quote_data = self.quotes.get(row_id)
            contract = self._contract_inputs_for_allocation(row_id)
            if quote_data is None:
                missing.append(f"{allocation.index}: Yahoo price not loaded")
                continue

            required = (
                "point_value",
                "point_size",
                "lot_increment",
                "minimum_lot",
            )
            missing_fields = [key for key in required if not contract.get(key)]
            if step_type == "enum_fixed_pips" and not contract.get("points_per_pip"):
                missing_fields.append("points_per_pip")
            if missing_fields:
                missing.append(
                    f"{allocation.index}: missing MT5 "
                    + ", ".join(missing_fields)
                )
                continue

            contract_currency = contract.get("contract_currency", "").strip().upper()
            if not contract_currency:
                missing.append(f"{allocation.index}: missing point-value currency")
                continue
            if account_currency and contract_currency != account_currency:
                missing.append(
                    f"{allocation.index}: point-value currency {contract_currency} "
                    f"does not match account currency {account_currency}"
                )
                continue

            try:
                point_value = decimal_value(
                    contract["point_value"], f"{allocation.index} point value"
                )
                point_size = decimal_value(
                    contract["point_size"], f"{allocation.index} point size"
                )
                lot_increment = decimal_value(
                    contract["lot_increment"], f"{allocation.index} lot step"
                )
                minimum_lot = decimal_value(
                    contract["minimum_lot"], f"{allocation.index} minimum lot"
                )
            except ValueError as error:
                missing.append(f"{allocation.index}: invalid MT5 contract ({error})")
                continue
            if min(point_value, point_size, lot_increment, minimum_lot) <= ZERO:
                missing.append(
                    f"{allocation.index}: MT5 point/volume specifications must be positive"
                )
                continue
            market_price = (
                decimal_value(self.reference_price_var.get(), "Reference price")
                if row_id == selected_row
                else quote_data[0]
            )
            row_stress_percent = stress_percent
            history = self.historical_stresses.get(row_id)
            observed_date = ""
            history_bars = 0
            if historical_mode:
                if history is None:
                    missing.append(
                        f"{allocation.index}: Yahoo 5-year daily history not loaded"
                    )
                    continue
                row_stress_percent = (
                    history.long_adverse_pct if is_long else history.short_adverse_pct
                )
                observed_date = (
                    history.long_observed_date if is_long else history.short_observed_date
                )
                history_bars = history.bar_count
                if not ZERO < row_stress_percent < ONE_HUNDRED:
                    missing.append(
                        f"{allocation.index}: historical adverse range is at least 100%"
                    )
                    continue
            if step_type == "enum_fixed_pips":
                points_per_pip = decimal_value(
                    contract["points_per_pip"], f"{allocation.index} points per pip"
                )
                grid_step_points = step_value * points_per_pip
            else:
                grid_step_points = (
                    market_price * step_value / ONE_HUNDRED / point_size
                )
            stress_points = (
                market_price * row_stress_percent / ONE_HUNDRED / point_size
            )
            row_max_trades = max_trades
            if historical_mode:
                try:
                    recommendation = suggest_safe_grid_settings(
                        stress_points=stress_points,
                        step_points=grid_step_points,
                        point_value_per_lot=point_value,
                        daily_budget=allocation_result.daily_loss_budget,
                        lot_step=lot_increment,
                        minimum_lot=minimum_lot,
                    )
                except ValueError as error:
                    missing.append(
                        f"{allocation.index}: no safe MT5 lot/Max Trades combination "
                        f"({error})"
                    )
                    continue
                row_max_trades = recommendation.max_trades
                effective_lot = recommendation.initial_lot
                loss = recommendation.estimated_loss
                below_minimum = False
            else:
                unit_stress = calculate_grid_stress(
                    initial_lot=ONE,
                    point_value_per_lot=point_value,
                    step_points=grid_step_points,
                    multiplier=ONE,
                    max_trades=row_max_trades,
                    stress_points=stress_points,
                    daily_budget=allocation_result.daily_loss_budget,
                )
                proposed_lot = (
                    (unit_stress.recommended_max_lot / lot_increment)
                    .to_integral_value(rounding=ROUND_FLOOR)
                    * lot_increment
                )
                below_minimum = proposed_lot < minimum_lot
                effective_lot = minimum_lot if below_minimum else proposed_lot
                loss = calculate_grid_stress(
                    initial_lot=effective_lot,
                    point_value_per_lot=point_value,
                    step_points=grid_step_points,
                    multiplier=ONE,
                    max_trades=row_max_trades,
                    stress_points=stress_points,
                    daily_budget=allocation_result.daily_loss_budget,
                ).estimated_loss
            total_estimated_loss += loss
            status = "MIN LOT EXCEEDS BUDGET" if below_minimum else "within allowance"
            rows.append(
                (
                    allocation.index,
                    allocation.robot,
                    row_stress_percent,
                    row_max_trades,
                    effective_lot,
                    loss,
                    status,
                    observed_date,
                    history_bars,
                )
            )

        allocated_daily_budget = sum(
            (item.daily_loss_budget for item in self.allocation_results.values()),
            ZERO,
        )
        (
            _account,
            daily_limit,
            remaining_daily_room,
            prop_loss_room,
            effective_cap,
        ) = self._portfolio_risk_limits()
        portfolio_working_allowance = allocated_daily_budget * Decimal("0.8")

        report = [
            "",
            (
                "PORTFOLIO SUGGESTION (each symbol's 5-year max; 1.0 multiplier)"
                if historical_mode
                else "PORTFOLIO STRESS (shared Step / Max Trades; 1.0 multiplier)"
            ),
            (
                "Uses each allocation's own largest adverse daily range from Yahoo 5y history."
                if historical_mode
                else "Applies the same adverse percentage to every loaded index."
            ),
        ]
        if historical_mode:
            report.append(
                "Combined as if every index reached its own worst downside session "
                "at the same time."
            )
        report.extend(
            [
                f"{'Symbol':<14} {'Robot':<6} {'Hist %':>8} {'MaxTr':>6} "
                f"{'Risk lots':>10} {'Loss':>12}  Result",
                "-" * 80,
            ]
        )
        for (
            symbol,
            robot,
            row_percent,
            row_trades,
            lot,
            loss,
            status,
            observed_date,
            history_bars,
        ) in rows:
            report.append(
                f"{symbol:<14.14} {robot:<6} {format_decimal(row_percent, 2):>8} "
                f"{row_trades:>6} {format_decimal(lot):>10} "
                f"{format_decimal(loss, 2):>12}  {status}"
            )
            if historical_mode:
                report.append(
                    f"  {history_bars} Yahoo daily bars; worst day: {observed_date}"
                )
        if rows:
            report.extend(
                [
                    "-" * 80,
                    f"{'Partial' if missing else 'Combined'} modeled loss: "
                    f"{format_decimal(total_estimated_loss, 2)} {currency} / "
                    f"80% allocated allowance {format_decimal(portfolio_working_allowance, 2)} "
                    f"{currency} / effective portfolio cap "
                    f"{format_decimal(effective_cap, 2)} {currency} / daily account "
                    f"limit {format_decimal(daily_limit, 2)} {currency}",
                ]
            )
            if prop_loss_room is not None:
                report.append(
                    f"Remaining prop overall-loss room: "
                    f"{format_decimal(prop_loss_room, 2)} {currency}"
                )
            else:
                report.append(
                    "Prop overall-loss rule is not applied; enter the remaining "
                    "total-loss room to include that account rule."
                )
            if remaining_daily_room is not None:
                report.append(
                    f"Remaining daily-loss room: "
                    f"{format_decimal(remaining_daily_room, 2)} {currency}"
                )
            else:
                report.append(
                    "Daily losses already incurred today are not deducted; enter "
                    "the remaining daily-loss room if today's loss is nonzero."
                )
            if not missing:
                if total_estimated_loss > daily_limit:
                    report.append("PORTFOLIO WARNING: modeled loss exceeds daily limit.")
                elif total_estimated_loss > portfolio_working_allowance:
                    report.append(
                        "PORTFOLIO WARNING: modeled loss exceeds the 20% safety-reserved "
                        "working allowance."
                    )
                else:
                    report.append(
                        "Portfolio modeled loss is within the safety-reserved allowance."
                    )
        if missing:
            report.append("Not included (missing data): " + "; ".join(missing))
        if not rows:
            report.append(
                "No combined estimate: import MT5 contract specifications and fetch "
                "Yahoo prices for the allocations."
            )
        report.append(
            (
                "Step Type/Value is shared from the selected row; verify it against "
                "each EA's actual configuration."
                if historical_mode
                else "Other robots use this row's Step Type/Value, Max Trades, and 1.0 "
                "multiplier for comparison; verify their actual EA settings."
            )
        )
        return report

    def _generate_settings_checked(
        self,
        show_errors: bool = True,
        require_complete_portfolio: bool = False,
    ) -> None:
        if not self._calculate_portfolio(show_error=show_errors):
            if require_complete_portfolio:
                raise ValueError(self.status_var.get())
            return
        if require_complete_portfolio and (
            self.stress_mode_var.get() != HISTORICAL_STRESS_MODE
            or self.position_direction_var.get() != "Long (price falls)"
        ):
            raise ValueError(
                "A full-portfolio suggestion requires the 5-year historical "
                "downward-move stress scenario."
            )
        row_id = self._selected_row_id()
        if row_id is None:
            raise ValueError("Select an allocation.")
        allocation_result = self.allocation_results[row_id]
        allocation = allocation_result.allocation
        contract = self._contract_inputs_for_allocation(row_id)
        for key, variable in self._contract_input_variables().items():
            if not variable.get().strip() and contract.get(key):
                variable.set(contract[key])
        required_contract_fields = {
            "point_value": "value of one point per lot",
            "point_size": "MT5 point size",
            "lot_increment": "broker lot increment",
            "minimum_lot": "broker minimum lot",
        }
        if self.step_type_var.get() == "Fixed pips":
            required_contract_fields["points_per_pip"] = "points per EA pip"
        if self.stress_mode_var.get() == HISTORICAL_STRESS_MODE:
            required_contract_fields["contract_currency"] = (
                "point-value currency (account currency)"
            )
        missing_contract_fields = [
            description
            for key, description in required_contract_fields.items()
            if not contract.get(key, "").strip()
        ]
        if missing_contract_fields:
            raise ValueError(
                f"Missing MT5 contract data for '{allocation.index}': "
                + ", ".join(missing_contract_fields)
                + ". Import the MT5 contract CSV and confirm it contains an exact "
                "or unambiguous row for this broker symbol."
            )
        if row_id not in self.quotes:
            raise ValueError(
                "Fetch the Yahoo Finance price and 5-year daily history for this allocation first."
            )
        price, quote_currency, yahoo_symbol, quote_time = self.quotes[row_id]
        price_in_account = decimal_value(
            self.reference_price_var.get(), "Yahoo reference price"
        )
        if price_in_account <= ZERO:
            raise ValueError("Yahoo reference price must be greater than zero.")

        point_value = decimal_value(
            contract["point_value"], f"{allocation.index} value of one point per lot"
        )
        point_size = decimal_value(
            contract["point_size"], f"{allocation.index} MT5 point size"
        )
        if point_value <= ZERO or point_size <= ZERO:
            raise ValueError("Point value and MT5 point size must be greater than zero.")
        step_value = decimal_value(self.step_value_var.get(), "Step Value")
        if step_value <= ZERO:
            raise ValueError("Step Value must be greater than zero.")

        if self.step_type_var.get() == "Fixed pips":
            points_per_pip = decimal_value(
                contract["points_per_pip"], f"{allocation.index} points per EA pip"
            )
            if points_per_pip <= ZERO:
                raise ValueError("Points per EA pip must be greater than zero.")
            step_points = step_value * points_per_pip
            step_type = "enum_fixed_pips"
        else:
            step_points = price_in_account * step_value / ONE_HUNDRED / point_size
            step_type = "Enum_percentage_pips"
        if step_points <= ZERO:
            raise ValueError("The converted step must be greater than zero.")

        is_long = self.position_direction_var.get() == "Long (price falls)"
        historical_stress = self.historical_stresses.get(row_id)
        historical_mode = self.stress_mode_var.get() == HISTORICAL_STRESS_MODE
        if self.stress_mode_var.get() == "Target price":
            target_price = decimal_value(
                self.stress_target_price_var.get(), "Stress target price"
            )
            adverse_difference = (
                price_in_account - target_price
                if is_long
                else target_price - price_in_account
            )
            if adverse_difference <= ZERO:
                direction = "below" if is_long else "above"
                raise ValueError(
                    f"For {self.position_direction_var.get()}, the stress target "
                    f"must be {direction} the current/reference price."
                )
            stress_points = adverse_difference / point_size
            stress_percent = adverse_difference * ONE_HUNDRED / price_in_account
        elif historical_mode:
            if historical_stress is None:
                raise ValueError(
                    "Fetch Yahoo's 5-year daily history for this allocation before "
                    "using historical stress settings."
                )
            stress_percent = (
                historical_stress.short_adverse_pct
                if not is_long
                else historical_stress.long_adverse_pct
            )
            if not ZERO < stress_percent < ONE_HUNDRED:
                raise ValueError(
                    "The historical adverse move is at least 100%; automatic settings "
                    "cannot model a valid positive target price for this symbol."
                )
            adverse_difference = price_in_account * stress_percent / ONE_HUNDRED
            stress_points = adverse_difference / point_size
            target_price = (
                price_in_account - adverse_difference
                if is_long
                else price_in_account + adverse_difference
            )
        else:
            stress_percent = decimal_value(
                self.stress_pct_var.get(), "Adverse stress move percent"
            )
            if not ZERO < stress_percent < ONE_HUNDRED:
                raise ValueError(
                    "Adverse stress move percent must be greater than 0 and less than 100."
                )
            adverse_difference = price_in_account * stress_percent / ONE_HUNDRED
            stress_points = adverse_difference / point_size
            target_price = (
                price_in_account - adverse_difference
                if is_long
                else price_in_account + adverse_difference
            )
        lot_increment = decimal_value(
            contract["lot_increment"], f"{allocation.index} broker lot increment"
        )
        minimum_lot = decimal_value(
            contract["minimum_lot"], f"{allocation.index} broker minimum lot"
        )
        if lot_increment <= ZERO or minimum_lot <= ZERO:
            raise ValueError("Broker lot increment and minimum lot must be greater than zero.")

        compare_count = positive_integer(
            self.compare_trades_var.get(), "Max Trades candidates"
        )
        if compare_count > 20:
            raise ValueError("Compare at most 20 Max Trades values.")
        if historical_mode:
            value_currency = contract["contract_currency"].strip().upper()
            account_currency = self.currency_var.get().strip().upper()
            if not value_currency or (
                account_currency and value_currency != account_currency
            ):
                raise ValueError(
                    "Historical risk suggestions need point value expressed in the "
                    "account currency. Import the MT5 contract CSV with account_currency."
                )
            suggestion = suggest_safe_grid_settings(
                stress_points=stress_points,
                step_points=step_points,
                point_value_per_lot=point_value,
                daily_budget=allocation_result.daily_loss_budget,
                lot_step=lot_increment,
                minimum_lot=minimum_lot,
            )
            selected_trades = suggestion.max_trades
            self.selected_trades_var.set(str(selected_trades))
            compare_count = max(compare_count, selected_trades)
        else:
            selected_trades = positive_integer(
                self.selected_trades_var.get(), "Max Trades to output"
            )
        if selected_trades > compare_count:
            raise ValueError("Selected Max Trades must be in the candidate range.")

        candidates: dict[int, tuple[Decimal, Decimal]] = {}
        for trades in range(1, compare_count + 1):
            calculation = calculate_grid_stress(
                initial_lot=ONE,
                point_value_per_lot=point_value,
                step_points=step_points,
                multiplier=ONE,
                max_trades=trades,
                stress_points=stress_points,
                daily_budget=allocation_result.daily_loss_budget,
            )
            lot = (
                (calculation.recommended_max_lot / lot_increment)
                .to_integral_value(rounding=ROUND_FLOOR)
                * lot_increment
            )
            loss = calculate_grid_stress(
                initial_lot=lot if lot >= minimum_lot else minimum_lot,
                point_value_per_lot=point_value,
                step_points=step_points,
                multiplier=ONE,
                max_trades=trades,
                stress_points=stress_points,
                daily_budget=allocation_result.daily_loss_budget,
            ).estimated_loss
            candidates[trades] = (lot, loss)

        selected_lot, selected_loss = candidates[selected_trades]
        if selected_lot < minimum_lot:
            raise ValueError(
                f"Max Trades {selected_trades} does not fit even the broker's "
                f"minimum lot ({format_decimal(minimum_lot)}). Choose fewer "
                "trades, reduce the stress scenario only if justified, or "
                "change the capital/risk allocation."
            )

        magic_number = positive_integer(self.magic_var.get(), "Magic Number")
        if magic_number > 2147483647:
            raise ValueError("Magic Number must not exceed 2147483647.")
        for other_row, assigned_magic in self.magic_assignments.items():
            if other_row != row_id and assigned_magic == magic_number:
                raise ValueError(
                    "Magic Number must be unique across configured robots."
                )
        take_profit_text = self.take_profit_value_var.get().strip()
        if take_profit_text:
            take_profit_value = decimal_value(take_profit_text, "Take Profit Value")
            if take_profit_value <= ZERO:
                raise ValueError("Take Profit Value must be greater than zero.")
            take_profit_output = format_decimal(take_profit_value)
        elif historical_mode:
            take_profit_output = "NOT DETERMINED - set and backtest manually"
        else:
            raise ValueError("Take Profit Value must be greater than zero.")
        take_profit_type = (
            "enum_fixed_pips"
            if self.take_profit_type_var.get() == "Fixed pips"
            else "Enum_percentage_pips"
        )

        robot = allocation.robot.upper()
        output = [
            f"SYMBOL / ROBOT: {allocation.index} / {robot}",
            f"Yahoo reference: {yahoo_symbol} = {format_decimal(price_in_account)} "
            f"{quote_currency} ({quote_time})",
            f"Tested adverse target: {format_decimal(target_price)} "
            f"({self.position_direction_var.get()})",
            f"Adverse move: {format_decimal(stress_percent, 2)}% = "
            f"{format_decimal(stress_points, 2)} MT5 points",
            f"Robot daily risk budget: "
            f"{format_decimal(allocation_result.daily_loss_budget, 2)} "
            f"{self.currency_var.get().strip() or 'account currency'}",
            f"Risk allowance used (80%): "
            f"{format_decimal(allocation_result.daily_loss_budget * Decimal('0.8'), 2)}",
            "",
            "MAX TRADES CANDIDATES (Multiplier Factor = 1.0)",
            f"{'Max Trades':>12} {'Risk Type':>14} {'Risk (lots)':>16}",
            "-" * 46,
        ]
        if historical_mode and historical_stress is not None:
            observed_date = (
                historical_stress.long_observed_date
                if is_long
                else historical_stress.short_observed_date
            )
            output.extend(
                [
                    (
                        "Historical basis: worst adverse daily High-Low / prior-close "
                        "move in Yahoo's 5-year daily history."
                    ),
                    f"Valid daily bars: {historical_stress.bar_count} "
                    f"({historical_stress.start_date} to {historical_stress.end_date})",
                    f"Worst {self.position_direction_var.get()} session: {observed_date}",
                    "Risk settings were sized with 1.0 multiplier and the 80% "
                    "allocation allowance.",
                    "",
                ]
            )
            if not take_profit_text:
                output.append(
                    "CONFIGURATION INCOMPLETE: set a strategy-specific Take Profit Value."
                )
                output.append("")
        for trades, (lot, loss) in candidates.items():
            risk_text = (
                f"NO FIT (min-lot loss {format_decimal(loss, 2)})"
                if lot < minimum_lot
                else format_decimal(lot)
            )
            output.append(f"{trades:>12} {'Fixed lots':>14} {risk_text:>16}")

        output.extend(
            [
                "",
                f"SELECTED {robot} EA SETTINGS",
                f"Magic Number: {magic_number}",
                f"Max Trades: {selected_trades}",
                f"Step Type: {step_type}",
                f"Step Value: {format_decimal(step_value)}",
                f"Take Profit Type: {take_profit_type}",
                f"Take Profit Value: {take_profit_output}",
                "Risk Type: Fixed lots",
                f"Risk: {format_decimal(selected_lot)}",
                "Multiplier Factor: 1.0",
            ]
        )

        if robot == "DCA":
            enabled = self.entry_break_var.get()
            ref_text = self.reference_price_var.get().strip()
            if enabled:
                if not ref_text:
                    ref_text = format_decimal(price_in_account)
                reference_price = decimal_value(ref_text, "DCA reference price")
                if reference_price <= ZERO:
                    raise ValueError("DCA reference price must be greater than zero.")
            else:
                reference_price = ZERO
            output.extend(
                [
                    f"Entry on price break: {str(enabled).lower()}",
                    f"InpPriceBreakType: {self.price_break_type_var.get()}",
                    f"Reference Price: {format_decimal(reference_price)}",
                    f"Trade on new candle: {str(self.trade_new_candle_var.get()).lower()}",
                    f"Show Invested Money: {str(self.show_dca_invested_var.get()).lower()}",
                ]
            )
        else:
            oversold = decimal_value(self.rsi_oversold_var.get(), "RSI oversold")
            overbought = decimal_value(self.rsi_overbought_var.get(), "RSI Overbought")
            period = positive_integer(self.rsi_period_var.get(), "RSI Period")
            if not ZERO < oversold < overbought < Decimal("100"):
                raise ValueError(
                    "RSI levels must satisfy 0 < oversold < overbought < 100."
                )
            output.extend(
                [
                    f"Close When Overbought: {str(self.close_overbought_var.get()).lower()}",
                    f"RSI oversold: {format_decimal(oversold)}",
                    f"RSI Overbought: {format_decimal(overbought)}",
                    f"RSI Period: {period}",
                    f"Show Invested Money: {str(self.show_rsi_invested_var.get()).lower()}",
                ]
            )

        output.extend(
            [
                "",
                f"Estimated loss at selected settings: "
                f"{format_decimal(selected_loss, 2)} "
                f"{self.currency_var.get().strip() or 'account currency'}",
            ]
        )
        portfolio_report = self._portfolio_stress_report(
            row_id,
            step_type,
            step_value,
            stress_percent,
            selected_trades,
        )
        if require_complete_portfolio:
            missing_report = next(
                (
                    line
                    for line in portfolio_report
                    if line.startswith("Not included (missing data):")
                ),
                None,
            )
            if missing_report:
                raise ValueError(
                    "Cannot model every allocation. " + missing_report
                )
            if not any(
                line == "Portfolio modeled loss is within the safety-reserved allowance."
                for line in portfolio_report
            ):
                raise ValueError(
                    "The combined modeled loss does not fit the portfolio's "
                    "safety-reserved allowance."
                )
        output.extend(portfolio_report)
        output.extend(
            [
                "",
                "IMPORTANT:",
                "- The step and take-profit values are strategy choices, not values "
                "derived from the daily drawdown limit.",
                "- Yahoo prices are references; an index quote may differ from the "
                "broker's CFD and may be delayed.",
                "- Point value and volume rules must match the MT5 broker contract.",
                "- This tests only the entered adverse move. Gaps, slippage, costs, "
                "or a larger move can exceed the daily limit.",
                "- The suggested target price is a stress-test input, not a price "
                "forecast.",
                "- A historical maximum is not a future loss ceiling; broker CFD "
                "prices and execution can differ from Yahoo data.",
                "- Take Profit and RSI/DCA signal values are strategy choices and "
                "are not inferred from historical drawdown.",
                "- Use an EA/account-level daily equity stop that blocks new trades "
                "and closes positions to enforce a loss limit.",
                "- Fixed-lot Risk assumes the EA parameter means the first-entry lot.",
                (
                    "- This full-portfolio suggestion includes all configured "
                    "allocations, models a downward move, and caps modeled loss at "
                    "80% of the tighter configured portfolio risk limit."
                    if require_complete_portfolio
                    else ""
                ),
            ]
        )

        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", "\n".join(output))
        self.magic_assignments[row_id] = magic_number
        self.status_var.set(
            f"Settings generated for {allocation.index} / {robot}; review broker units."
        )

    def _copy_output(self) -> None:
        content = self.output_text.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo(
                "Nothing to copy",
                "Generate settings first.",
                parent=self,
            )
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_var.set("Settings copied to clipboard.")


if __name__ == "__main__":
    RiskCalculatorApp().mainloop()
