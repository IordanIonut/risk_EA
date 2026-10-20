"""Desktop MT5 risk planner with broker CSV history and Yahoo fallback."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import importlib
import io
import json
from html.parser import HTMLParser
import os
import queue
import re
from string import Formatter
import tempfile
import threading
from typing import TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlsplit
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from advanced_risk import (
    EquitySample, ExposureInputs, ModeledExposure, check_exposures,
    default_exposure, default_profile, evaluate_equity_curve, parse_equity_csv,
    remaining_rooms, validate_exposure, validate_profile,
)

from risk_calculator import (
    Allocation,
    AllocationResult,
    DailyBar,
    HistoricalStress,
    ONE,
    ONE_HUNDRED,
    ZERO,
    backtest_historical_grid_campaign,
    calculate_historical_stress,
    calculate_grid_stress,
    calculate_portfolio,
    effective_portfolio_risk_cap,
    replay_historical_grid,
    suggest_safe_grid_settings,
    suggest_safe_grid_settings_from_history,
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

APP_DATA_DIRECTORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
)
AUTOSAVE_FILE_NAME = "portfolio.json"
BROKER_API_CONFIG_FILE_NAME = "broker_api_config.json"
LEGACY_AUTOSAVE_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "MT5RiskPlanner",
    AUTOSAVE_FILE_NAME,
)

QuoteData = tuple[Decimal, str, str, str]
ContractFields = dict[str, str]
HISTORICAL_STRESS_MODE = "Historical max daily range (MT5 / Yahoo fallback)"
HISTORICAL_DRAWDOWN_MODE = "Historical peak-to-trough drawdown (MT5 / Yahoo fallback)"
HISTORICAL_STRESS_MODES = (
    HISTORICAL_STRESS_MODE,
    HISTORICAL_DRAWDOWN_MODE,
)
MT5_HISTORY_SOURCES = ("MT5 CSV", "MT5 terminal")
BROKER_HISTORY_SOURCES = (*MT5_HISTORY_SOURCES, "Broker API")
LEGACY_HISTORICAL_STRESS_MODE = "Yahoo 5-year max daily range"
PROP_WEBSITE_FILE_NAME = "prop_website.json"


class PropRuleCandidate(TypedDict):
    stage: str
    daily_percent: str
    total_percent: str
    evidence: str


class PropWebsiteSnapshot(TypedDict):
    source: str
    fetched_at: str
    candidates: list[PropRuleCandidate]


class PropWebsiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] | None = None
        self.hidden_depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in ("script", "style"):
            self.hidden_depth += 1
        if self.hidden_depth:
            return
        if tag == "table":
            self.rows.append([])
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.hidden_depth:
            self.hidden_depth -= 1
        if self.hidden_depth:
            return
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def extract_prop_website_rules(html: str) -> list[PropRuleCandidate]:
    parser = PropWebsiteParser()
    parser.feed(html)
    headers: list[str] = []
    candidates: list[PropRuleCandidate] = []
    number = r"(\d+(?:[.,]\d+)?)\s*%"

    def percent(text: str) -> str:
        matches = re.findall(number, text)
        return matches[0].replace(",", ".") if len(matches) == 1 else ""

    for row in parser.rows:
        if not row:
            headers = []
            continue
        lower = [cell.lower() for cell in row]
        if any("daily" in cell for cell in lower) and not any(
            re.search(number, cell) for cell in row
        ):
            headers = lower
            continue
        daily_values: set[str] = set()
        total_values: set[str] = set()
        for index, cell in enumerate(row):
            header = headers[index] if index < len(headers) else ""
            if "daily" in header and "total" not in header:
                daily_values.add(percent(cell))
            if any(word in header for word in ("total", "overall", "maximum loss")) and "daily" not in header:
                total_values.add(percent(cell))
            daily_values.update(
                match.replace(",", ".")
                for match in re.findall(number + r"\s*(?:daily|per day)\b", cell, re.I)
            )
            total_values.update(
                match.replace(",", ".")
                for match in re.findall(number + r"\s*(?:total|overall)\b", cell, re.I)
            )
        if len(daily_values) != 1 or len(total_values) != 1:
            continue
        daily = next(iter(daily_values))
        total = next(iter(total_values))
        if daily and total and ZERO < Decimal(daily) <= Decimal(total) < ONE_HUNDRED:
            candidates.append({
                "stage": row[0][:200],
                "daily_percent": daily,
                "total_percent": total,
                "evidence": " | ".join(row)[:2000],
            })
    return candidates[:100]


def fetch_prop_website(url: str) -> PropWebsiteSnapshot:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username or parsed.password or parsed.fragment
    ):
        raise ValueError("Use a public HTTPS program URL without credentials or fragments.")
    request = Request(
        url.strip(), headers={"User-Agent": "MT5RiskPlanner/1.0", "Accept": "text/html"}
    )
    try:
        with urlopen(request, timeout=30) as response:
            if urlsplit(response.geturl()).scheme != "https":
                raise ValueError("The program website redirected to a non-HTTPS URL.")
            body = response.read(2 * 1024 * 1024 + 1)
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("Program page exceeds the 2 MiB download limit.")
        html = body.decode(charset)
    except HTTPError as error:
        raise ValueError(f"Program website returned HTTP {error.code}.") from error
    except (URLError, OSError, UnicodeError, LookupError) as error:
        raise ValueError(f"Could not read the program website: {error}") from error
    candidates = extract_prop_website_rules(html)
    if not candidates:
        raise ValueError(
            "No unambiguous daily/total percentage pairs were found in HTML tables. "
            "JavaScript-only pages, PDFs, vertical tables and other languages may "
            "require manual entry. Existing account values were not changed."
        )
    return {
        "source": final_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "candidates": candidates,
    }


SPICEPROP_SWEET_REFERENCE = {
    "program": "SpiceProp Sweet / Spice 2 Step",
    "verified_on": "2026-10-20",
    "source": "https://spiceprop.com/programs/sweet",
    "rules_source": (
        "https://spiceprop.com/qa/902-what-are-the-main-account-objectives-and-rules"
    ),
    "currency": "EUR",
    "account_sizes": (6000, 10000, 25000, 50000, 100000, 150000),
    "phases": (
        ("Phase 1", "5.5", "11", "7.5"),
        ("Phase 2", "4.5", "11", "5"),
        ("Funded", "4.5", "11", None),
    ),
    "funded_idea_risk_percent": "2",
}


def historical_stress_move(
    stress: HistoricalStress,
    mode: str,
    is_long: bool,
) -> Decimal:
    if mode == HISTORICAL_DRAWDOWN_MODE:
        return stress.long_drawdown_pct if is_long else stress.short_rally_pct
    return stress.long_adverse_pct if is_long else stress.short_adverse_pct


def historical_stress_period(
    stress: HistoricalStress,
    mode: str,
    is_long: bool,
) -> str:
    if mode == HISTORICAL_DRAWDOWN_MODE:
        start_date, end_date = (
            (stress.long_drawdown_peak_date, stress.long_drawdown_trough_date)
            if is_long
            else (stress.short_rally_trough_date, stress.short_rally_peak_date)
        )
        return f"{start_date} to {end_date}" if start_date and end_date else ""
    return stress.long_observed_date if is_long else stress.short_observed_date


def historical_spread_floor(
    bars: tuple[DailyBar, ...],
    configured_spread_points: Decimal,
) -> Decimal:
    return max(
        configured_spread_points,
        max(
            (
                bar.spread_points
                for bar in bars
                if bar.spread_points is not None
            ),
            default=ZERO,
        ),
    )


@dataclass(frozen=True)
class YahooDataResult:
    row_id: str
    quote: QuoteData | None
    history: HistoricalStress | None
    error: str | None


@dataclass(frozen=True)
class MT5SymbolData:
    contract: ContractFields
    bars: tuple[DailyBar, ...]
    quote: QuoteData
    timeframe_charts: dict[str, list[dict[str, str]]] | None = None


@dataclass(frozen=True)
class MT5PortfolioResult:
    rows: dict[str, MT5SymbolData]
    account_currency: str
    error: str | None = None


@dataclass(frozen=True)
class MT5InspectionResult:
    connection: dict[str, str]
    error: str = ""


def history_quality_warnings(
    stress: HistoricalStress, now: datetime | None = None
) -> tuple[str, ...]:
    today = (now or datetime.now(timezone.utc)).date()
    try:
        expected_start = today.replace(year=today.year - 5)
    except ValueError:
        expected_start = today.replace(year=today.year - 5, day=28)
    first = datetime.strptime(stress.start_date, "%Y-%m-%d").date()
    last = datetime.strptime(stress.end_date, "%Y-%m-%d").date()
    warnings = []
    if first > expected_start + timedelta(days=14):
        warnings.append("History covers less than the requested five-year window.")
    if last < today - timedelta(days=7):
        warnings.append("History is stale: last daily bar is more than 7 days old.")
    if last > today:
        warnings.append("History contains future-dated bars.")
    if stress.bar_count < 1000:
        warnings.append("Fewer than 1000 daily bars: five-year sample is too sparse.")
    return tuple(warnings)


def merge_refreshed_contract(
    previous: ContractFields, incoming: ContractFields
) -> tuple[ContractFields, bool]:
    merged = dict(incoming)
    fields = (
        "contract_currency", "point_size", "point_value", "lot_increment",
        "minimum_lot", "maximum_lot",
    )
    matching = True
    for field in fields:
        old = previous.get(field, "").strip()
        new = incoming.get(field, "").strip()
        if field == "contract_currency":
            equal = old.upper() == new.upper()
        elif old and new:
            try:
                equal = decimal_value(old, field) == decimal_value(new, field)
            except ValueError:
                equal = False
        else:
            equal = old == new
        matching = matching and equal
    review_required = False
    for field in ("points_per_pip", "commission_per_lot"):
        if not incoming.get(field) and previous.get(field):
            if matching:
                merged[field] = previous[field]
            else:
                review_required = True
    return merged, review_required


def connect_mt5(
    mt5_module: object | None = None, terminal_path: str = ""
) -> tuple[object, bool]:
    if mt5_module is None:
        try:
            mt5_module = importlib.import_module("MetaTrader5")
        except ImportError as error:
            raise ValueError(
                "The MetaTrader5 Python package is not installed. Install it in "
                "the same Python environment with `py -m pip install MetaTrader5`, "
                "then open and log in to the MT5 terminal."
            ) from error

    mt5 = mt5_module
    terminal_was_initialized = getattr(mt5, "terminal_info")() is not None
    if terminal_path:
        initialized = getattr(mt5, "initialize")(terminal_path)
    else:
        initialized = terminal_was_initialized or getattr(mt5, "initialize")()
    if not initialized:
        raise ValueError(
            f"Could not connect to the MT5 terminal: {getattr(mt5, 'last_error')()}."
        )
    return mt5, bool(terminal_path) or not terminal_was_initialized


def inspect_mt5_terminal(
    terminal_path: str = "", mt5_module: object | None = None,
    requested_symbols: tuple[str, ...] = (),
) -> dict[str, str]:
    mt5, owns_connection = connect_mt5(mt5_module, terminal_path)
    try:
        terminal = getattr(mt5, "terminal_info")()
        account = getattr(mt5, "account_info")()
        if terminal is None or account is None:
            raise ValueError("MT5 terminal/account information is unavailable. Log in first.")
        symbols = getattr(mt5, "symbols_get")()
        if symbols is None:
            raise ValueError(f"MT5 symbol list unavailable: {getattr(mt5, 'last_error')()}.")
        available_timeframes = sorted(
            {
                constant_name.removeprefix("TIMEFRAME_")
                for constant_name in dir(mt5)
                if constant_name.startswith("TIMEFRAME_")
                and isinstance(getattr(mt5, constant_name, None), int)
                and not isinstance(getattr(mt5, constant_name, None), bool)
                and getattr(mt5, constant_name, 0) > 0
            }
        )
        account_currency = str(getattr(account, "currency", "") or "")
        symbol_catalog = []
        symbol_info = getattr(mt5, "symbol_info", lambda _symbol: None)
        symbol_info_tick = getattr(mt5, "symbol_info_tick", lambda _symbol: None)
        for item in symbols:
            name = str(getattr(item, "name", "") or "").strip()
            if not name:
                continue
            metadata: dict[str, object] = {
                "symbol": name,
                "available_in_mt5": True,
                "available_timeframes": available_timeframes,
            }
            info = symbol_info(name)
            if info is not None:
                for field, attribute in (
                    ("description", "description"),
                    ("path", "path"),
                    ("digits", "digits"),
                    ("point_size", "point"),
                    ("tick_size", "trade_tick_size"),
                    ("volume_min", "volume_min"),
                    ("volume_step", "volume_step"),
                    ("volume_max", "volume_max"),
                ):
                    value = getattr(info, attribute, None)
                    if value is not None:
                        metadata[field] = str(value)
                metadata["contract_currency"] = account_currency
                try:
                    point_size = Decimal(str(getattr(info, "point", "0")))
                    tick_size = Decimal(str(getattr(info, "trade_tick_size", "0")))
                    tick_value = Decimal(
                        str(
                            getattr(info, "trade_tick_value_profit", 0)
                            or getattr(info, "trade_tick_value", 0)
                        )
                    )
                    if min(point_size, tick_size, tick_value) > ZERO:
                        metadata["point_value"] = str(
                            tick_value * point_size / tick_size
                        )
                except (InvalidOperation, TypeError, ValueError):
                    pass
            tick = symbol_info_tick(name)
            if tick is not None:
                for field, attribute in (
                    ("bid", "bid"), ("ask", "ask"), ("last", "last"),
                    ("quote_time", "time"),
                ):
                    value = getattr(tick, attribute, None)
                    if value is not None:
                        metadata[field] = str(value)
            symbol_catalog.append(metadata)
        mode = getattr(account, "trade_mode", None)
        modes = {
            getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0): "DEMO",
            getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1): "CONTEST",
            getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2): "REAL",
        }
        risk_details = []
        for symbol in dict.fromkeys(requested_symbols):
            if not getattr(mt5, "symbol_select")(symbol, True):
                risk_details.append(
                    f"WARNING: MT5 could not select {symbol}; choose an exact symbol "
                    "from the returned broker list before fetching specs/margin."
                )
                continue
            info = getattr(mt5, "symbol_info")(symbol)
            tick = getattr(mt5, "symbol_info_tick")(symbol)
            if info is None or tick is None:
                risk_details.append(f"WARNING: MT5 has no live contract/tick for {symbol}.")
                continue
            volume = Decimal(str(getattr(info, "volume_min", 0)))
            ask = Decimal(str(getattr(tick, "ask", 0)))
            bid = Decimal(str(getattr(tick, "bid", 0)))
            if any(not value.is_finite() or value <= ZERO for value in (volume, ask, bid)):
                risk_details.append(f"WARNING: invalid MT5 live quote/minimum volume for {symbol}.")
                continue
            margins = []
            for side, price in (("BUY", ask), ("SELL", bid)):
                margin = getattr(mt5, "order_calc_margin")(
                    getattr(mt5, f"ORDER_TYPE_{side}"), symbol, float(volume), float(price)
                )
                if margin is None:
                    margins.append(
                        f"WARNING: {side} margin unavailable: {getattr(mt5, 'last_error')()}"
                    )
                    continue
                value = Decimal(str(margin))
                if not value.is_finite() or value < ZERO:
                    margins.append(f"WARNING: invalid {side} margin returned by MT5")
                    continue
                margins.append(f"{side} margin/lot estimate={value / volume}")
            risk_details.append(
                f"{symbol}: " + "; ".join(margins)
                + f"; raw swap_long={getattr(info, 'swap_long', 'unavailable')}"
                + f"; raw swap_short={getattr(info, 'swap_short', 'unavailable')}"
                + f"; swap_mode={getattr(info, 'swap_mode', 'unavailable')}"
                + f"; triple-day enum={getattr(info, 'swap_rollover3days', 'unavailable')}"
                + f"; point={getattr(info, 'point', 'unavailable')}. "
                "Margin estimates use current prices and minimum volume, in account cash; "
                "verify worst-price/volume tiers before copying a conservative per-lot bound. "
                "Raw swaps are NOT normalized cash: verify swap mode, currency, points "
                "and charge-day weights before entering debit/lot/charge-day."
            )
        return {
            "terminal_path": str(getattr(terminal, "path", "")),
            "connected": str(getattr(terminal, "connected", False)),
            "broker": str(getattr(account, "company", "")),
            "server": str(getattr(account, "server", "")),
            "account_type": modes.get(mode, "UNKNOWN"),
            "currency": str(getattr(account, "currency", "")),
            "leverage": str(getattr(account, "leverage", "")),
            "free_margin": str(getattr(account, "margin_free", "")),
            "equity": str(getattr(account, "equity", "")),
            "used_margin": str(getattr(account, "margin", "")),
            "stopout_mode": str(getattr(account, "margin_so_mode", "")),
            "stopout_level": str(getattr(account, "margin_so_so", "")),
            "risk_details": "\n".join(risk_details),
            "symbol_catalog": json.dumps(symbol_catalog, ensure_ascii=False),
            "symbols": "\n".join(sorted(
                str(getattr(symbol, "name", "")) for symbol in symbols
                if getattr(symbol, "name", "")
            )),
        }
    finally:
        if owns_connection:
            getattr(mt5, "shutdown")()


def fetch_mt5_terminal_data(
    symbols: list[str],
    history_years: int = 5,
    mt5_module: object | None = None,
    terminal_path: str = "",
    include_timeframes: bool = False,
) -> tuple[str, dict[str, MT5SymbolData]]:
    if (
        isinstance(history_years, bool)
        or not isinstance(history_years, int)
        or history_years <= 0
    ):
        raise ValueError("MT5 history years must be a positive integer.")
    mt5, owns_connection = connect_mt5(mt5_module, terminal_path)

    try:
        account = getattr(mt5, "account_info")()
        account_currency = str(getattr(account, "currency", "") or "").strip().upper()
        if account is None or not account_currency:
            raise ValueError(
                "MT5 account information is unavailable or has no account currency. "
                "Log in to the broker account in the terminal."
            )

        now = datetime.now(timezone.utc)
        try:
            start = now.replace(year=now.year - history_years)
        except ValueError:
            start = now.replace(year=now.year - history_years, day=28)
        timeframe = getattr(mt5, "TIMEFRAME_D1")
        result: dict[str, MT5SymbolData] = {}
        for symbol in dict.fromkeys(item.strip() for item in symbols if item.strip()):
            if not getattr(mt5, "symbol_select")(symbol, True):
                raise ValueError(
                    f"MT5 could not select symbol '{symbol}' in Market Watch."
                )
            info = getattr(mt5, "symbol_info")(symbol)
            if info is None:
                raise ValueError(f"MT5 has no contract information for '{symbol}'.")

            point = Decimal(str(getattr(info, "point", "0")))
            tick_size = Decimal(str(getattr(info, "trade_tick_size", "0")))
            tick_value = Decimal(
                str(
                    getattr(info, "trade_tick_value_profit", 0)
                    or getattr(info, "trade_tick_value", 0)
                )
            )
            volume_step = Decimal(str(getattr(info, "volume_step", "0")))
            volume_min = Decimal(str(getattr(info, "volume_min", "0")))
            if (
                not point.is_finite()
                or not tick_size.is_finite()
                or not tick_value.is_finite()
                or point <= ZERO
                or tick_size <= ZERO
                or tick_value <= ZERO
                or volume_step <= ZERO
                or volume_min <= ZERO
            ):
                raise ValueError(
                    f"MT5 returned incomplete or invalid point/tick/volume data "
                    f"for '{symbol}'."
                )
            point_value = tick_value * point / tick_size
            volume_max = Decimal(str(getattr(info, "volume_max", "0")))
            contract: ContractFields = {
                "point_value": str(point_value),
                "point_size": str(point),
                "points_per_pip": "",
                "lot_increment": str(volume_step),
                "minimum_lot": str(volume_min),
                "maximum_lot": str(volume_max) if volume_max > ZERO else "",
                "commission_per_lot": "",
                "contract_currency": account_currency,
            }

            rates = getattr(mt5, "copy_rates_range")(
                symbol, timeframe, start, now
            )
            if rates is None or len(rates) < 20:
                last_error = getattr(mt5, "last_error")()
                raise ValueError(
                    f"MT5 returned fewer than 20 daily bars for '{symbol}' "
                    f"over the last {history_years} years ({last_error})."
                )
            bars: list[DailyBar] = []
            for rate in rates:
                try:
                    timestamp = int(rate["time"])
                    bar_date = datetime.fromtimestamp(
                        timestamp, timezone.utc
                    ).date().isoformat()
                    bar = DailyBar(
                        date=bar_date,
                        open=Decimal(str(rate["open"])),
                        high=Decimal(str(rate["high"])),
                        low=Decimal(str(rate["low"])),
                        close=Decimal(str(rate["close"])),
                        spread_points=(
                            Decimal(str(rate["spread"]))
                            if "spread"
                            in getattr(getattr(rate, "dtype", None), "names", ())
                            else None
                        ),
                    )
                except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
                    raise ValueError(
                        f"MT5 returned a malformed daily bar for '{symbol}'."
                    ) from error
                bars.append(bar)
            bars_tuple = tuple(bars)
            calculate_historical_stress(bars_tuple)

            timeframe_charts: dict[str, list[dict[str, str]]] = {}
            timeframe_values: dict[int, str] = {}
            for constant_name in dir(mt5) if include_timeframes else ():
                if not constant_name.startswith("TIMEFRAME_"):
                    continue
                value = getattr(mt5, constant_name, None)
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    continue
                timeframe_values.setdefault(
                    value, constant_name.removeprefix("TIMEFRAME_")
                )
            copy_rates_from_pos = getattr(mt5, "copy_rates_from_pos", None)
            for timeframe_value, timeframe_name in sorted(timeframe_values.items()):
                if timeframe_name == "D1":
                    timeframe_rates = rates
                elif callable(copy_rates_from_pos):
                    try:
                        timeframe_rates = copy_rates_from_pos(
                            symbol, timeframe_value, 0, 1000
                        )
                    except (TypeError, ValueError, RuntimeError):
                        continue
                    if timeframe_rates is None or len(timeframe_rates) == 0:
                        continue
                else:
                    continue
                chart_bars: list[dict[str, str]] = []
                for rate in timeframe_rates:
                    try:
                        timestamp = int(rate["time"])
                        chart_bar = {
                            "time": datetime.fromtimestamp(
                                timestamp, timezone.utc
                            ).isoformat().replace("+00:00", "Z"),
                            "open": str(rate["open"]),
                            "high": str(rate["high"]),
                            "low": str(rate["low"]),
                            "close": str(rate["close"]),
                        }
                        field_names = getattr(
                            getattr(rate, "dtype", None), "names", ()
                        )
                        for optional_field in (
                            "tick_volume", "spread", "real_volume"
                        ):
                            if optional_field in field_names:
                                chart_bar[optional_field] = str(
                                    rate[optional_field]
                                )
                    except (
                        KeyError, TypeError, ValueError, OverflowError
                    ):
                        continue
                    chart_bars.append(chart_bar)
                if chart_bars:
                    timeframe_charts[timeframe_name] = chart_bars

            tick = getattr(mt5, "symbol_info_tick")(symbol)
            ask = Decimal(str(getattr(tick, "ask", "0") or "0"))
            bid = Decimal(str(getattr(tick, "bid", "0") or "0"))
            if ask.is_finite() and ask > ZERO:
                market_price = ask
            elif bid.is_finite() and bid > ZERO:
                market_price = bid
            else:
                market_price = bars_tuple[-1].close
            tick_time = getattr(tick, "time", None)
            quote_time = (
                datetime.fromtimestamp(int(tick_time), timezone.utc)
                .astimezone()
                .strftime("%Y-%m-%d %H:%M")
                if tick_time
                else f"{bars_tuple[-1].date} (last MT5 D1 close)"
            )
            result[symbol.strip().upper()] = MT5SymbolData(
                contract=contract,
                bars=bars_tuple,
                quote=(
                    market_price,
                    str(getattr(info, "currency_profit", "") or account_currency),
                    symbol,
                    quote_time,
                ),
                timeframe_charts=timeframe_charts,
            )
        if not result:
            raise ValueError("No MT5 broker symbols were selected for data fetch.")
        return account_currency, result
    finally:
        if owns_connection:
            getattr(mt5, "shutdown")()


def fetch_broker_api_data(
    endpoint_template: str,
    api_token: str,
    symbols: list[str],
    timeout: int = 30,
) -> tuple[str, dict[str, MT5SymbolData]]:
    validate_broker_api_endpoint(endpoint_template)
    if not symbols:
        raise ValueError("Select at least one broker symbol for the API request.")

    now = datetime.now(timezone.utc)
    try:
        history_start = now.replace(year=now.year - 5)
    except ValueError:
        history_start = now.replace(year=now.year - 5, day=28)
    placeholders = {
        "symbol": "",
        "start": history_start.date().isoformat(),
        "end": now.date().isoformat(),
        "interval": "1d",
    }
    account_currency = ""
    results: dict[str, MT5SymbolData] = {}
    for requested_symbol in symbols:
        symbol = requested_symbol.strip()
        if not symbol:
            raise ValueError("Broker API symbol names cannot be blank.")
        request_url = endpoint_template.strip().format(
            symbol=quote(symbol, safe=""),
            start=placeholders["start"],
            end=placeholders["end"],
            interval=placeholders["interval"],
        )
        headers = {"Accept": "application/json"}
        if api_token.strip():
            headers["Authorization"] = f"Bearer {api_token.strip()}"
        request = Request(request_url, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                response_body = response.read(50 * 1024 * 1024 + 1)
            if len(response_body) > 50 * 1024 * 1024:
                raise ValueError("Broker API response exceeds the 50 MiB limit.")
            payload = json.loads(response_body.decode("utf-8"))
            symbol_data = _parse_broker_api_symbol_data(payload, symbol)
        except HTTPError as error:
            raise ValueError(
                f"Broker API returned HTTP {error.code} for {symbol}."
            ) from error
        except (URLError, OSError, TimeoutError) as error:
            raise ValueError(f"Broker API request failed for {symbol}: {error}") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                f"Broker API returned invalid UTF-8 or JSON for {symbol}."
            ) from error
        except (KeyError, TypeError, InvalidOperation, OverflowError) as error:
            raise ValueError(
                f"Broker API response is invalid for {symbol}: {error}"
            ) from error
        response_currency = symbol_data.contract["contract_currency"]
        if not account_currency:
            account_currency = response_currency
        elif response_currency != account_currency:
            raise ValueError(
                "Broker API responses returned inconsistent account currencies."
            )
        results[symbol.upper()] = symbol_data
    return account_currency, results


def validate_broker_api_endpoint(endpoint_template: str) -> None:
    endpoint = endpoint_template.strip()
    try:
        parsed_endpoint = urlsplit(endpoint)
        parsed_fields = tuple(Formatter().parse(endpoint))
    except ValueError as error:
        raise ValueError(f"Broker API endpoint is malformed: {error}") from error
    if parsed_endpoint.scheme.lower() != "https" or not parsed_endpoint.hostname:
        raise ValueError("Broker API endpoint must be an HTTPS URL.")
    if parsed_endpoint.username or parsed_endpoint.password or parsed_endpoint.fragment:
        raise ValueError(
            "Do not put credentials or secret fragments in the endpoint URL."
        )
    fields = {field_name for _literal, field_name, _spec, _conversion in parsed_fields}
    if "symbol" not in fields:
        raise ValueError("Broker API endpoint must include the {symbol} placeholder.")
    if fields - {"symbol", "start", "end", "interval"} or any(
        spec or conversion
        for _literal, field_name, spec, conversion in parsed_fields
        if field_name is not None
    ):
        raise ValueError(
            "Endpoint placeholders may only be {symbol}, {start}, {end}, and {interval}."
        )
    sensitive_query_keys = {
        "key",
        "apikey",
        "accesstoken",
        "auth",
        "password",
        "secret",
        "clientsecret",
        "signature",
        "xapikey",
        "token",
    }
    query_keys = (
        re.sub(r"[^a-z0-9]", "", key.lower())
        for key, _value in parse_qsl(parsed_endpoint.query, keep_blank_values=True)
    )
    if any(key in sensitive_query_keys for key in query_keys):
        raise ValueError(
            "Do not put API credentials in the endpoint URL; use the token field."
        )


def _parse_broker_api_symbol_data(payload: object, requested_symbol: str) -> MT5SymbolData:
    if not isinstance(payload, dict):
        raise ValueError("response root must be a JSON object")
    actual_symbol = payload.get("symbol")
    if not isinstance(actual_symbol, str) or actual_symbol.strip().upper() != requested_symbol.upper():
        raise ValueError("response symbol does not match the requested broker symbol")
    account_currency = payload.get("account_currency")
    quote_data = payload.get("quote")
    contract_data = payload.get("contract")
    bars_data = payload.get("bars")
    if not isinstance(account_currency, str) or not account_currency.strip():
        raise ValueError("account_currency must be a non-empty string")
    if not isinstance(quote_data, dict) or not isinstance(contract_data, dict):
        raise ValueError("quote and contract must be JSON objects")
    if not isinstance(bars_data, list):
        raise ValueError("bars must be a JSON array")

    def decimal_field(value: object, label: str, *, positive: bool = False) -> Decimal:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{label} must be a finite number")
        try:
            result = Decimal(str(value))
        except InvalidOperation as error:
            raise ValueError(f"{label} must be a finite number") from error
        if not result.is_finite() or (positive and result <= ZERO):
            qualifier = "positive and finite" if positive else "finite"
            raise ValueError(f"{label} must be {qualifier}")
        return result

    def contract_field(
        primary: str,
        alternate: str | None = None,
        *,
        positive: bool = False,
        optional: bool = False,
    ) -> str:
        raw = contract_data.get(primary)
        if raw is None and alternate:
            raw = contract_data.get(alternate)
        if raw is None and optional:
            return ""
        return format(decimal_field(raw, f"contract.{primary}", positive=positive), "f")

    contract_currency = contract_data.get("contract_currency", account_currency)
    if not isinstance(contract_currency, str) or not contract_currency.strip():
        raise ValueError("contract.contract_currency must be a non-empty string")
    if contract_currency.strip().upper() != account_currency.strip().upper():
        raise ValueError(
            "contract currency must match account_currency for point-value sizing"
        )
    contract: ContractFields = {
        "point_size": contract_field("point_size", positive=True),
        "point_value": contract_field(
            "point_value_per_point_per_lot", "point_value", positive=True
        ),
        "points_per_pip": contract_field(
            "points_per_ea_pip",
            "points_per_pip",
            positive=True,
            optional=True,
        ),
        "lot_increment": contract_field("lot_step", "lot_increment", positive=True),
        "minimum_lot": contract_field("min_lot", "minimum_lot", positive=True),
        "maximum_lot": contract_field(
            "max_lot", "maximum_lot", positive=True, optional=True
        ),
        "commission_per_lot": contract_field(
            "commission_per_lot", optional=True
        ),
        "contract_currency": contract_currency.strip().upper(),
    }
    if contract["commission_per_lot"]:
        commission = Decimal(contract["commission_per_lot"])
        if commission < ZERO:
            raise ValueError("contract.commission_per_lot cannot be negative")

    quote_price = decimal_field(quote_data.get("price"), "quote.price", positive=True)
    quote_currency = quote_data.get("currency", account_currency)
    quote_time = quote_data.get("time", "time unavailable")
    if not isinstance(quote_currency, str) or not quote_currency.strip():
        raise ValueError("quote.currency must be a non-empty string")
    if not isinstance(quote_time, str):
        raise ValueError("quote.time must be a string")
    quote: QuoteData = (
        quote_price,
        quote_currency.strip().upper(),
        requested_symbol,
        quote_time.strip() or "time unavailable",
    )

    bars: list[DailyBar] = []
    for index, item in enumerate(bars_data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"bars[{index - 1}] must be a JSON object")
        bar_date = item.get("date")
        if not isinstance(bar_date, str):
            raise ValueError(f"bars[{index - 1}].date must be YYYY-MM-DD text")
        try:
            normalized_date = datetime.strptime(bar_date, "%Y-%m-%d").date().isoformat()
        except ValueError as error:
            raise ValueError(
                f"bars[{index - 1}].date must be a valid YYYY-MM-DD date"
            ) from error
        low = decimal_field(item.get("low"), f"bars[{index - 1}].low", positive=True)
        high = decimal_field(item.get("high"), f"bars[{index - 1}].high", positive=True)
        close = decimal_field(item.get("close"), f"bars[{index - 1}].close", positive=True)
        raw_open = item.get("open")
        raw_spread = item.get("spread_points")
        raw_samples = item.get("spread_sample_count")
        if raw_samples is not None and (
            isinstance(raw_samples, bool)
            or not isinstance(raw_samples, int)
        ):
            raise ValueError(
                f"bars[{index - 1}].spread_sample_count must be a non-negative integer"
            )
        bar = DailyBar(
            normalized_date,
            high,
            low,
            close,
            spread_points=(
                decimal_field(raw_spread, f"bars[{index - 1}].spread_points")
                if raw_spread is not None
                else None
            ),
            open=(
                decimal_field(raw_open, f"bars[{index - 1}].open", positive=True)
                if raw_open is not None
                else None
            ),
            spread_sample_count=(
                int(raw_samples)
                if isinstance(raw_samples, int) and not isinstance(raw_samples, bool)
                else None
            ),
        )
        if bar.low > bar.high or not bar.low <= bar.close <= bar.high:
            raise ValueError(
                f"bars[{index - 1}] has inconsistent OHLC prices"
            )
        if bar.open is not None and not bar.low <= bar.open <= bar.high:
            raise ValueError(f"bars[{index - 1}].open is outside low/high")
        if bar.spread_points is not None and bar.spread_points < ZERO:
            raise ValueError(f"bars[{index - 1}].spread_points cannot be negative")
        if bar.spread_sample_count is not None and bar.spread_sample_count < 0:
            raise ValueError(
                f"bars[{index - 1}].spread_sample_count cannot be negative"
            )
        bars.append(bar)
    if len(bars) < 20:
        raise ValueError("at least 20 valid daily bars are required")
    if len({bar.date for bar in bars}) != len(bars):
        raise ValueError("daily bars cannot contain duplicate dates")
    bars.sort(key=lambda bar: bar.date)
    calculate_historical_stress(tuple(bars))
    return MT5SymbolData(contract, tuple(bars), quote)


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
        if not isinstance(quote_data, list):
            raise ValueError(f"Yahoo Finance returned malformed fallback quote data for {symbol}.")
        closes = (
            quote_data[0].get("close", [])
            if quote_data and isinstance(quote_data[0], dict)
            else []
        )
        if not isinstance(closes, list):
            raise ValueError(f"Yahoo Finance returned malformed fallback quote prices for {symbol}.")
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
    time_text = "time unavailable"
    if timestamp is not None:
        try:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError("Expected a numeric Unix timestamp.")
            time_text = datetime.fromtimestamp(
                timestamp, timezone.utc
            ).astimezone().strftime("%Y-%m-%d %H:%M")
        except (OverflowError, OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"Yahoo Finance returned an invalid quote time for {symbol}."
            ) from error
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
    if any(len(values) != len(timestamps) for values in (highs, lows, closes)):
        raise ValueError(
            f"Yahoo Finance returned mismatched daily history array lengths for {symbol}."
        )
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        if highs[index] is None or lows[index] is None or closes[index] is None:
            raise ValueError(
                f"Yahoo Finance daily history for {symbol}, bar {index + 1}, "
                "has missing prices; incomplete history cannot be used for sizing."
            )
        try:
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError("Expected a numeric Unix timestamp.")
            date = datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat()
        except (OverflowError, OSError, TypeError, ValueError) as error:
            raise ValueError(
                f"Yahoo Finance returned an invalid timestamp for {symbol}, "
                f"bar {index + 1}."
            ) from error
        try:
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


def parse_mt5_history_csv(
    csv_text: str,
    default_symbol: str = "",
) -> dict[str, tuple[DailyBar, ...]]:
    """Parse MT5 OHLC CSV and aggregate intraday rows into daily bars."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff")))
    if not reader.fieldnames:
        raise ValueError("The MT5 history CSV is empty or has no header row.")

    def normalized_header(value: str) -> str:
        return value.strip().strip("<>").strip().lower()

    header_map: dict[str, str] = {}
    for name in reader.fieldnames:
        normalized = normalized_header(name)
        if not normalized or normalized in header_map:
            raise ValueError("MT5 history CSV has an empty or duplicate column header.")
        header_map[normalized] = name
    required = ("date", "high", "low", "close")
    missing = [name for name in required if name not in header_map]
    if missing:
        raise ValueError(
            "MT5 history CSV is missing required columns: " + ", ".join(missing)
        )
    if "symbol" not in header_map and not default_symbol.strip():
        raise ValueError(
            "MT5 history CSV needs a symbol column unless exactly one allocation "
            "is available."
        )

    def parse_timestamp(date_text: str, time_text: str) -> datetime:
        clean_date = date_text.strip()
        clean_time = time_text.strip()
        if re.match(r"^\d{4}\.\d{2}\.\d{2}", clean_date):
            clean_date = clean_date.replace(".", "-", 2)
        combined = f"{clean_date} {clean_time}".strip()
        try:
            timestamp = datetime.fromisoformat(combined)
        except ValueError:
            pass
        else:
            if timestamp.tzinfo is not None:
                raise ValueError(
                    "MT5 date/time must use broker-local time without a timezone offset."
                )
            return timestamp
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(combined, pattern)
            except ValueError:
                continue
        raise ValueError(f"Invalid MT5 date/time value: {combined}")

    grouped: dict[
        str,
        dict[
            str,
            tuple[
                datetime,
                Decimal,
                Decimal,
                Decimal,
                Decimal | None,
                int | None,
                datetime,
                Decimal | None,
            ],
        ],
    ] = {}
    seen_timestamps: dict[str, set[datetime]] = {}
    symbol_timeframes: dict[str, str] = {}
    row_count = 0
    for line_number, row in enumerate(reader, start=2):
        row_count += 1
        if None in row:
            raise ValueError(f"MT5 history CSV row {line_number} has too many columns.")
        if any(value is None for value in row.values()):
            raise ValueError(f"MT5 history CSV row {line_number} has missing columns.")
        raw_symbol = (
            row.get(header_map["symbol"], "").strip()
            if "symbol" in header_map
            else default_symbol.strip()
        )
        if not raw_symbol:
            raise ValueError(f"MT5 history CSV row {line_number} has no symbol.")
        raw_date = row.get(header_map["date"], "")
        raw_time = row.get(header_map["time"], "") if "time" in header_map else ""
        try:
            timestamp = parse_timestamp(raw_date, raw_time)
            high = decimal_value(row.get(header_map["high"], ""), "MT5 bar high")
            low = decimal_value(row.get(header_map["low"], ""), "MT5 bar low")
            close = decimal_value(row.get(header_map["close"], ""), "MT5 bar close")
            open_text = (
                row.get(header_map["open"], "").strip()
                if "open" in header_map
                else ""
            )
            opening = decimal_value(open_text, "MT5 bar open") if open_text else None
            spread_header = next(
                (
                    header_map[name]
                    for name in (
                        "spread_max_points",
                        "max_spread_points",
                        "spread_points",
                        "spread",
                    )
                    if name in header_map and row.get(header_map[name], "").strip()
                ),
                None,
            )
            spread_text = row.get(spread_header, "").strip() if spread_header else ""
            spread = (
                decimal_value(spread_text, "MT5 bar spread")
                if spread_text
                else None
            )
            sample_count_text = (
                row.get(header_map["spread_sample_count"], "").strip()
                if "spread_sample_count" in header_map
                else ""
            )
            try:
                sample_count = (
                    int(sample_count_text) if sample_count_text else None
                )
            except ValueError as error:
                raise ValueError(
                    "MT5 bar spread sample count must be a whole number."
                ) from error
            if sample_count is not None and sample_count < 0:
                raise ValueError("MT5 bar spread sample count must be non-negative.")
        except ValueError as error:
            raise ValueError(f"MT5 history CSV row {line_number}: {error}") from error
        if (
            min(high, low, close) <= ZERO
            or not low <= close <= high
            or (opening is not None and not low <= opening <= high)
        ):
            raise ValueError(
                f"MT5 history CSV row {line_number} contains invalid OHLC prices."
            )
        if spread is not None and spread < ZERO:
            raise ValueError(
                f"MT5 history CSV row {line_number} contains a negative spread."
            )
        symbol_key = raw_symbol.strip().upper()
        timeframe = (
            row[header_map["timeframe"]].strip().upper()
            if "timeframe" in header_map
            else ""
        )
        if timeframe:
            previous_timeframe = symbol_timeframes.setdefault(symbol_key, timeframe)
            if timeframe != previous_timeframe:
                raise ValueError(
                    f"MT5 history CSV row {line_number} mixes timeframes for "
                    f"{symbol_key}: {previous_timeframe} and {timeframe}."
                )
        symbol_timestamps = seen_timestamps.setdefault(symbol_key, set())
        if timestamp in symbol_timestamps:
            raise ValueError(
                f"MT5 history CSV row {line_number} has a duplicate timestamp "
                f"for {symbol_key}: {timestamp.isoformat()}."
            )
        symbol_timestamps.add(timestamp)
        day = timestamp.date().isoformat()
        daily_rows = grouped.setdefault(symbol_key, {})
        previous = daily_rows.get(day)
        if previous is None:
            daily_rows[day] = (
                timestamp,
                high,
                low,
                close,
                spread,
                sample_count,
                timestamp,
                opening,
            )
        else:
            spreads = tuple(
                value for value in (spread, previous[4]) if value is not None
            )
            sample_counts = tuple(
                value
                for value in (sample_count, previous[5])
                if value is not None
            )
            daily_rows[day] = (
                max(timestamp, previous[0]),
                max(high, previous[1]),
                min(low, previous[2]),
                close if timestamp >= previous[0] else previous[3],
                max(spreads) if spreads else None,
                sum(sample_counts) if sample_counts else None,
                min(timestamp, previous[6]),
                opening if timestamp < previous[6] else previous[7],
            )

    if row_count == 0:
        raise ValueError("The MT5 history CSV has no OHLC data rows.")

    histories: dict[str, tuple[DailyBar, ...]] = {}
    for symbol, daily_rows in grouped.items():
        bars = tuple(
            DailyBar(
                date,
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[7],
            )
            for date, values in sorted(daily_rows.items())
        )
        calculate_historical_stress(bars)
        histories[symbol] = bars
    return histories


def build_mt5_set_template(robot: str, settings: dict[str, str]) -> str:
    """Create a .set draft using canonical names; EA input identifiers need verification."""
    robot_type = robot.strip().upper()
    if robot_type not in ("DCA", "RSI"):
        raise ValueError("Robot type must be DCA or RSI.")
    fields = {
        "Magic Number": "MagicNumber",
        "Max Trades": "MaxTrades",
        "Step Type": "StepType",
        "Step Value": "StepValue",
        "Take Profit Type": "TakeProfitType",
        "Take Profit Value": "TakeProfitValue",
        "Risk Type": "RiskType",
        "Risk": "Risk",
        "Multiplier Factor": "MultiplierFactor",
    }
    enum_values = {
        "Step Type": {
            "Enum_percentage_pips": "0",
            "enum_fixed_pips": "1",
        },
        "Take Profit Type": {
            "Enum_percentage_pips": "0",
            "enum_fixed_pips": "1",
        },
        "Risk Type": {"Fixed lots": "0", "Cash": "1"},
    }
    if robot_type == "DCA":
        fields.update(
            {
                "Entry on price break": "EntryOnPriceBreak",
                "InpPriceBreakType": "InpPriceBreakType",
                "Reference Price": "ReferencePrice",
                "Trade on new candle": "TradeOnNewCandle",
                "Show Invested Money": "ShowInvestedMoney",
            }
        )
        enum_values["InpPriceBreakType"] = {}
        enum_values["InpPriceBreakType"] = {
            "break Below": "0",
            "break above": "1",
            "break Above": "1",
        }
    else:
        fields.update(
            {
                "Close When Overbought": "CloseWhenOverbought",
                "RSI oversold": "RSIOversold",
                "RSI Overbought": "RSIOverbought",
                "RSI Period": "RSIPeriod",
                "Show Invested Money": "ShowInvestedMoney",
            }
        )

    integer_fields = {"Magic Number", "Max Trades"}
    if robot_type == "RSI":
        integer_fields.add("RSI Period")
    decimal_fields = {
        "Step Value",
        "Take Profit Value",
        "Risk",
        "Multiplier Factor",
    }
    if robot_type == "DCA":
        decimal_fields.add("Reference Price")
    else:
        decimal_fields.update({"RSI oversold", "RSI Overbought"})
    boolean_fields = (
        {
            "Entry on price break",
            "Trade on new candle",
            "Show Invested Money",
        }
        if robot_type == "DCA"
        else {"Close When Overbought", "Show Invested Money"}
    )

    lines = []
    for label, name in fields.items():
        if label not in settings:
            raise ValueError(f"Generated settings are missing '{label}'.")
        value = settings[label].strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError(f"Generated setting '{label}' is empty or invalid.")
        if label in integer_fields:
            positive_integer(value, label)
            if label == "Magic Number" and int(value) > 2147483647:
                raise ValueError("Magic Number must not exceed 2147483647.")
        elif label in decimal_fields:
            numeric_value = decimal_value(value, label)
            if numeric_value < ZERO or (
                numeric_value == ZERO
                and label != "Reference Price"
                and not (label == "Risk" and settings.get("Risk Type") == "Fixed lots")
            ):
                raise ValueError(f"Generated setting '{label}' must be positive.")
        elif label in boolean_fields and value not in ("true", "false"):
            raise ValueError(f"Generated setting '{label}' must be true or false.")
        choices = enum_values.get(label, {})
        if choices:
            if value not in choices:
                raise ValueError(f"Unsupported {label} value: {value}")
            value = choices[value]
        lines.append(f"{name}={value}||0||0||0||N")
    if robot_type == "DCA":
        if settings["Entry on price break"] == "true":
            if decimal_value(settings["Reference Price"], "Reference Price") <= ZERO:
                raise ValueError("Reference Price must be positive when price-break entry is enabled.")
        elif decimal_value(settings["Reference Price"], "Reference Price") != ZERO:
            raise ValueError("Reference Price must be zero when price-break entry is disabled.")
    else:
        oversold = decimal_value(settings["RSI oversold"], "RSI oversold")
        overbought = decimal_value(settings["RSI Overbought"], "RSI Overbought")
        if not ZERO < oversold < overbought < Decimal("100"):
            raise ValueError("RSI levels must satisfy 0 < oversold < overbought < 100.")
    return "\r\n".join(lines) + "\r\n"


class RiskCalculatorApp(tk.Tk):
    AUTOSAVE_ENABLED = True
    STARTUP_REFRESH_ENABLED = True

    def __init__(self) -> None:
        super().__init__()
        self.title("MT5 Portfolio Risk Planner")
        self.geometry("1180x850")
        self.minsize(980, 700)

        self.allocations: dict[str, Allocation] = {}
        self.allocation_percentages: dict[str, Decimal | None] = {}
        self.next_allocation_id = 1
        self.allocation_results: dict[str, AllocationResult] = {}
        self.contract_inputs: dict[str, ContractFields] = {}
        self.risk_profile = default_profile()
        self.exposure_inputs: dict[str, ExposureInputs] = {}
        self.quotes: dict[str, QuoteData] = {}
        self.historical_stresses: dict[str, HistoricalStress] = {}
        self.history_bars: dict[str, tuple[DailyBar, ...]] = {}
        self.history_sources: dict[str, str] = {}
        self.magic_assignments: dict[str, int] = {}
        self.quote_messages: queue.Queue[tuple[str, str, object]] = queue.Queue()
        self.quote_busy = False
        self.quote_request_cancelled = False
        self.startup_wait_window: tk.Toplevel | None = None
        self.startup_wait_progress: ttk.Progressbar | None = None
        self._startup_refresh_after_id: str | None = None
        self.fetch_all_button: ttk.Button | None = None
        self.fetch_mt5_button: ttk.Button | None = None
        self.inspect_mt5_button: ttk.Button | None = None
        self.fetch_broker_api_button: ttk.Button | None = None
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
        self.generated_scenario: dict[str, object] | None = None
        self.generated_output = ""
        self.generated_requires_accepted_portfolio = False
        self.autosave_path = os.path.join(APP_DATA_DIRECTORY, AUTOSAVE_FILE_NAME)
        self.broker_api_config_path = os.path.join(
            APP_DATA_DIRECTORY, BROKER_API_CONFIG_FILE_NAME
        )
        self.broker_api_endpoint_var = tk.StringVar()
        self.broker_api_token_var = tk.StringVar()
        self.mt5_terminal_path_var = tk.StringVar()
        self.mt5_connection: dict[str, str] = {}
        self.mt5_symbol_catalog: dict[str, dict[str, object]] = {}
        self.mt5_config_path = os.path.join(APP_DATA_DIRECTORY, "mt5_connection.json")
        self.equity_report_path = os.path.join(APP_DATA_DIRECTORY, "equity_validation.json")
        self.broker_symbol_combo: ttk.Combobox | None = None
        self._autosave_loading = False
        self._autosave_dirty = False
        self._autosave_after_id: str | None = None
        self._autosave_trace_variables: set[str] = set()
        self.cached_data_warnings: dict[str, str] = {}
        self.prop_website_snapshot: PropWebsiteSnapshot | None = None
        self.prop_import_window: tk.Toplevel | None = None

        self._build_ui()
        self._load_mt5_config()
        self._add_default_allocation()
        self._refresh_allocation_choices()
        if self.AUTOSAVE_ENABLED:
            self._install_autosave_traces()
            self._load_autosave_scenario()
            self.protocol("WM_DELETE_WINDOW", self._close_app)
        self._refresh_broker_symbol_choices()
        if self.STARTUP_REFRESH_ENABLED:
            self._startup_refresh_after_id = self.after(
                200, self._refresh_startup_data
            )

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
            text="Risk estimates using MT5 contracts and broker history with Yahoo fallback",
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
        self.prop_account_tab = ttk.Frame(self.notebook, padding=12)
        self.portfolio_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.prop_account_tab, text="Prop firm & account")
        self.notebook.add(self.portfolio_tab, text="Portfolio")
        self.notebook.add(self.settings_tab, text="Robot settings")
        self._build_prop_account_tab()
        self._build_portfolio_tab()
        self._build_settings_tab()
        self.notebook.bind("<<NotebookTabChanged>>", self._main_tab_changed)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Frame(self, padding=(12, 5))
        status_bar.pack(fill="x", side="bottom")
        self.fetch_progress = ttk.Progressbar(
            status_bar, mode="indeterminate", length=100
        )
        ttk.Label(status_bar, textvariable=self.status_var, anchor="w").pack(
            side="left", fill="x", expand=True
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
            "spread_points": self.spread_points_var,
            "slippage_points": self.slippage_points_var,
            "commission_per_lot": self.commission_per_lot_var,
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
            "maximum_lot": self.maximum_lot_var,
            "commission_per_lot": self.symbol_commission_per_lot_var,
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
                    "allocation_percent": (
                        str(self.allocation_percentages[row_id])
                        if self.allocation_percentages.get(row_id) is not None
                        else ""
                    ),
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
                    "history_source": self.history_sources.get(row_id, ""),
                    "exposure_inputs": dict(self.exposure_inputs.get(row_id, default_exposure())),
                    "history_bars": [
                        {
                            "date": bar.date,
                            "high": str(bar.high),
                            "low": str(bar.low),
                            "close": str(bar.close),
                            "open": str(bar.open) if bar.open is not None else "",
                            "spread_points": (
                                str(bar.spread_points)
                                if bar.spread_points is not None
                                else ""
                            ),
                            "spread_sample_count": (
                                str(bar.spread_sample_count)
                                if bar.spread_sample_count is not None
                                else ""
                            ),
                        }
                        for bar in self.history_bars.get(row_id, ())
                    ],
                }
            )

        selected_index = row_ids.index(selected_id) if selected_id in row_ids else None
        return {
            "format": "mt5-risk-planner-scenario",
            "version": 14,
            "risk_profile": dict(self.risk_profile),
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
                "allocation_percent": self.allocation_pct_var.get(),
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
            or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
        ):
            raise ValueError("Unsupported or unrecognized scenario file format.")
        risk_profile = validate_profile(
            data.get("risk_profile") if version >= 14 else default_profile()
        )

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
            required_text(portfolio, "account_capital"), "Scenario account capital"
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
        if required_text(new_allocation, "robot").upper() not in ("DCA", "RSI"):
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
            allocation_percent = raw.get("allocation_percent", "")
            if allocation_percent != "":
                if not isinstance(allocation_percent, str):
                    raise ValueError(
                        f"Allocation {position} percentage must be text."
                    )
                parsed_percent = decimal_value(
                    allocation_percent, f"Allocation {position} percentage"
                )
                if not ZERO < parsed_percent <= ONE_HUNDRED:
                    raise ValueError(
                        f"Allocation {position} percentage must be greater than "
                        "0 and no greater than 100."
                    )

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
                "maximum_lot",
                "commission_per_lot",
                "contract_currency",
            )
            if version >= 3 and version < 15 and "broker_contract" not in raw:
                raise ValueError(f"Allocation {position} is missing broker contract data.")
            normalized_contract = {
                field: (
                    ""
                    if (field == "maximum_lot" and version < 10)
                    or (field == "commission_per_lot" and version < 11)
                    or (version >= 15 and field not in raw_contract)
                    else (
                        required_text(raw_contract, field)
                        if version >= 3
                        else str(raw_contract.get(field, ""))
                    )
                )
                for field in contract_fields
            }
            for field in (
                "point_value",
                "point_size",
                "points_per_pip",
                "lot_increment",
                "minimum_lot",
                "maximum_lot",
            ):
                value = normalized_contract[field].strip()
                if value:
                    parsed_value = decimal_value(
                        value, f"Allocation {position} broker {field}"
                    )
                    if parsed_value <= ZERO:
                        raise ValueError(
                            f"Allocation {position} broker {field} must be positive."
                        )
            if (
                normalized_contract["maximum_lot"].strip()
                and normalized_contract["minimum_lot"].strip()
                and decimal_value(
                    normalized_contract["maximum_lot"],
                    f"Allocation {position} broker maximum lot",
                )
                < decimal_value(
                    normalized_contract["minimum_lot"],
                    f"Allocation {position} broker minimum lot",
                )
            ):
                raise ValueError(
                    f"Allocation {position} broker maximum lot cannot be below "
                    "the minimum lot."
                )
            contract_commission = normalized_contract["commission_per_lot"].strip()
            if contract_commission:
                if decimal_value(
                    contract_commission,
                    f"Allocation {position} broker commission per lot",
                ) < ZERO:
                    raise ValueError(
                        f"Allocation {position} broker commission must be "
                        "non-negative."
                    )
            historical_stress = None
            if version >= 4:
                if "historical_stress" not in raw and version < 15:
                    raise ValueError(
                        f"Allocation {position} is missing historical stress data."
                    )
                raw_stress = raw.get("historical_stress")
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
                        < ZERO
                        or decimal_value(
                            short_pct, f"Allocation {position} short historical stress"
                        )
                        < ZERO
                    ):
                        raise ValueError(
                            f"Allocation {position} historical stress percentages must be non-negative."
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
                    for direction, pct_text in (("long", long_pct), ("short", short_pct)):
                        if decimal_value(pct_text, "Historical stress percent") == ZERO:
                            if stress_dates[f"{direction}_observed_date"]:
                                raise ValueError(
                                    f"Allocation {position} {direction} daily stress "
                                    "dates must be empty when the move is zero."
                                )
                    try:
                        parsed_dates = {
                            field: datetime.strptime(value, "%Y-%m-%d").date()
                            for field, value in stress_dates.items()
                            if value or field in ("start_date", "end_date")
                        }
                    except ValueError as error:
                        raise ValueError(
                            f"Allocation {position} has an invalid historical date."
                        ) from error
                    if (
                        parsed_dates["start_date"] > parsed_dates["end_date"]
                        or any(
                            not (
                                parsed_dates["start_date"]
                                <= parsed_dates[field]
                                <= parsed_dates["end_date"]
                            )
                            for field in ("long_observed_date", "short_observed_date")
                            if field in parsed_dates
                        )
                    ):
                        raise ValueError(
                            f"Allocation {position} historical dates are inconsistent."
                        )
                    if (
                        decimal_value(long_pct, "Long historical stress") > ZERO
                        and "long_observed_date" not in parsed_dates
                    ) or (
                        decimal_value(short_pct, "Short historical stress") > ZERO
                        and "short_observed_date" not in parsed_dates
                    ):
                        raise ValueError(
                            f"Allocation {position} positive daily stress needs an observed date."
                        )
                    drawdown_values: dict[str, str] = {}
                    drawdown_date_pairs = (
                        (
                            "long_drawdown_pct",
                            "long_drawdown_peak_date",
                            "long_drawdown_trough_date",
                        ),
                        (
                            "short_rally_pct",
                            "short_rally_trough_date",
                            "short_rally_peak_date",
                        ),
                    )
                    for pct_key, start_key, end_key in drawdown_date_pairs:
                        if version >= 8:
                            pct_text = required_text(raw_stress, pct_key)
                            start_text = required_text(raw_stress, start_key)
                            end_text = required_text(raw_stress, end_key)
                            pct_value = decimal_value(
                                pct_text,
                                f"Allocation {position} {pct_key.replace('_', ' ')}",
                            )
                            if pct_value < ZERO:
                                raise ValueError(
                                    f"Allocation {position} {pct_key.replace('_', ' ')} "
                                    "must be non-negative."
                                )
                            if pct_value == ZERO:
                                if start_text or end_text:
                                    raise ValueError(
                                        f"Allocation {position} {pct_key.replace('_', ' ')} "
                                        "dates must be empty when the move is zero."
                                    )
                            else:
                                try:
                                    start_value = datetime.strptime(
                                        start_text, "%Y-%m-%d"
                                    ).date()
                                    end_value = datetime.strptime(
                                        end_text, "%Y-%m-%d"
                                    ).date()
                                except ValueError as error:
                                    raise ValueError(
                                        f"Allocation {position} has invalid "
                                        f"{pct_key.replace('_', ' ')} dates."
                                    ) from error
                                if not (
                                    parsed_dates["start_date"]
                                    <= start_value
                                    <= end_value
                                    <= parsed_dates["end_date"]
                                ):
                                    raise ValueError(
                                        f"Allocation {position} {pct_key.replace('_', ' ')} "
                                        "dates are inconsistent."
                                    )
                            drawdown_values[pct_key] = str(pct_value)
                            drawdown_values[start_key] = start_text
                            drawdown_values[end_key] = end_text
                        else:
                            drawdown_values[pct_key] = "0"
                            drawdown_values[start_key] = ""
                            drawdown_values[end_key] = ""
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
                        **drawdown_values,
                        "bar_count": raw_count,
                        "start_date": stress_dates["start_date"],
                        "end_date": stress_dates["end_date"],
                    }
            raw_bars = raw.get("history_bars", [])
            history_bars: list[dict[str, str]] = []
            if version >= 7:
                if not isinstance(raw_bars, list) or len(raw_bars) > 10000:
                    raise ValueError(
                        f"Allocation {position} history_bars must be a list of at most 10000 bars."
                    )
                parsed_bars: list[DailyBar] = []
                for bar_index, raw_bar in enumerate(raw_bars, start=1):
                    if not isinstance(raw_bar, dict):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} must be an object."
                        )
                    bar_date = required_text(raw_bar, "date")
                    try:
                        datetime.strptime(bar_date, "%Y-%m-%d")
                    except ValueError as error:
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} has an invalid date."
                        ) from error
                    raw_spread = raw_bar.get("spread_points", "")
                    raw_open = raw_bar.get("open", "")
                    if not isinstance(raw_open, str):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "open must be text."
                        )
                    if not isinstance(raw_spread, str):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "spread must be text."
                        )
                    raw_sample_count = raw_bar.get("spread_sample_count", "")
                    if version >= 12 and not isinstance(raw_sample_count, str):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "spread sample count must be text."
                        )
                    if not isinstance(raw_sample_count, str):
                        raw_sample_count = ""
                    try:
                        spread_sample_count = (
                            int(raw_sample_count) if raw_sample_count.strip() else None
                        )
                    except ValueError as error:
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "has an invalid spread sample count."
                        ) from error
                    if (
                        spread_sample_count is not None
                        and spread_sample_count < 0
                    ):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "spread sample count must be non-negative."
                        )
                    parsed_bar = DailyBar(
                        bar_date,
                        decimal_value(
                            required_text(raw_bar, "high"),
                            f"Allocation {position} history high",
                        ),
                        decimal_value(
                            required_text(raw_bar, "low"),
                            f"Allocation {position} history low",
                        ),
                        decimal_value(
                            required_text(raw_bar, "close"),
                            f"Allocation {position} history close",
                        ),
                        decimal_value(
                            raw_spread,
                            f"Allocation {position} history spread",
                        )
                        if raw_spread.strip()
                        else None,
                        spread_sample_count,
                        (
                            decimal_value(
                                raw_open,
                                f"Allocation {position} history open",
                            )
                            if raw_open.strip()
                            else None
                        ),
                    )
                    if (
                        parsed_bar.spread_points is not None
                        and parsed_bar.spread_points < ZERO
                    ):
                        raise ValueError(
                            f"Allocation {position} history bar {bar_index} "
                            "spread must be non-negative."
                        )
                    parsed_bars.append(parsed_bar)
                    history_bars.append(
                        {
                            "date": parsed_bar.date,
                            "high": str(parsed_bar.high),
                            "low": str(parsed_bar.low),
                            "close": str(parsed_bar.close),
                            "open": (
                                str(parsed_bar.open)
                                if parsed_bar.open is not None
                                else ""
                            ),
                            "spread_points": (
                                str(parsed_bar.spread_points)
                                if parsed_bar.spread_points is not None
                                else ""
                            ),
                            "spread_sample_count": (
                                str(parsed_bar.spread_sample_count)
                                if parsed_bar.spread_sample_count is not None
                                else ""
                            ),
                        }
                    )
                history_source = (
                    raw.get("history_source", "")
                    if version >= 15
                    else required_text(raw, "history_source")
                )
                if not isinstance(history_source, str):
                    raise ValueError(
                        f"Allocation {position} history source must be text."
                    )
                if history_source not in ("", "Yahoo", *BROKER_HISTORY_SOURCES):
                    raise ValueError(
                        f"Allocation {position} has an unsupported history source."
                    )
                if parsed_bars:
                    computed_stress = calculate_historical_stress(parsed_bars)
                    if (
                        historical_stress is None
                        or history_source not in BROKER_HISTORY_SOURCES
                    ):
                        raise ValueError(
                            f"Allocation {position} broker history bars need matching historical stress data."
                        )
                    historical_stress = RiskCalculatorApp._historical_stress_data(
                        computed_stress
                    )
                    if normalized_quote is None:
                        raise ValueError(
                            f"Allocation {position} MT5 history needs a saved reference quote."
                        )
                if history_source in BROKER_HISTORY_SOURCES and not parsed_bars:
                    raise ValueError(
                        f"Allocation {position} is marked as broker history without stored bars."
                    )
            else:
                history_source = "Yahoo" if historical_stress is not None else ""
            normalized_allocations.append(
                {
                    "symbol": symbol,
                    "yahoo_ticker": ticker or yahoo_symbol_for(symbol, ""),
                    "robot": robot,
                    "capital": capital_text,
                    "allocation_percent": allocation_percent,
                    "magic_number": raw_magic,
                    "broker_contract": normalized_contract,
                    "quote": normalized_quote,
                    "historical_stress": historical_stress,
                    "history_source": history_source,
                    "exposure_inputs": validate_exposure(
                        raw.get("exposure_inputs") if version >= 14 else default_exposure()
                    ),
                    "history_bars": history_bars,
                }
            )

        total_allocation_percent = sum(
            (
                decimal_value(item["allocation_percent"], "Allocation percentage")
                for item in normalized_allocations
                if item["allocation_percent"]
            ),
            ZERO,
        )
        if total_allocation_percent > ONE_HUNDRED:
            raise ValueError(
                "The sum of account-allocation percentages cannot exceed 100%."
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
        if text_settings.get("stress_mode") == LEGACY_HISTORICAL_STRESS_MODE:
            text_settings["stress_mode"] = HISTORICAL_STRESS_MODE
        if version < 7:
            text_settings.setdefault("spread_points", "0")
            text_settings.setdefault("slippage_points", "0")
            text_settings.setdefault("commission_per_lot", "0")
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
            "spread_points",
            "slippage_points",
            "commission_per_lot",
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
        market_text_fields = {
            "point_value", "point_size", "contract_currency", "lot_increment",
            "minimum_lot", "points_per_pip",
        }
        clean_text = {
            key: (
                ""
                if version >= 15 and key in market_text_fields and key not in text_settings
                else required_text(text_settings, key)
            )
            for key in string_keys
        }
        for cost_field in (
            "spread_points",
            "slippage_points",
            "commission_per_lot",
        ):
            if version < 7:
                clean_text[cost_field] = "0"
            cost_text = clean_text[cost_field].strip()
            if cost_text and decimal_value(
                cost_text, f"Scenario {cost_field.replace('_', ' ')}"
            ) < ZERO:
                raise ValueError(
                    f"Scenario {cost_field.replace('_', ' ')} must be non-negative."
                )
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
            HISTORICAL_DRAWDOWN_MODE,
            LEGACY_HISTORICAL_STRESS_MODE,
        ):
            raise ValueError("Scenario has an invalid stress-test mode.")
        if clean_text["stress_mode"] == LEGACY_HISTORICAL_STRESS_MODE:
            clean_text["stress_mode"] = HISTORICAL_STRESS_MODE
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
            "risk_profile": risk_profile,
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
            scenario_data = self._scenario_data()
            self._validate_scenario(scenario_data)
            directory = os.path.dirname(os.path.abspath(path))
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".mt5-scenario-",
                suffix=".tmp",
                dir=directory,
                text=True,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as scenario_file:
                json.dump(
                    scenario_data,
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

    def _install_autosave_traces(self) -> None:
        variables: dict[str, tk.Variable] = {
            "account_capital": self.account_capital_var,
            "currency": self.currency_var,
            "daily_limit": self.daily_limit_var,
            "remaining_daily_room": self.remaining_daily_loss_room_var,
            "overall_room": self.prop_total_loss_room_var,
            "limit_mode": self.limit_mode_var,
            "new_symbol": self.index_var,
            "new_ticker": self.yahoo_ticker_var,
            "new_robot": self.robot_var,
            "new_allocation_percent": self.allocation_pct_var,
        }
        variables.update(self._scenario_string_settings())
        variables.update(self._scenario_boolean_settings())
        variables.update(self._contract_input_variables())
        variables["symbol_commission"] = self.symbol_commission_per_lot_var
        variables["maximum_lot"] = self.maximum_lot_var
        for variable in variables.values():
            variable_name = str(variable)
            if variable_name in self._autosave_trace_variables:
                continue
            variable.trace_add("write", self._schedule_autosave)
            self._autosave_trace_variables.add(variable_name)

    def _load_broker_api_config(self) -> None:
        if not os.path.isfile(self.broker_api_config_path):
            return
        try:
            with open(self.broker_api_config_path, "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
            if not isinstance(config, dict) or not isinstance(
                config.get("endpoint_template"), str
            ):
                raise ValueError("Broker API config must contain endpoint_template.")
            validate_broker_api_endpoint(config["endpoint_template"])
            self.broker_api_endpoint_var.set(config["endpoint_template"])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            self.status_var.set(f"Could not load broker API endpoint: {error}")
            messagebox.showwarning(
                "Broker API configuration",
                f"{error}\n\nThe configuration file was kept unchanged:\n"
                f"{self.broker_api_config_path}",
                parent=self,
            )

    def _save_broker_api_config(self, endpoint_template: str) -> None:
        validate_broker_api_endpoint(endpoint_template)
        directory = os.path.dirname(self.broker_api_config_path)
        os.makedirs(directory, exist_ok=True)
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=".broker-api-",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as config_file:
                json.dump(
                    {"endpoint_template": endpoint_template.strip()},
                    config_file,
                    ensure_ascii=False,
                    indent=2,
                )
                config_file.write("\n")
            os.replace(temporary_path, self.broker_api_config_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _schedule_autosave(self, *_args: str) -> None:
        if self._autosave_loading or not self.AUTOSAVE_ENABLED:
            return
        self._autosave_dirty = True
        if self._autosave_after_id is not None:
            self.after_cancel(self._autosave_after_id)
        self._autosave_after_id = self.after(700, self._save_autosave_scenario)

    def _save_autosave_scenario(self) -> bool:
        self._autosave_after_id = None
        if self._autosave_loading or not self.AUTOSAVE_ENABLED:
            return True
        temporary_path = ""
        try:
            scenario_data = self._scenario_data()
            self._validate_scenario(scenario_data)
            if not self._save_symbol_market_data(scenario_data):
                return False
            portfolio_data = self._compact_autosave_scenario(scenario_data)
            self._validate_scenario(portfolio_data)
            directory = os.path.dirname(self.autosave_path)
            os.makedirs(directory, exist_ok=True)
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".portfolio-",
                suffix=".tmp",
                dir=directory,
                text=True,
            )
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as scenario_file:
                json.dump(
                    portfolio_data,
                    scenario_file,
                    ensure_ascii=False,
                    indent=2,
                )
                scenario_file.write("\n")
            os.replace(temporary_path, self.autosave_path)
            temporary_path = ""
            self._autosave_dirty = False
            return True
        except (OSError, TypeError, ValueError) as error:
            self.status_var.set(f"Local JSON auto-save failed: {error}")
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _load_autosave_scenario(self) -> None:
        if not self.AUTOSAVE_ENABLED:
            return
        source_path = self.autosave_path
        if not os.path.isfile(source_path):
            if not os.path.isfile(LEGACY_AUTOSAVE_PATH):
                return
            source_path = LEGACY_AUTOSAVE_PATH
        try:
            with open(source_path, "r", encoding="utf-8") as scenario_file:
                scenario_data = json.load(scenario_file)
            scenario = self._validate_scenario(
                self._restore_symbol_market_data(scenario_data)
            )
            self._autosave_loading = True
            try:
                self._apply_scenario(scenario)
            finally:
                self._autosave_loading = False
            self._autosave_dirty = False
            if source_path != self.autosave_path or scenario_data.get("version") != 15:
                self._autosave_dirty = True
                if not self._save_autosave_scenario():
                    raise OSError(
                        f"Could not migrate the saved portfolio to {self.autosave_path}"
                    )
                self.status_var.set(
                    f"Migrated saved portfolio and market history to: {self.autosave_path}"
                )
            else:
                self.status_var.set(
                    f"Loaded saved portfolio and market history: {self.autosave_path}"
                )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            self.status_var.set(f"Could not load saved local portfolio: {error}")
            messagebox.showwarning(
                "Saved portfolio could not be loaded",
                f"{error}\n\nThe file was kept unchanged:\n{source_path}",
                parent=self,
            )

    def _close_app(self) -> None:
        if self._autosave_after_id is not None:
            self.after_cancel(self._autosave_after_id)
            self._autosave_after_id = None
        if self._autosave_dirty and not self._save_autosave_scenario():
            messagebox.showerror(
                "Could not save portfolio",
                "The latest changes were not saved to the local JSON file. "
                "Correct the issue before closing, or use Save scenario.",
                parent=self,
            )
            return
        if self._startup_refresh_after_id is not None:
            self.after_cancel(self._startup_refresh_after_id)
            self._startup_refresh_after_id = None
        self.fetch_progress.stop()
        self.destroy()

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
            scenario_data = (
                self._restore_symbol_market_data(data)
                if isinstance(data, dict) and data.get("version") == 15
                else data
            )
            scenario = self._validate_scenario(scenario_data)
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
        self.generated_scenario = None
        self.generated_output = ""
        self.portfolio_suggestion_pending = False
        if self.quote_busy:
            self.quote_request_cancelled = True
        portfolio = scenario["portfolio"]
        new_allocation = scenario["new_allocation"]
        settings = scenario["settings"]
        raw_allocations = scenario["allocations"]
        assert isinstance(portfolio, dict)
        assert isinstance(new_allocation, dict)
        assert isinstance(settings, dict)
        assert isinstance(raw_allocations, list)
        self.risk_profile = validate_profile(scenario.get("risk_profile", default_profile()))

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
        allocation_percent = new_allocation.get("allocation_percent", "")
        if allocation_percent:
            self.allocation_pct_var.set(allocation_percent)
        else:
            self.allocation_pct_var.set(
                format_decimal(
                    decimal_value(new_allocation["capital"], "Allocated capital")
                    * ONE_HUNDRED
                    / decimal_value(
                        self.account_capital_var.get(), "Total account capital"
                    )
                )
            )

        for row_id in self.allocation_tree.get_children():
            self.allocation_tree.delete(row_id)
        self.allocations.clear()
        self.allocation_percentages.clear()
        self.allocation_results.clear()
        self.quotes.clear()
        self.historical_stresses.clear()
        self.history_bars.clear()
        self.history_sources.clear()
        self.magic_assignments.clear()
        self.contract_inputs.clear()
        self.exposure_inputs.clear()
        self.saved_quote_rows.clear()
        self.saved_history_rows.clear()
        self.current_settings_row = None
        contracts_to_restore: dict[str, ContractFields] = {}
        history_to_restore: dict[str, HistoricalStress] = {}
        bars_to_restore: dict[str, tuple[DailyBar, ...]] = {}
        sources_to_restore: dict[str, str] = {}
        for item in raw_allocations:
            assert isinstance(item, dict)
            self._insert_allocation(
                item["symbol"],
                item["yahoo_ticker"],
                item["robot"],
                item["capital"],
                item.get("allocation_percent") or None,
            )
            row_id = list(self.allocations)[-1]
            self.exposure_inputs[row_id] = validate_exposure(
                item.get("exposure_inputs", default_exposure())
            )
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
                    long_drawdown_pct=Decimal(
                        history_data.get("long_drawdown_pct", "0")
                    ),
                    long_drawdown_peak_date=history_data.get(
                        "long_drawdown_peak_date", ""
                    ),
                    long_drawdown_trough_date=history_data.get(
                        "long_drawdown_trough_date", ""
                    ),
                    short_rally_pct=Decimal(history_data.get("short_rally_pct", "0")),
                    short_rally_trough_date=history_data.get(
                        "short_rally_trough_date", ""
                    ),
                    short_rally_peak_date=history_data.get(
                        "short_rally_peak_date", ""
                    ),
                )
            raw_history_bars = item["history_bars"]
            if raw_history_bars:
                bars_to_restore[row_id] = tuple(
                    DailyBar(
                        bar["date"],
                        Decimal(bar["high"]),
                        Decimal(bar["low"]),
                        Decimal(bar["close"]),
                        (
                            Decimal(bar["spread_points"])
                            if bar.get("spread_points")
                            else None
                        ),
                        (
                            int(bar["spread_sample_count"])
                            if bar.get("spread_sample_count")
                            else None
                        ),
                        Decimal(bar["open"]) if bar.get("open") else None,
                    )
                    for bar in raw_history_bars
                )
            if item["history_source"]:
                sources_to_restore[row_id] = item["history_source"]
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
                values[5] = (
                    f"{format_decimal(quote_value[0])} {quote_value[1]} (saved)"
                )
                self.allocation_tree.item(row_id, values=values)

        self.contract_inputs.update(contracts_to_restore)
        self.historical_stresses.update(history_to_restore)
        self.history_bars.update(bars_to_restore)
        self.history_sources.update(sources_to_restore)
        self.saved_history_rows.update(history_to_restore)
        self.current_settings_row = None
        self.allocation_results.clear()
        selected_index = scenario["selected_allocation"]
        if selected_index is not None:
            if (
                isinstance(selected_index, bool)
                or not isinstance(selected_index, int)
                or not 0 <= selected_index < len(self.allocations)
            ):
                raise ValueError("Scenario selected allocation index is invalid.")
            selected_row = list(self.allocations)[selected_index]
            selected_label = next(
                label for label, row_id in self.selection_ids.items()
                if row_id == selected_row
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
            value = text_settings[name]
            if (
                not value
                and name in (
                    "point_value", "point_size", "contract_currency",
                    "lot_increment", "minimum_lot", "points_per_pip",
                )
                and selected_row in self.allocations
            ):
                value = self.contract_inputs.get(selected_row, {}).get(name, "")
            variable.set(value)
        for name, variable in self._scenario_boolean_settings().items():
            variable.set(option_settings[name])
        self._update_stress_input_states()
        self._update_robot_options()
        self.output_text.delete("1.0", "end")
        self._refresh_broker_symbol_choices()

    def _build_prop_account_tab(self) -> None:
        ttk.Button(
            self.prop_account_tab,
            text="Import prop rules from website...",
            command=self._open_prop_website_import,
        ).pack(anchor="w", pady=(0, 10))
        account = ttk.LabelFrame(
            self.prop_account_tab,
            text="Prop account and loss limits",
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

        ttk.Label(
            self.prop_account_tab,
            text=(
                "These account values and prop loss limits are saved automatically "
                "with your portfolio and restored when the application opens. "
                "Enter the limits from your firm's rules; no firm-specific rules "
                "are inferred automatically."
            ),
            wraplength=1050,
        ).pack(fill="x", pady=(4, 8))
        ttk.Label(
            self.prop_account_tab,
            text=f"Local JSON: {self.autosave_path}",
            wraplength=1050,
        ).pack(fill="x")
        ttk.Button(
            self.prop_account_tab,
            text="Configure robots in Portfolio",
            command=lambda: self.notebook.select(self.portfolio_tab),
        ).pack(anchor="w", pady=(12, 0))
        advanced_actions = ttk.Frame(self.prop_account_tab)
        advanced_actions.pack(fill="x", pady=6)
        ttk.Button(
            advanced_actions, text="Advanced prop, margin & swap...",
            command=self._open_advanced_risk,
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            advanced_actions, text="Evaluate MT5 equity CSV...",
            command=self._import_equity_curve,
        ).pack(side="left")
        ttk.Button(
            advanced_actions, text="Open saved equity report",
            command=self._open_saved_equity_report,
        ).pack(side="left", padx=8)
        self._build_spiceprop_reference()

    def _open_advanced_risk(self) -> None:
        window = tk.Toplevel(self)
        window.title("Explicit prop rules, margin and overnight costs")
        window.geometry("1000x760")
        window.transient(self)
        window.grab_set()
        enabled = tk.BooleanVar(value=self.risk_profile["enabled"])
        ttk.Checkbutton(
            window, text="Enable advanced constraints for candidate sizing and verdict",
            variable=enabled,
        ).pack(anchor="w", padx=12, pady=8)
        ttk.Label(
            window, wraplength=960,
            text=(
                "All cash values use the configured account currency. Enter verified rules; "
                "website imports do not infer these. Trailing equity is continuous, uncapped, "
                "with a fixed cash distance based on initial capital. Reset uses a FIXED UTC "
                "offset (no automatic DST). Zero swap must be explicitly verified. "
                "Margin per lot must be a conservative upper bound, not an inferred leverage."
            ),
        ).pack(fill="x", padx=12)
        tabs = ttk.Notebook(window)
        tabs.pack(fill="both", expand=True, padx=12, pady=8)
        rules = ttk.Frame(tabs, padding=8)
        exposures = ttk.Frame(tabs, padding=8)
        tabs.add(rules, text="Account rules")
        tabs.add(exposures, text="Per-robot exposure")
        labels = {
            "current_equity": "Current equity (cash)",
            "daily_start_equity": "Equity at today's reset",
            "daily_start_balance": "Balance at today's reset",
            "daily_session_date": "Reset session start date YYYY-MM-DD (refresh daily)",
            "daily_baseline": "Daily equity floor baseline",
            "overall_rule": "Overall drawdown rule",
            "total_limit_pct": "Overall loss % of initial capital",
            "high_water_equity": "High-water equity (trailing; at curve start for CSV)",
            "reset_time": "Daily reset HH:MM",
            "utc_offset_minutes": "Reset fixed UTC offset (minutes; e.g. 120)",
            "idea_limit_pct": "Max loss % per correlated idea",
            "free_margin": "Current free margin (cash)",
            "existing_margin": "Current used margin (cash)",
            "stopout_pct": "Broker stop-out margin level % (not cash mode)",
            "holding_days": "Swap charge-days (include triple-day/weekend weights)",
        }
        variables = {}
        for position, (field, label) in enumerate(labels.items()):
            variable = tk.StringVar(value=self.risk_profile[field])
            variables[field] = variable
            ttk.Label(rules, text=label).grid(row=position, column=0, sticky="w", pady=3)
            choices = (
                ("Equity", "Balance", "Higher of balance/equity")
                if field == "daily_baseline" else
                ("Static", "Trailing equity") if field == "overall_rule" else ()
            )
            widget = (
                ttk.Combobox(rules, textvariable=variable, values=choices, state="readonly")
                if choices else ttk.Entry(rules, textvariable=variable)
            )
            widget.grid(row=position, column=1, sticky="ew", padx=10)
        rules.columnconfigure(1, weight=1)
        ttk.Label(
            exposures, text="Assign the SAME idea group to correlated robots; blank is unverified."
        ).pack(anchor="w", pady=(0, 8))
        canvas = tk.Canvas(exposures, highlightthickness=0)
        scrollbar = ttk.Scrollbar(exposures, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        grid = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=grid, anchor="nw")
        grid.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        for column, label in enumerate((
            "Robot / allocation", "Idea group", "Margin / lot",
            "Long swap debit / lot / day", "Short swap debit / lot / day",
        )):
            ttk.Label(grid, text=label).grid(row=0, column=column, padx=5, pady=5)
        exposure_vars = {}
        for position, (row_id, allocation) in enumerate(self.allocations.items(), 1):
            ttk.Label(grid, text=f"{allocation.index}/{allocation.robot} [{row_id}]").grid(
                row=position, column=0, sticky="w"
            )
            values = self.exposure_inputs.get(row_id, default_exposure())
            row_vars = {}
            for column, field in enumerate((
                "idea_group", "margin_per_lot", "swap_long_debit", "swap_short_debit",
            ), 1):
                variable = tk.StringVar(value=values[field])
                row_vars[field] = variable
                ttk.Entry(grid, textvariable=variable, width=20).grid(
                    row=position, column=column, padx=4, pady=3
                )
            exposure_vars[row_id] = row_vars

        def apply() -> None:
            try:
                raw_profile = {key: variable.get() for key, variable in variables.items()}
                raw_profile["enabled"] = enabled.get()
                profile = validate_profile(raw_profile)
                inputs = {
                    row_id: validate_exposure({key: var.get() for key, var in row.items()})
                    for row_id, row in exposure_vars.items()
                    if row_id in self.allocations
                }
            except ValueError as error:
                messagebox.showerror("Advanced risk inputs", str(error), parent=window)
                return
            self.risk_profile = profile
            self.exposure_inputs = inputs
            self.generated_scenario = None
            self.generated_output = ""
            self.output_text.delete("1.0", "end")
            self._calculate_portfolio(show_error=False)
            self._schedule_autosave()
            self.status_var.set("Advanced risk inputs applied; regenerate estimates with the new assumptions.")
            window.destroy()

        ttk.Button(window, text="Apply and save with portfolio", command=apply).pack(pady=8)

    def _import_equity_curve(self) -> None:
        path = filedialog.askopenfilename(
            title="Sampled account equity CSV: timestamp,balance,equity",
            filetypes=(("Equity curve", "*.csv"),), parent=self,
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Confirm equity-curve assumptions",
            "Use only a single-account/tester curve in the configured account currency, "
            "without deposits or withdrawals. The initial account capital must be the "
            "original test/account balance. For trailing mode, high-water equity must "
            "be the value AT THE START of this curve.\n\n"
            "The CSV needs explicit timezone offsets and reset-time samples. It is "
            "not an automatically reconstructed equity curve from a trade/deal list.\n\n"
            "Have you verified these assumptions?",
            parent=self,
        ):
            return
        try:
            if os.path.getsize(path) > 10 * 1024 * 1024:
                raise ValueError("Equity CSV exceeds the 10 MiB limit.")
            with open(path, encoding="utf-8-sig") as file:
                samples = parse_equity_csv(file.read())
            report = self._evaluate_and_save_equity_curve(samples)
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror("Equity curve evaluation", str(error), parent=self)
            self.status_var.set(f"Equity curve evaluation failed: {error}")
            return
        self._show_equity_report(report)
        self.status_var.set(f"Sampled equity report saved locally: {self.equity_report_path}")

    def _show_equity_report(self, report: str) -> None:
        window = tk.Toplevel(self)
        window.title("Sampled MT5 equity validation")
        window.geometry("1000x650")
        text = tk.Text(window, wrap="word")
        scrollbar = ttk.Scrollbar(window, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", report)
        text.configure(state="disabled")

    def _open_saved_equity_report(self) -> None:
        try:
            with open(self.equity_report_path, encoding="utf-8") as file:
                snapshot = json.load(file)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("report"), str):
                raise ValueError("Saved equity report has an invalid format.")
            report = (
                f"OFFLINE SNAPSHOT evaluated at {snapshot.get('evaluated_at', 'unknown')}.\n"
                "This report retains its original rules/curve; it is NOT recalculated "
                "for today's inputs or current candidate settings.\n\n" + snapshot["report"]
            )
        except (OSError, ValueError) as error:
            messagebox.showerror("Saved equity report", str(error), parent=self)
            return
        self._show_equity_report(report)

    def _evaluate_and_save_equity_curve(self, samples: tuple[EquitySample, ...]) -> str:
        profile = validate_profile(self.risk_profile)
        capital = decimal_value(self.account_capital_var.get(), "Initial account capital")
        daily = decimal_value(self.daily_limit_var.get(), "Daily limit")
        if capital <= ZERO or daily <= ZERO:
            raise ValueError("Initial capital and daily limit must be positive.")
        if self.limit_mode_var.get() == "Percent of account":
            daily = capital * daily / ONE_HUNDRED
        if daily > capital:
            raise ValueError("Daily loss limit cannot exceed initial capital.")
        result = evaluate_equity_curve(samples, profile, capital, daily)
        verdict = "BREACHED" if result.breaches else "UNVERIFIED" if result.missing else "NO SAMPLED BREACH"
        report = "\n".join((
            f"SAMPLED EQUITY VERDICT: {verdict}",
            f"Currency: {self.currency_var.get()}",
            f"Initial capital: {capital}; baseline: {profile['daily_baseline']}; "
            f"overall rule: {profile['overall_rule']}; reset: {profile['reset_time']} "
            f"with fixed UTC offset {profile['utc_offset_minutes']} minutes.",
            *result.lines, *("UNVERIFIED: " + item for item in result.missing[:100]),
            *("BREACH: " + item for item in result.breaches[:100]),
            f"Counts: {len(result.missing)} missing reset/session checks; "
            f"{len(result.breaches)} sampled breach observations (up to 100 listed each).",
            "This evaluates the supplied curve, NOT the planner candidate settings. "
            "It neither runs the EA nor proves future prop compliance.",
        ))
        snapshot = {
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "currency": self.currency_var.get(), "initial_balance": str(capital),
            "daily_limit": str(daily), "risk_profile": dict(profile),
            "samples": [
                {"timestamp": sample.time.isoformat(), "balance": str(sample.balance),
                 "equity": str(sample.equity)}
                for sample in samples
            ],
            "report": report,
        }
        directory = os.path.dirname(self.equity_report_path)
        os.makedirs(directory, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as file:
                temporary_path = file.name
                json.dump(snapshot, file, indent=2)
            os.replace(temporary_path, self.equity_report_path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
        return report

    def _open_prop_website_import(self) -> None:
        if self.prop_import_window is not None and self.prop_import_window.winfo_exists():
            self.prop_import_window.lift()
            return
        window = tk.Toplevel(self)
        self.prop_import_window = window
        window.title("Import prop website - review required")
        window.geometry("1000x650")
        window.transient(self)
        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        self.prop_url_var = tk.StringVar(value="https://spiceprop.com/programs/sweet")
        ttk.Label(frame, text="Official program URL (HTTPS)").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.prop_url_var).pack(fill="x")
        ttk.Button(
            frame, text="Extract rules from URL", command=self._fetch_prop_website
        ).pack(anchor="w", pady=6)
        self.prop_preview_tree = ttk.Treeview(
            frame, columns=("stage", "daily", "total"), show="headings", height=5
        )
        for column, label in (
            ("stage", "Program / stage (verify)"),
            ("daily", "Daily %"), ("total", "Total %"),
        ):
            self.prop_preview_tree.heading(column, text=label)
        self.prop_preview_tree.pack(fill="x")
        self.prop_preview_tree.bind("<<TreeviewSelect>>", self._select_prop_rule)
        self.prop_evidence = tk.Text(frame, height=6, wrap="word", state="disabled")
        self.prop_evidence.pack(fill="both", expand=True, pady=6)
        fields = ttk.Frame(frame)
        fields.pack(fill="x")
        self.prop_daily_preview_var = tk.StringVar()
        self.prop_total_preview_var = tk.StringVar()
        for label, variable in (
            ("Confirmed daily %", self.prop_daily_preview_var),
            ("Confirmed total %", self.prop_total_preview_var),
        ):
            ttk.Label(fields, text=label).pack(side="left", padx=4)
            ttk.Entry(fields, textvariable=variable, width=10).pack(side="left")
        self.prop_reviewed_var = tk.BooleanVar(value=False)
        self.prop_new_account_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="I verified the program, stage, account size/currency and limits on the official site.",
            variable=self.prop_reviewed_var,
        ).pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(
            frame,
            text="New account: no losses or open positions; use full nominal loss room.",
            variable=self.prop_new_account_var,
        ).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "Capital/currency come from the Prop firm & account tab: verify them first. "
                "For existing accounts, enter actual remaining daily AND overall cash room "
                "there before applying. Only daily/total caps are imported. Trailing equity, "
                "reset timezone, EA bans, correlated-idea risk and other firm rules are NOT "
                "validated. No universal website parser or verified EA preset is implied."
            ),
            wraplength=940,
        ).pack(fill="x", pady=6)
        ttk.Button(
            frame, text="Apply confirmed limits", command=self._apply_prop_website_rules
        ).pack(anchor="w")
        ttk.Button(
            frame, text="Apply limits + suggest robot settings",
            command=lambda: self._apply_prop_website_rules(suggest=True),
        ).pack(anchor="w", pady=4)
        if self.prop_website_snapshot is None:
            path = os.path.join(APP_DATA_DIRECTORY, PROP_WEBSITE_FILE_NAME)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8") as file:
                        snapshot = json.load(file)
                    self.prop_website_snapshot = self._validate_prop_website_snapshot(snapshot)
                except (OSError, UnicodeError, ValueError) as error:
                    messagebox.showwarning(
                        "Saved website rules", f"Could not load saved rules: {error}",
                        parent=window,
                    )
        self._display_prop_website_snapshot()

    @staticmethod
    def _validate_prop_website_snapshot(snapshot: object) -> PropWebsiteSnapshot:
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid saved website reference.")

        def text(mapping: dict, key: str) -> str:
            value = mapping.get(key)
            if not isinstance(value, str):
                raise ValueError(f"Saved website field {key} must be text.")
            return value

        source = text(snapshot, "source")
        fetched_at = text(snapshot, "fetched_at")
        candidates = snapshot.get("candidates")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 100:
            raise ValueError("Invalid saved website rule rows.")
        normalized: list[PropRuleCandidate] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Invalid saved website rule.")
            row: PropRuleCandidate = {
                "stage": text(candidate, "stage"),
                "daily_percent": text(candidate, "daily_percent"),
                "total_percent": text(candidate, "total_percent"),
                "evidence": text(candidate, "evidence"),
            }
            daily = decimal_value(row["daily_percent"], "Daily percentage")
            total = decimal_value(row["total_percent"], "Total percentage")
            if not ZERO < daily <= total < ONE_HUNDRED:
                raise ValueError("Saved rule percentages are invalid.")
            normalized.append(row)
        return {"source": source, "fetched_at": fetched_at, "candidates": normalized}

    def _display_prop_website_snapshot(self) -> None:
        if (
            self.prop_website_snapshot is None or self.prop_import_window is None
            or not self.prop_import_window.winfo_exists()
        ):
            return
        snapshot = self.prop_website_snapshot
        self.prop_url_var.set(snapshot["source"])
        self.prop_preview_tree.delete(*self.prop_preview_tree.get_children())
        self.prop_daily_preview_var.set("")
        self.prop_total_preview_var.set("")
        self.prop_reviewed_var.set(False)
        self.prop_new_account_var.set(False)
        for index, row in enumerate(snapshot["candidates"]):
            self.prop_preview_tree.insert(
                "", "end", iid=str(index),
                values=(row["stage"], row["daily_percent"], row["total_percent"]),
            )
        self.prop_evidence.configure(state="normal")
        self.prop_evidence.delete("1.0", "end")
        self.prop_evidence.insert(
            "1.0", f"Source: {snapshot['source']}\nFetched: {snapshot['fetched_at']}\n"
            "Select a row to view evidence. Extraction is unverified."
        )
        self.prop_evidence.configure(state="disabled")

    def _select_prop_rule(self, _event: object = None) -> None:
        selected = self.prop_preview_tree.selection()
        if not selected or self.prop_website_snapshot is None:
            return
        row = self.prop_website_snapshot["candidates"][int(selected[0])]
        self.prop_daily_preview_var.set(row["daily_percent"])
        self.prop_total_preview_var.set(row["total_percent"])
        self.prop_reviewed_var.set(False)
        self.prop_evidence.configure(state="normal")
        self.prop_evidence.delete("1.0", "end")
        self.prop_evidence.insert(
            "1.0", f"Source: {self.prop_website_snapshot['source']}\n"
            f"Fetched: {self.prop_website_snapshot['fetched_at']}\n{row['evidence']}"
        )
        self.prop_evidence.configure(state="disabled")

    def _fetch_prop_website(self) -> None:
        if self.quote_busy:
            self.status_var.set("Wait for the current data request to finish.")
            return
        url = self.prop_url_var.get()
        self.prop_reviewed_var.set(False)
        self.prop_preview_tree.selection_remove(self.prop_preview_tree.selection())
        self._set_fetch_busy(True)
        self.status_var.set("Extracting program website tables; review will be required...")

        def worker() -> None:
            try:
                result = fetch_prop_website(url)
            except (ValueError, OSError) as error:
                result = str(error)
            self.quote_messages.put(("__prop__", "prop_website_done", result))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _apply_prop_website_rules(self, suggest: bool = False) -> None:
        try:
            if self.quote_busy:
                raise ValueError("Wait for the data request to finish before applying rules.")
            if not self.prop_reviewed_var.get() or not self.prop_preview_tree.selection():
                raise ValueError("Select a row and confirm that you verified its rules.")
            daily = decimal_value(self.prop_daily_preview_var.get(), "Daily percentage")
            total = decimal_value(self.prop_total_preview_var.get(), "Total percentage")
            capital = decimal_value(self.account_capital_var.get(), "Account capital")
            if capital <= ZERO or not ZERO < daily <= total < ONE_HUNDRED:
                raise ValueError("Capital must be positive; require 0 < daily <= total < 100%.")
            if not self.currency_var.get().strip():
                raise ValueError("Confirm the account currency first.")
            daily_cash = capital * daily / ONE_HUNDRED
            total_cash = capital * total / ONE_HUNDRED
            if not self.prop_new_account_var.get():
                remaining_daily = decimal_value(
                    self.remaining_daily_loss_room_var.get(), "Remaining daily room"
                )
                remaining_total = decimal_value(
                    self.prop_total_loss_room_var.get(), "Remaining total room"
                )
                if not (
                    ZERO < remaining_daily <= daily_cash
                    and ZERO < remaining_total <= total_cash
                ):
                    raise ValueError(
                        "Enter positive actual remaining rooms no larger than nominal limits."
                    )
            if not messagebox.askyesno(
                "Apply reviewed prop limits",
                f"Apply daily {daily}% and total {total}% to capital {capital} "
                f"{self.currency_var.get()}?\nOnly the modeled loss caps are imported. "
                "This does not verify all firm rules or robot compliance.",
                parent=self.prop_import_window,
            ):
                return
            self.daily_limit_var.set(str(daily))
            self.limit_mode_var.set("Percent of account")
            if self.prop_new_account_var.get():
                self.remaining_daily_loss_room_var.set(str(daily_cash))
                self.prop_total_loss_room_var.set(str(total_cash))
            self.generated_scenario = None
            self.generated_output = ""
            self.output_text.delete("1.0", "end")
            self._calculate_portfolio(show_error=False)
            self._schedule_autosave()
            self.prop_import_window.destroy()
            self.status_var.set(
                "Reviewed prop caps applied. Configure robots, contract specs and "
                "history, then use Suggest all robots. Full firm compliance is not verified."
            )
            if suggest:
                self._suggest_portfolio_downside()
        except ValueError as error:
            messagebox.showerror("Prop website rules", str(error), parent=self.prop_import_window)

    def _build_spiceprop_reference(self) -> None:
        reference = SPICEPROP_SWEET_REFERENCE
        box = ttk.LabelFrame(
            self.prop_account_tab,
            text=f"{reference['program']} - saved offline reference",
            padding=8,
        )
        box.pack(fill="x", pady=(12, 0))
        ttk.Label(
            box,
            text=(
                f"Verified: {reference['verified_on']}. Account sizes (EUR): "
                + ", ".join(str(size) for size in reference["account_sizes"])
                + ". 1000 EUR is NOT offered by this program."
            ),
            wraplength=1050,
        ).pack(fill="x")
        columns = ("capital", "phase", "daily", "total", "target")
        self.spiceprop_reference_tree = ttk.Treeview(
            box, columns=columns, show="headings", height=3, selectmode="none"
        )
        for column, title in zip(
            columns,
            ("Capital", "Stage", "Daily loss limit", "Total loss limit", "Profit target"),
        ):
            self.spiceprop_reference_tree.heading(column, text=title)
            self.spiceprop_reference_tree.column(column, width=180, anchor="w")
        capital = Decimal("25000")

        def limit_text(percent: str) -> str:
            cash = capital * Decimal(percent) / ONE_HUNDRED
            return f"{percent}% / {cash:f} EUR"

        for phase, daily, total, target in reference["phases"]:
            self.spiceprop_reference_tree.insert(
                "", "end",
                values=(
                    "25000 EUR", phase, limit_text(daily), limit_text(total),
                    limit_text(target) if target is not None else "No evaluation target",
                ),
            )
        self.spiceprop_reference_tree.pack(fill="x", pady=5)
        ttk.Label(
            box,
            text=(
                f"Funded: max {reference['funded_idea_risk_percent']}% risk per trading "
                "idea, including correlated exposures. This rule is NOT checked by "
                "the planner. Daily reset and firm-specific equity rules are NOT "
                "implemented. The site states 23:59:59 'CET (UTC+2)'; confirm the "
                "actual timezone with the firm. Nominal limits assume no losses; "
                "enter actual remaining room for an existing account. Reference "
                "only: it does not overwrite your account or certify compliance. "
                "Rules can change; confirm them before trading.\n"
                f"Sources: {reference['source']}\n{reference['rules_source']}"
            ),
            wraplength=1050,
        ).pack(fill="x")

    def _build_portfolio_tab(self) -> None:
        ttk.Label(
            self.portfolio_tab,
            text=(
                "Account capital, currency and prop loss limits are configured in "
                "the Prop firm & account tab. Enter each robot as a percentage "
                "of account capital; percentages may total up to 100%."
            ),
            wraplength=1050,
        ).pack(fill="x", pady=(0, 10))
        entry_box = ttk.LabelFrame(
            self.portfolio_tab,
            text="Add an index / robot allocation",
            style="Section.TLabelframe",
            padding=10,
        )
        entry_box.pack(fill="x", pady=(0, 10))
        self.index_var = tk.StringVar(value="")
        self.yahoo_ticker_var = tk.StringVar(value="")
        self.auto_yahoo_ticker = ""
        self.index_var.trace_add("write", self._suggest_yahoo_ticker)
        self.robot_var = tk.StringVar(value="RSI")
        self.capital_var = tk.StringVar(value="5000")
        self.allocation_pct_var = tk.StringVar(value="50")
        for column, (label, variable, width) in enumerate(
            (
                ("Broker symbol", self.index_var, 13),
                ("Yahoo ticker", self.yahoo_ticker_var, 13),
                ("Robot", self.robot_var, 10),
                ("Account allocation (%)", self.allocation_pct_var, 14),
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
            elif label == "Broker symbol":
                self.broker_symbol_combo = ttk.Combobox(
                    entry_box,
                    textvariable=variable,
                    values=(variable.get(),),
                    state="readonly",
                    width=width,
                )
                self.broker_symbol_combo.grid(
                    row=0, column=column * 2 + 1, sticky="w", padx=(0, 12)
                )
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
        columns = (
            "symbol",
            "ticker",
            "robot",
            "capital",
            "allocation_pct",
            "quote",
            "daily",
        )
        self.allocation_tree = ttk.Treeview(
            table_box, columns=columns, show="headings", height=9, selectmode="browse"
        )
        headings = {
            "symbol": "Broker symbol",
            "ticker": "Yahoo ticker",
            "robot": "Robot",
            "capital": "Capital",
            "allocation_pct": "Account %",
            "quote": "Market reference price",
            "daily": "Daily robot budget",
        }
        widths = {
            "symbol": 130,
            "ticker": 130,
            "robot": 85,
            "capital": 120,
            "allocation_pct": 90,
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
        self.fetch_mt5_button = ttk.Button(
            actions,
            text="Connect MT5: get specs + 5y D1",
            command=self._fetch_mt5_terminal_data,
        )
        self.fetch_mt5_button.pack(side="left", padx=8)
        ttk.Button(
            self.portfolio_tab, text="Data status", command=self._show_data_status
        ).pack(anchor="w", pady=4)
        terminal_box = ttk.LabelFrame(self.portfolio_tab, text="MT5 connection", padding=6)
        terminal_box.pack(fill="x", pady=4)
        ttk.Label(terminal_box, text="Terminal .exe (empty = automatic):").pack(side="left")
        ttk.Entry(
            terminal_box, textvariable=self.mt5_terminal_path_var, width=40,
            state="readonly",
        ).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(
            terminal_box, text="Choose...", command=self._choose_mt5_terminal
        ).pack(side="left", padx=3)
        ttk.Button(
            terminal_box, text="Automatic",
            command=self._use_automatic_mt5_terminal,
        ).pack(side="left", padx=3)
        self.inspect_mt5_button = ttk.Button(
            terminal_box, text="Inspect terminal / symbols",
            command=self._inspect_mt5_terminal,
        )
        self.inspect_mt5_button.pack(side="left", padx=3)
        ttk.Label(
            actions,
            text=f"Auto-saved JSON: {self.autosave_path}",
            wraplength=470,
        ).pack(side="right", padx=6)
        ttk.Button(
            actions,
            text="Calculate portfolio budgets",
            command=self._calculate_portfolio,
        ).pack(side="right")
        ttk.Label(
            self.portfolio_tab,
            text=(
                "Use Inspect terminal / symbols to populate Broker symbol with "
                "the broker's available symbols. Selecting and fetching a symbol "
                "stores its contract and history in its own data folder. Yahoo "
                "tickers may differ from broker CFD names."
            ),
            wraplength=1080,
        ).pack(fill="x", pady=(7, 0))
        ttk.Label(
            self.portfolio_tab,
            text=(
                "Use Connect MT5 to read account currency, broker contract specs, "
                "current price and 5 years of D1 bars directly from the logged-in "
                "terminal (requires the MetaTrader5 Python package). Contract "
                "inputs can also be entered manually in Robot settings. "
                "Fetch daily history to size fixed lots against each symbol's "
                "largest peak-to-trough decline; daily shock remains available "
                "as a separate stress mode. Yahoo remains the fallback when "
                "broker history is unavailable."
            ),
            wraplength=1080,
        ).pack(fill="x", pady=(3, 0))

    def _data_status_text(self) -> str:
        lines = [
            "MARKET DATA STATUS",
            "Requested window: 5 years. Actual coverage is shown per allocation.",
            "No terminal/server identity is stored in legacy snapshots. Verify "
            "the active broker/server in MT5; equal specs do not prove equal brokers.",
            "",
        ]
        if self.mt5_connection:
            lines.append("CURRENT SESSION MT5 INSPECTION (not a saved account snapshot)")
            lines.extend(
                f"{key}: {value}"
                for key, value in self.mt5_connection.items()
                if key not in ("symbols", "symbol_catalog")
            )
            lines.extend(("", "AVAILABLE BROKER SYMBOLS:", self.mt5_connection["symbols"], ""))
        for row_id, allocation in self.allocations.items():
            contract = self._contract_inputs_for_allocation(row_id)
            stress = self.historical_stresses.get(row_id)
            lines.append(
                f"{row_id} | {allocation.index} | {allocation.robot} | "
                f"source: {self.history_sources.get(row_id) or 'not loaded'}"
            )
            quote = self.quotes.get(row_id)
            lines.append(
                f"Quote: {quote[0]} {quote[1]} ({quote[3]})"
                if quote else "Quote: MISSING"
            )
            if stress:
                lines.append(
                    f"History: {stress.start_date} to {stress.end_date}; "
                    f"{stress.bar_count} daily bars"
                )
                lines.extend(f"WARNING: {item}" for item in history_quality_warnings(stress))
            else:
                lines.append("History: MISSING")
            required = (
                "point_value", "point_size", "lot_increment", "minimum_lot",
                "contract_currency",
            )
            missing = [field for field in required if not contract.get(field)]
            lines.append("Missing contract fields: " + (", ".join(missing) or "none"))
            lines.append(
                "EA points per pip: " + (contract.get("points_per_pip") or "MISSING")
            )
            lines.append(
                "Round-turn commission per lot: "
                + (contract.get("commission_per_lot") or
                   f"shared fallback {self.commission_per_lot_var.get()} (verify manually)")
            )
            currency = contract.get("contract_currency", "")
            if currency.upper() != self.currency_var.get().strip().upper():
                lines.append("WARNING: contract/account currencies do not match.")
            if row_id in self.cached_data_warnings:
                lines.append(f"Refresh warning: {self.cached_data_warnings[row_id]}")
            lines.append("")
        return "\n".join(lines)

    def _show_data_status(self) -> None:
        window = tk.Toplevel(self)
        window.title("Market data status")
        window.geometry("950x600")
        symbols = self.mt5_connection.get("symbols", "").splitlines()
        if symbols:
            chooser = ttk.Frame(window, padding=6)
            chooser.pack(fill="x")
            ttk.Label(chooser, text="MT5 symbol for a NEW allocation:").pack(side="left")
            selected = tk.StringVar(value=symbols[0])
            ttk.Combobox(
                chooser, textvariable=selected, values=symbols, height=12, width=35
            ).pack(side="left", padx=8)
            ttk.Button(
                chooser, text="Use in Portfolio",
                command=lambda: self._use_mt5_symbol(selected.get()),
            ).pack(side="left")
        text = tk.Text(window, wrap="word")
        scrollbar = ttk.Scrollbar(window, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.insert("1.0", self._data_status_text())
        text.configure(state="disabled")

    def _symbol_data_directory(self, symbol: str) -> str:
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("Broker symbol cannot be empty.")
        folder_name = quote(symbol, safe="._-")
        if folder_name in (".", ".."):
            folder_name = "%2E" * len(folder_name)
        return os.path.join(os.path.dirname(self.autosave_path), folder_name)

    @staticmethod
    def _write_symbol_cache_file(path: str, content: dict[str, object]) -> None:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".symbol-", suffix=".tmp", dir=directory, text=True
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as cache_file:
                json.dump(content, cache_file, ensure_ascii=False, indent=2)
                cache_file.write("\n")
            os.replace(temporary_path, path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _save_symbol_market_data(self, scenario: dict[str, object]) -> bool:
        allocations = scenario.get("allocations", [])
        if not isinstance(allocations, list):
            return False
        pending: dict[str, dict[str, object]] = {}
        contract_fields = (
            "point_value", "point_size", "lot_increment", "minimum_lot",
            "maximum_lot", "contract_currency",
        )
        for allocation in allocations:
            if not isinstance(allocation, dict):
                continue
            symbol = allocation.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                continue
            update = pending.setdefault(
                symbol,
                {
                    "quote": None,
                    "broker_contract": {},
                    "historical_stress": None,
                    "history_source": "",
                    "history_bars": [],
                },
            )
            if allocation.get("quote") is not None:
                update["quote"] = allocation["quote"]
            stress = allocation.get("historical_stress")
            if stress is not None:
                update["historical_stress"] = stress
            source = allocation.get("history_source", "")
            if isinstance(source, str) and source:
                update["history_source"] = source
            bars = allocation.get("history_bars", [])
            if isinstance(bars, list) and bars:
                update["history_bars"] = bars
            contract = allocation.get("broker_contract", {})
            if isinstance(contract, dict):
                market_contract = update["broker_contract"]
                for field in contract_fields:
                    value = contract.get(field, "")
                    if isinstance(value, str) and value.strip():
                        market_contract[field] = value

        success = True
        for symbol, update in pending.items():
            try:
                folder = self._symbol_data_directory(symbol)
                market_path = os.path.join(folder, "market_data.json")
                existing_market: dict[str, object] = {}
                if os.path.isfile(market_path):
                    try:
                        with open(market_path, "r", encoding="utf-8") as market_file:
                            cached = json.load(market_file)
                        if (
                            isinstance(cached, dict)
                            and cached.get("format") == "mt5-risk-planner-symbol-data"
                            and cached.get("symbol") == symbol
                        ):
                            existing_market = cached
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        pass
                market_contract = existing_market.get("broker_contract", {})
                merged_contract = (
                    dict(market_contract) if isinstance(market_contract, dict) else {}
                )
                update_contract = update.get("broker_contract", {})
                if isinstance(update_contract, dict):
                    merged_contract.update(update_contract)
                market_data = {
                    "format": "mt5-risk-planner-symbol-data",
                    "version": 1,
                    "symbol": symbol,
                    "quote": update.get("quote") or existing_market.get("quote"),
                    "broker_contract": merged_contract,
                    "historical_stress": (
                        update.get("historical_stress")
                        or existing_market.get("historical_stress")
                    ),
                    "history_source": (
                        update.get("history_source")
                        or existing_market.get("history_source", "")
                    ),
                    "history_bars": (
                        update.get("history_bars")
                        or existing_market.get("history_bars", [])
                    ),
                }
                self._write_symbol_cache_file(
                    market_path, market_data
                )
                catalog_path = os.path.join(folder, "symbol.json")
                catalog: dict[str, object] = {}
                if os.path.isfile(catalog_path):
                    try:
                        with open(catalog_path, "r", encoding="utf-8") as catalog_file:
                            cached = json.load(catalog_file)
                        if isinstance(cached, dict):
                            catalog = cached
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        pass
                catalog.update(self.mt5_symbol_catalog.get(symbol, {}))
                catalog.update(
                    {
                        "symbol": symbol,
                        "available_in_mt5": bool(
                            catalog.get("available_in_mt5", False)
                        ),
                        "quote": market_data["quote"],
                        "broker_contract": merged_contract,
                        "history_source": market_data["history_source"],
                        "history_bar_count": (
                            market_data["historical_stress"].get("bar_count", 0)
                            if isinstance(market_data["historical_stress"], dict) else 0
                        ),
                    }
                )
                self._write_symbol_cache_file(catalog_path, catalog)
            except (OSError, ValueError) as error:
                success = False
                self.status_var.set(
                    f"Portfolio saved; symbol cache for {symbol} failed: {error}"
                )
        return success

    @staticmethod
    def _compact_autosave_scenario(
        scenario: dict[str, object],
    ) -> dict[str, object]:
        compact = dict(scenario)
        compact["version"] = 15
        allocations = scenario.get("allocations", [])
        if not isinstance(allocations, list):
            raise ValueError("Scenario allocations must be a list.")
        compact_allocations = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                raise ValueError("Scenario allocations must contain objects.")
            item = dict(allocation)
            contract = item.get("broker_contract", {})
            if not isinstance(contract, dict):
                contract = {}
            item["broker_contract"] = {
                field: contract[field]
                for field in ("points_per_pip", "commission_per_lot")
                if isinstance(contract.get(field), str) and contract[field].strip()
            }
            for market_field in (
                "quote", "historical_stress", "history_source", "history_bars"
            ):
                item.pop(market_field, None)
            compact_allocations.append(item)
        compact["allocations"] = compact_allocations
        settings = compact.get("settings")
        if isinstance(settings, dict):
            text_settings = settings.get("text")
            if isinstance(text_settings, dict):
                compact_text = dict(text_settings)
                for field in (
                    "point_value", "point_size", "contract_currency",
                    "lot_increment", "minimum_lot", "points_per_pip",
                ):
                    compact_text.pop(field, None)
                compact_settings = dict(settings)
                compact_settings["text"] = compact_text
                compact["settings"] = compact_settings
        return compact

    def _restore_symbol_market_data(
        self, scenario: dict[str, object]
    ) -> dict[str, object]:
        restored = dict(scenario)
        allocations = scenario.get("allocations", [])
        if not isinstance(allocations, list):
            return restored
        restored_allocations = []
        for allocation in allocations:
            if not isinstance(allocation, dict):
                restored_allocations.append(allocation)
                continue
            item = dict(allocation)
            symbol = item.get("symbol")
            if isinstance(symbol, str) and symbol.strip():
                cache_path = os.path.join(
                    self._symbol_data_directory(symbol), "market_data.json"
                )
                try:
                    with open(cache_path, "r", encoding="utf-8") as cache_file:
                        cached = json.load(cache_file)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    cached = None
                if (
                    isinstance(cached, dict)
                    and cached.get("format") == "mt5-risk-planner-symbol-data"
                    and cached.get("symbol") == symbol
                ):
                    cached_contract = cached.get("broker_contract")
                    saved_contract = item.get("broker_contract", {})
                    if isinstance(cached_contract, dict):
                        merged_contract = dict(saved_contract) if isinstance(
                            saved_contract, dict
                        ) else {}
                        merged_contract.update(cached_contract)
                        for override in ("points_per_pip", "commission_per_lot"):
                            saved_value = (
                                saved_contract.get(override, "")
                                if isinstance(saved_contract, dict) else ""
                            )
                            if isinstance(saved_value, str) and saved_value.strip():
                                merged_contract[override] = saved_value
                        item["broker_contract"] = merged_contract
                    for field in (
                        "quote", "historical_stress", "history_source", "history_bars"
                    ):
                        cached_value = cached.get(field)
                        if field == "history_bars" and not cached_value:
                            continue
                        if field == "history_source" and not cached_value:
                            continue
                        if cached_value is not None:
                            item[field] = cached_value
            restored_allocations.append(item)
        restored["allocations"] = restored_allocations
        return restored

    def _save_symbol_timeframe_charts(
        self, symbol: str, timeframe_charts: dict[str, list[dict[str, str]]] | None
    ) -> None:
        if not timeframe_charts:
            return
        try:
            symbol_directory = self._symbol_data_directory(symbol)
            charts_directory = os.path.join(symbol_directory, "charts")
            counts: dict[str, int] = {}
            for timeframe, bars in timeframe_charts.items():
                if not bars:
                    continue
                filename = quote(timeframe, safe="") + ".json"
                self._write_symbol_cache_file(
                    os.path.join(charts_directory, filename),
                    {
                        "format": "mt5-risk-planner-timeframe-chart",
                        "version": 1,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "bar_count": len(bars),
                        "bars": bars,
                    },
                )
                counts[timeframe] = len(bars)
            if counts:
                catalog_path = os.path.join(symbol_directory, "symbol.json")
                catalog: dict[str, object] = {"symbol": symbol}
                if os.path.isfile(catalog_path):
                    try:
                        with open(catalog_path, "r", encoding="utf-8") as catalog_file:
                            cached = json.load(catalog_file)
                        if isinstance(cached, dict):
                            catalog = cached
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        pass
                previous_counts = catalog.get("timeframe_bar_counts", {})
                if not isinstance(previous_counts, dict):
                    previous_counts = {}
                previous_counts.update(counts)
                catalog["timeframe_bar_counts"] = previous_counts
                catalog["collected_timeframes"] = sorted(previous_counts)
                self._write_symbol_cache_file(catalog_path, catalog)
        except (OSError, ValueError) as error:
            self.status_var.set(
                f"Market data saved; timeframe chart cache for {symbol} failed: {error}"
            )

    def _refresh_broker_symbol_choices(
        self, register_terminal_symbols: bool = False
    ) -> None:
        symbols = set(self.mt5_connection.get("symbols", "").splitlines())
        symbols.update(
            allocation.index for allocation in self.allocations.values()
        )
        try:
            with os.scandir(os.path.dirname(self.autosave_path)) as directory_entries:
                entries = list(directory_entries)
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir():
                continue
            if any(
                os.path.isfile(os.path.join(entry.path, file_name))
                for file_name in ("symbol.json", "market_data.json")
            ):
                cached_symbol = unquote(entry.name).strip()
                if cached_symbol:
                    symbols.add(cached_symbol)
        current_symbol = self.index_var.get().strip()
        if current_symbol:
            symbols.add(current_symbol)
        terminal_symbols = self.mt5_connection.get("symbols", "").splitlines()
        if register_terminal_symbols:
            for symbol in terminal_symbols:
                try:
                    folder = self._symbol_data_directory(symbol)
                    catalog_path = os.path.join(folder, "symbol.json")
                    existing: dict[str, object] = {}
                    if os.path.isfile(catalog_path):
                        try:
                            with open(catalog_path, "r", encoding="utf-8") as catalog_file:
                                cached = json.load(catalog_file)
                            if isinstance(cached, dict):
                                existing = cached
                        except (OSError, UnicodeError, json.JSONDecodeError):
                            pass
                    existing.update(self.mt5_symbol_catalog.get(symbol, {}))
                    existing.update(
                        {"symbol": symbol, "available_in_mt5": True}
                    )
                    self._write_symbol_cache_file(catalog_path, existing)
                except (OSError, ValueError):
                    continue
        if self.broker_symbol_combo is not None:
            self.broker_symbol_combo.configure(
                values=tuple(sorted(symbols, key=str.casefold))
            )

    def _use_mt5_symbol(self, symbol: str) -> None:
        if symbol not in self.mt5_connection.get("symbols", "").splitlines():
            messagebox.showerror(
                "MT5 symbol", "Select an exact symbol returned by the inspected terminal.",
                parent=self,
            )
            return
        self.index_var.set(symbol)
        self.notebook.select(self.portfolio_tab)
        self.status_var.set(
            f"Selected {symbol} for a new allocation. Choose robot/percentage and Add; "
            "existing allocations were not changed."
        )

    def _load_mt5_config(self) -> None:
        if not os.path.isfile(self.mt5_config_path):
            return
        try:
            with open(self.mt5_config_path, encoding="utf-8") as file:
                config = json.load(file)
            if not isinstance(config, dict) or not isinstance(config.get("terminal_path"), str):
                raise ValueError("MT5 configuration requires a terminal_path string.")
            self.mt5_terminal_path_var.set(config["terminal_path"])
        except (OSError, ValueError) as error:
            messagebox.showwarning("MT5 configuration", str(error), parent=self)

    def _save_mt5_config(self) -> None:
        path = self.mt5_terminal_path_var.get().strip()
        if path and (not os.path.isfile(path) or not path.lower().endswith(".exe")):
            raise ValueError("Choose the installed MT5 terminal .exe, or leave the path empty.")
        directory = os.path.dirname(self.mt5_config_path)
        os.makedirs(directory, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=directory, delete=False
            ) as file:
                temporary_path = file.name
                json.dump({"terminal_path": path}, file, indent=2)
            os.replace(temporary_path, self.mt5_config_path)
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def _choose_mt5_terminal(self) -> None:
        if self.quote_busy:
            self.status_var.set("Wait for the current request before changing terminals.")
            return
        path = filedialog.askopenfilename(
            title="Select MT5 terminal executable",
            filetypes=[("MT5 terminal", "*.exe")], parent=self,
        )
        if path:
            self.mt5_terminal_path_var.set(path)
            self.mt5_connection.clear()
            try:
                self._save_mt5_config()
            except (OSError, ValueError) as error:
                messagebox.showerror("MT5 configuration", str(error), parent=self)

    def _use_automatic_mt5_terminal(self) -> None:
        if self.quote_busy:
            self.status_var.set("Wait for the current request before changing terminals.")
            return
        self.mt5_terminal_path_var.set("")
        self.mt5_connection.clear()
        try:
            self._save_mt5_config()
        except (OSError, ValueError) as error:
            messagebox.showerror("MT5 configuration", str(error), parent=self)

    def _inspect_mt5_terminal(self) -> None:
        if self.quote_busy:
            return
        try:
            self._save_mt5_config()
        except (OSError, ValueError) as error:
            messagebox.showerror("MT5 configuration", str(error), parent=self)
            return
        path = self.mt5_terminal_path_var.get().strip()
        symbols = tuple(allocation.index for allocation in self.allocations.values())
        self._set_fetch_busy(True)
        self.status_var.set("Reading MT5 terminal identity and available symbols...")

        def worker() -> None:
            try:
                data = inspect_mt5_terminal(path, requested_symbols=symbols)
                result = MT5InspectionResult(data)
            except (
                ValueError, OSError, TypeError, AttributeError, RuntimeError,
                InvalidOperation, OverflowError,
            ) as error:
                result = MT5InspectionResult({}, str(error))
            self.quote_messages.put(("__mt5_status__", "mt5_status_done", result))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _build_settings_tab(self) -> None:
        top = ttk.LabelFrame(
            self.settings_tab,
            text="Select robot and market reference price",
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
        self.stress_mode_var = tk.StringVar(value=HISTORICAL_DRAWDOWN_MODE)
        self.stress_target_price_var = tk.StringVar()
        self.position_direction_var = tk.StringVar(value="Long (price falls)")
        self.stress_pct_var.trace_add("write", self._stress_percent_changed)
        self.lot_step_var = tk.StringVar()
        self.minimum_lot_var = tk.StringVar()
        self.maximum_lot_var = tk.StringVar()
        self.symbol_commission_per_lot_var = tk.StringVar()
        self.spread_points_var = tk.StringVar(value="0")
        self.slippage_points_var = tk.StringVar(value="0")
        self.commission_per_lot_var = tk.StringVar(value="0")
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
                HISTORICAL_DRAWDOWN_MODE,
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
        self._add_entry(market, 11, "Broker maximum lot per order (optional)", self.maximum_lot_var, 35)
        self._add_entry(market, 12, "Max Trades candidates to compare (1-20)", self.compare_trades_var, 35)
        self._add_entry(market, 13, "Max Trades to output", self.selected_trades_var, 35)
        ttk.Label(market, text="Point-value currency (account currency)").grid(
            row=14, column=0, sticky="w", pady=3
        )
        ttk.Entry(
            market, textvariable=self.contract_currency_var, width=35, state="readonly"
        ).grid(row=14, column=1, sticky="ew", pady=3)
        self._add_entry(
            market,
            15,
            "Minimum spread (MT5 points)",
            self.spread_points_var,
            35,
        )
        self._add_entry(
            market,
            16,
            "Slippage allowance (MT5 points per trade)",
            self.slippage_points_var,
            35,
        )
        self._add_entry(
            market,
            17,
            "Fallback round-turn commission per 1.00 lot",
            self.commission_per_lot_var,
            35,
        )
        self._add_entry(
            market,
            18,
            "Symbol override commission per 1.00 lot (optional)",
            self.symbol_commission_per_lot_var,
            35,
        )

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
            values=("break Below", "break above"),
            state="readonly",
            width=33,
        ).grid(row=1, column=1, sticky="ew", pady=3)
        self._add_entry(dca, 2, "Reference Price", self.reference_price_var, 35)
        ttk.Checkbutton(
            dca, text="Trade on new candle", variable=self.trade_new_candle_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(dca, text="Show Invested Money: true").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=3
        )

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
            text="Suggest all robots (historical drawdown)",
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
        ttk.Button(
            buttons,
            text="Export .set template",
            command=self._export_set_template,
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
        symbol = self.index_var.get().strip()
        if not symbol:
            return
        self._insert_allocation(
            symbol,
            self.yahoo_ticker_var.get().strip(),
            self.robot_var.get(),
            self.capital_var.get(),
            self.allocation_pct_var.get(),
        )

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
        allocation_percent_text: str | None = None,
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
        allocation_percent = None
        if allocation_percent_text is not None:
            allocation_percent = decimal_value(
                allocation_percent_text, "Account allocation percentage"
            )
            if not ZERO < allocation_percent <= ONE_HUNDRED:
                raise ValueError(
                    "Account allocation percentage must be greater than 0 and "
                    "no greater than 100."
                )
            total_percentage = allocation_percent + sum(
                (
                    percentage
                    for percentage in self.allocation_percentages.values()
                    if percentage is not None
                ),
                ZERO,
            )
            if total_percentage > ONE_HUNDRED:
                raise ValueError(
                    "The sum of account-allocation percentages cannot exceed 100%."
                )
            account_capital = decimal_value(
                self.account_capital_var.get(), "Total account capital"
            )
            if account_capital <= ZERO:
                raise ValueError("Total account capital must be greater than zero.")
            capital = account_capital * allocation_percent / ONE_HUNDRED
        ticker = yahoo_symbol_for(symbol, ticker)
        row_id = f"allocation-{self.next_allocation_id}"
        self.next_allocation_id += 1
        allocation = Allocation(symbol, robot, capital)
        self.allocations[row_id] = allocation
        self.allocation_percentages[row_id] = allocation_percent
        self.allocation_tree.insert(
            "",
            "end",
            iid=row_id,
            values=(
                symbol,
                ticker,
                robot,
                format_decimal(capital),
                format_decimal(allocation_percent)
                if allocation_percent is not None
                else "",
                "Not fetched",
                "Not calculated",
            ),
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
        self._schedule_autosave()

    def _add_allocation(self) -> None:
        try:
            self._insert_allocation(
                self.index_var.get(),
                self.yahoo_ticker_var.get(),
                self.robot_var.get(),
                self.account_capital_var.get(),
                self.allocation_pct_var.get(),
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
        self.allocation_percentages.pop(row_id, None)
        self.allocation_results.clear()
        self.quotes.pop(row_id, None)
        self.historical_stresses.pop(row_id, None)
        self.history_bars.pop(row_id, None)
        self.history_sources.pop(row_id, None)
        self.magic_assignments.pop(row_id, None)
        self.contract_inputs.pop(row_id, None)
        self.exposure_inputs.pop(row_id, None)
        self.saved_quote_rows.discard(row_id)
        self.saved_history_rows.discard(row_id)
        if self.current_settings_row == row_id:
            self.current_settings_row = None
        self._refresh_allocation_choices()
        self.status_var.set("Allocation removed.")
        self._schedule_autosave()

    def _refresh_allocation_choices(self) -> None:
        choices = []
        self.selection_ids.clear()
        for row_id, allocation in self.allocations.items():
            values = self.allocation_tree.item(row_id, "values")
            ticker = values[1]
            label = f"{allocation.index} | {allocation.robot} | {ticker} [{row_id}]"
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

            header_lookup: dict[str, str] = {}
            for header in reader.fieldnames:
                normalized = re.sub(r"[^a-z0-9]", "", header.casefold())
                if not normalized or normalized in header_lookup:
                    raise ValueError(
                        "MT5 contract CSV has an empty or duplicate column header."
                    )
                header_lookup[normalized] = header
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
                "maximum_lot": ("maxlot", "volumemax"),
                "commission_per_lot": (
                    "commissionperlot",
                    "roundturncommissionperlot",
                    "commissionperlotaccountcurrency",
                ),
                "contract_currency": (
                    "accountcurrency",
                    "pointvaluecurrency",
                    "accountcurrencyforpointvalue",
                    "contractcurrency",
                ),
            }
            selected_headers: dict[str, list[str]] = {}
            for field, candidates in aliases.items():
                headers = [
                    header_lookup[name] for name in candidates if name in header_lookup
                ]
                if headers:
                    selected_headers[field] = headers
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
                if None in row:
                    raise ValueError(f"CSV row {line_number} has too many columns.")
                if any(value is None for value in row.values()):
                    raise ValueError(f"CSV row {line_number} has missing columns.")
                if not row or not any(value and value.strip() for value in row.values()):
                    continue
                contract: ContractFields = {}
                for field, headers in selected_headers.items():
                    values = [
                        row[header].strip() for header in headers if row[header].strip()
                    ]
                    if values:
                        if field in ("symbol", "contract_currency"):
                            equivalent = len({value.upper() for value in values}) == 1
                        else:
                            numeric_values = [
                                decimal_value(value, f"CSV row {line_number} {field}")
                                for value in values
                            ]
                            equivalent = len(set(numeric_values)) == 1
                        if not equivalent:
                            raise ValueError(
                                f"CSV row {line_number} has conflicting columns for {field}."
                            )
                    contract[field] = values[0] if values else ""
                symbol = contract["symbol"]
                key = cls._normalized_broker_symbol(symbol)
                if not key:
                    raise ValueError(f"CSV row {line_number} has no symbol.")
                if key in contracts:
                    raise ValueError(f"CSV has duplicate symbol '{symbol}'.")

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
                if contract.get("maximum_lot"):
                    maximum_lot = decimal_value(
                        contract["maximum_lot"],
                        f"CSV row {line_number} maximum_lot",
                    )
                    if maximum_lot < decimal_value(
                        contract["minimum_lot"],
                        f"CSV row {line_number} minimum_lot",
                    ):
                        raise ValueError(
                            f"CSV row {line_number} maximum_lot cannot be below "
                            "minimum_lot."
                        )
                    contract["maximum_lot"] = format_decimal(maximum_lot)
                if contract.get("commission_per_lot"):
                    commission = decimal_value(
                        contract["commission_per_lot"],
                        f"CSV row {line_number} commission_per_lot",
                    )
                    if commission < ZERO:
                        raise ValueError(
                            f"CSV row {line_number} commission_per_lot must be "
                            "non-negative."
                        )
                    contract["commission_per_lot"] = format_decimal(commission)
                contract.setdefault("points_per_pip", "")
                contract.setdefault("maximum_lot", "")
                contract.setdefault("commission_per_lot", "")
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
                contract[key] = variable.get().strip()
        return contract

    def _transaction_costs(
        self,
        contract: ContractFields | None = None,
    ) -> tuple[Decimal, Decimal, Decimal]:
        costs = []
        for variable, label in (
            (self.spread_points_var, "Minimum spread points"),
            (self.slippage_points_var, "Slippage points"),
            (self.commission_per_lot_var, "Round-turn commission per lot"),
        ):
            raw = variable.get().strip()
            value = ZERO if not raw else decimal_value(raw, label)
            if value < ZERO:
                raise ValueError(f"{label} must be non-negative.")
            costs.append(value)
        override_text = (contract or {}).get("commission_per_lot", "").strip()
        if override_text:
            override = decimal_value(
                override_text, "Symbol round-turn commission per lot"
            )
            if override < ZERO:
                raise ValueError(
                    "Symbol round-turn commission per lot must be non-negative."
                )
            costs[2] = override
        return costs[0], costs[1], costs[2]

    def _sizing_costs(
        self, row_id: str, contract: ContractFields
    ) -> tuple[Decimal, Decimal, Decimal]:
        spread, slippage, commission = self._transaction_costs(contract)
        if not self.risk_profile["enabled"]:
            return spread, slippage, commission
        days = int(self.risk_profile["holding_days"])
        field = (
            "swap_short_debit" if self.position_direction_var.get() == "Short (price rises)"
            else "swap_long_debit"
        )
        inputs = self.exposure_inputs.get(row_id, default_exposure())
        if days and not inputs[field]:
            raise ValueError(
                f"{self.allocations[row_id].index}: enter verified {field} in "
                "account cash per lot per charge-day (0 only if verified)."
            )
        swap = decimal_value(inputs[field] or "0", "Swap debit")
        if swap < ZERO:
            raise ValueError("Swap must be a non-negative debit; credits are not used for sizing.")
        return spread, slippage, commission + swap * days

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
            self._schedule_autosave()
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

    def _import_mt5_history(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Import MT5 OHLC history",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            default_symbol = (
                next(iter(self.allocations.values())).index
                if len(self.allocations) == 1
                else ""
            )
            with open(path, "r", encoding="utf-8-sig", newline="") as history_file:
                histories = parse_mt5_history_csv(
                    history_file.read(),
                    default_symbol=default_symbol,
                )
            matched = 0
            unmatched: list[str] = []
            for row_id, allocation in self.allocations.items():
                symbol_key = allocation.index.strip().upper()
                bars = histories.get(symbol_key)
                if bars is None:
                    base_key = self._broker_symbol_base(allocation.index)
                    candidates = [
                        candidate_bars
                        for symbol, candidate_bars in histories.items()
                        if self._broker_symbol_base(symbol) == base_key
                    ]
                    if len(candidates) == 1:
                        bars = candidates[0]
                    elif len(candidates) > 1:
                        unmatched.append(f"{allocation.index} (ambiguous symbol match)")
                        continue
                if bars is None:
                    unmatched.append(allocation.index)
                    continue
                history = calculate_historical_stress(bars)
                self.historical_stresses[row_id] = history
                self.history_bars[row_id] = bars
                self.history_sources[row_id] = "MT5 CSV"
                self.saved_history_rows.discard(row_id)
                last_bar = bars[-1]
                self.quotes[row_id] = (
                    last_bar.close,
                    "MT5 price",
                    allocation.index,
                    f"{last_bar.date} (last imported bar)",
                )
                self.saved_quote_rows.discard(row_id)
                values = list(self.allocation_tree.item(row_id, "values"))
                values[5] = f"{format_decimal(last_bar.close)} (MT5 history)"
                self.allocation_tree.item(row_id, values=values)
                matched += 1

            if matched == 0:
                raise ValueError(
                    "No imported MT5 history symbol matched the current portfolio. "
                    "Check the CSV symbol column or add a single allocation before "
                    "importing a file without one."
                )
            self._calculate_portfolio(show_error=False)
            self._selection_changed()
            self._update_stress_input_states()
            self.status_var.set(
                f"Imported {matched} MT5 OHLC history allocation(s) from {path}."
            )
            self._schedule_autosave()
            if unmatched:
                messagebox.showwarning(
                    "Some histories were not matched",
                    f"Imported {matched} symbol(s). Add or correct history for: "
                    + ", ".join(unmatched),
                    parent=self,
                )
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            self.status_var.set("MT5 history import failed.")
            messagebox.showerror(
                "Could not import MT5 history", str(error), parent=self
            )

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
                    "Import the MT5 contract CSV and optional MT5 OHLC history, "
                    "or fetch Yahoo price plus daily history. Set a strategy-specific "
                    "Take Profit value for a complete EA configuration."
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
        if mode in HISTORICAL_STRESS_MODES:
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
            stress_percent = historical_stress_move(
                historical,
                mode,
                self.position_direction_var.get() != "Short (price rises)",
            )
            self.stress_pct_var.set(
                format_decimal(stress_percent) if stress_percent > ZERO else ""
            )
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
            self.status_var.set(
                "Connect MT5, fetch a Yahoo price, or enter a reference price first."
            )

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
        is_long = self.position_direction_var.get() == "Long (price falls)"
        if base_price <= ZERO or percent <= ZERO or (
            is_long and percent >= ONE_HUNDRED
        ):
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
        if self.stress_mode_var.get() in HISTORICAL_STRESS_MODES:
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
            history_source = self.history_sources.get(row_id, "Yahoo")
            history_mark = (
                f" | {history_source} history: {historical.bar_count} bars"
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
        if self.risk_profile["enabled"]:
            profile_daily, profile_total = remaining_rooms(
                self.risk_profile, account_capital, daily_limit
            )
            if profile_daily <= ZERO or profile_total <= ZERO:
                raise ValueError(
                    "Configured prop equity floor is already reached/breached; "
                    "no loss room is available for new candidates."
                )
            remaining_daily_room = min(
                remaining_daily_room if remaining_daily_room is not None else profile_daily,
                profile_daily,
            )
            prop_loss_room = min(
                prop_loss_room if prop_loss_room is not None else profile_total,
                profile_total,
            )
        effective_cap = effective_portfolio_risk_cap(
            daily_limit,
            remaining_daily_room,
            prop_loss_room,
        )
        if self.risk_profile["enabled"] and self.risk_profile["idea_limit_pct"]:
            groups: dict[str, Decimal] = {}
            for row_id, allocation in self.allocations.items():
                group = self.exposure_inputs.get(row_id, default_exposure())["idea_group"]
                if not group:
                    continue
                percent = self.allocation_percentages.get(row_id)
                capital = (
                    account_capital * percent / ONE_HUNDRED
                    if percent is not None else allocation.capital
                )
                groups[group.casefold()] = groups.get(group.casefold(), ZERO) + capital
            idea_cap = account_capital * decimal_value(
                self.risk_profile["idea_limit_pct"], "Per-idea loss limit"
            ) / ONE_HUNDRED
            for capital in groups.values():
                effective_cap = min(effective_cap, idea_cap * account_capital / capital)
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
            allocated_percent = sum(
                (
                    percentage
                    for percentage in self.allocation_percentages.values()
                    if percentage is not None
                ),
                ZERO,
            )
            if allocated_percent > ONE_HUNDRED:
                raise ValueError(
                    "The sum of account-allocation percentages cannot exceed 100%."
                )
            for row_id, allocation in tuple(self.allocations.items()):
                percentage = self.allocation_percentages.get(row_id)
                if percentage is None:
                    continue
                capital = account_capital * percentage / ONE_HUNDRED
                self.allocations[row_id] = Allocation(
                    allocation.index, allocation.robot, capital
                )
                values = list(self.allocation_tree.item(row_id, "values"))
                values[3] = format_decimal(capital)
                self.allocation_tree.item(row_id, values=values)
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
                values[5] = (
                    f"{format_decimal(quote_data[0])} {quote_data[1]}"
                    if quote_data
                    else "Not fetched"
                )
                if quote_data and row_id in self.saved_quote_rows:
                    values[5] += " (saved)"
                values[6] = (
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

    def _refresh_startup_data(self) -> None:
        self._startup_refresh_after_id = None
        if self.quote_busy or not self.allocations:
            return
        required_contract_fields = (
            "point_value", "point_size", "lot_increment", "minimum_lot",
            "contract_currency",
        )
        missing_contract_rows = {
            row_id
            for row_id in self.allocations
            if any(
                not self._contract_inputs_for_allocation(row_id).get(field, "").strip()
                for field in required_contract_fields
            )
        }
        if any(
            row_id not in self.quotes
            or row_id not in self.historical_stresses
            or row_id in missing_contract_rows
            for row_id in self.allocations
        ):
            self._show_startup_data_wait()
        requests = [
            (
                row_id,
                allocation.index,
                yahoo_symbol_for(
                    allocation.index, self.allocation_tree.item(row_id, "values")[1]
                ),
                self.history_sources.get(row_id, ""),
                row_id in missing_contract_rows,
            )
            for row_id, allocation in self.allocations.items()
        ]
        account_currency = self.currency_var.get().strip().upper()
        terminal_path = self.mt5_terminal_path_var.get().strip()
        self._set_fetch_busy(True)
        self.status_var.set("Refreshing saved market data at startup...")

        def worker() -> None:
            warnings: list[str] = []
            mt5_symbol_cache: dict[str, tuple[str, MT5SymbolData]] = {}
            for row_id, symbol, ticker, source, missing_contract in requests:
                if (
                    source == "MT5 CSV"
                    and row_id in self.quotes
                    and row_id in self.historical_stresses
                    and not missing_contract
                ):
                    warnings.append(
                        f"{symbol}: imported MT5 CSV snapshot retained; "
                        "connect MT5 to refresh broker data."
                    )
                    continue
                missing_contract_requires_mt5 = (
                    missing_contract and source in ("Yahoo", "MT5 CSV", "Broker API")
                )
                if source == "MT5 terminal" or missing_contract_requires_mt5:
                    try:
                        symbol_key = symbol.strip().upper()
                        cached_mt5_result = mt5_symbol_cache.get(symbol_key)
                        if cached_mt5_result is None:
                            currency, data = (
                                fetch_mt5_terminal_data(
                                    [symbol],
                                    terminal_path=terminal_path,
                                )
                                if terminal_path else fetch_mt5_terminal_data([symbol])
                            )
                            symbol_data = data[symbol_key]
                            mt5_symbol_cache[symbol_key] = (currency, symbol_data)
                        else:
                            currency, symbol_data = cached_mt5_result
                        if currency != account_currency:
                            raise ValueError(
                                f"Broker currency {currency} differs from the "
                                f"configured account currency {account_currency}."
                            )
                        result = MT5PortfolioResult(
                            {row_id: symbol_data}, currency
                        )
                        self.quote_messages.put((row_id, "startup_mt5_done", result))
                    except (
                        ValueError, OSError, KeyError, TypeError, AttributeError,
                        OverflowError, InvalidOperation, RuntimeError,
                    ) as error:
                        warnings.append(f"{symbol}: {error} Saved data retained.")
                    continue
                result = self._request_yahoo_data(row_id, ticker)
                if result.error:
                    warnings.append(f"{symbol}: {result.error} Saved data retained.")
                self.quote_messages.put((row_id, "startup_yahoo", result))
            self.quote_messages.put(("__startup__", "startup_done", warnings))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _show_startup_data_wait(self) -> None:
        if self.startup_wait_window is not None:
            return
        window = tk.Toplevel(self)
        self.startup_wait_window = window
        window.title("Collecting initial market data")
        window.resizable(False, False)
        window.transient(self)
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        content = ttk.Frame(window, padding=18)
        content.pack(fill="both", expand=True)
        ttk.Label(
            content,
            text=(
                "Saved market data is incomplete. Please wait while the planner "
                "refreshes available sources. The screen unlocks when the refresh "
                "attempt finishes."
            ),
            justify="left",
            wraplength=380,
        ).pack(fill="x")
        progress = ttk.Progressbar(content, mode="indeterminate", length=380)
        progress.pack(fill="x", pady=(12, 0))
        self.startup_wait_progress = progress
        progress.start(15)
        window.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - window.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - window.winfo_height()) // 2
        window.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        window.grab_set()
        window.lift()
        window.focus_set()

    def _close_startup_data_wait(self) -> None:
        window = self.startup_wait_window
        if window is None:
            return
        progress = self.startup_wait_progress
        self.startup_wait_window = None
        self.startup_wait_progress = None
        if progress is not None:
            progress.stop()
        try:
            if window.grab_current() is window:
                window.grab_release()
            window.destroy()
        except tk.TclError:
            pass

    def _fetch_all_yahoo_data(self, only_missing: bool = False) -> None:
        if self.quote_busy:
            return
        requests = []
        for row_id, allocation in self.allocations.items():
            if (
                only_missing
                and self.history_sources.get(row_id) in BROKER_HISTORY_SOURCES
                and row_id in self.quotes
                and row_id in self.historical_stresses
            ):
                continue
            values = self.allocation_tree.item(row_id, "values")
            requests.append(
                (row_id, yahoo_symbol_for(allocation.index, values[1]))
            )
        if not requests:
            if self.portfolio_suggestion_pending:
                self.portfolio_suggestion_pending = False
                self._generate_portfolio_settings_checked()
                return
            messagebox.showinfo(
                "No allocations",
                "Add at least one robot allocation first.",
                parent=self,
            )
            return
        self._set_fetch_busy(True)
        self._begin_yahoo_batch(len(requests))
        self.status_var.set(
            f"Fetching missing Yahoo prices and history for {len(requests)} allocation(s)..."
        )

        def worker() -> None:
            for row_id, ticker in requests:
                result = self._request_yahoo_data(row_id, ticker)
                self.quote_messages.put((row_id, "batch_item", result))
            self.quote_messages.put(("__all__", "batch_done", None))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _fetch_mt5_terminal_data(self) -> None:
        if self.quote_busy:
            self.status_var.set("Wait for the current market-data request to finish.")
            return
        if not self.allocations:
            self._show_portfolio_suggestion_error(
                "Add at least one broker symbol before connecting to MT5."
            )
            return
        if self.current_settings_row in self.allocations:
            self._capture_contract_inputs(self.current_settings_row)
        requested_rows = [
            (row_id, allocation.index)
            for row_id, allocation in self.allocations.items()
        ]
        terminal_path = self.mt5_terminal_path_var.get().strip()
        self._set_fetch_busy(True)
        self.status_var.set(
            "Connecting to the logged-in MT5 terminal for contract specs and "
            "five years of daily history..."
        )

        def worker() -> None:
            try:
                account_currency, symbols = fetch_mt5_terminal_data(
                    [symbol for _, symbol in requested_rows],
                    history_years=5,
                    terminal_path=terminal_path,
                    include_timeframes=True,
                )
                rows = {
                    row_id: symbols[symbol.strip().upper()]
                    for row_id, symbol in requested_rows
                }
                result = MT5PortfolioResult(rows, account_currency)
            except (
                ValueError,
                OSError,
                TypeError,
                AttributeError,
                OverflowError,
                InvalidOperation,
                RuntimeError,
            ) as error:
                result = MT5PortfolioResult({}, "", str(error))
            self.quote_messages.put(("__mt5__", "mt5_done", result))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_quote_result)

    def _fetch_broker_api_data(self) -> None:
        if self.quote_busy:
            self.status_var.set("Wait for the current market-data request to finish.")
            return
        if not self.allocations:
            self._show_portfolio_suggestion_error(
                "Add at least one broker symbol before fetching broker API data."
            )
            return
        endpoint = self.broker_api_endpoint_var.get().strip()
        token = self.broker_api_token_var.get()
        try:
            validate_broker_api_endpoint(endpoint)
            self._save_broker_api_config(endpoint)
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Broker API configuration",
                str(error),
                parent=self,
            )
            self.status_var.set(f"Broker API configuration is invalid: {error}")
            return

        requested_rows = [
            (row_id, allocation.index)
            for row_id, allocation in self.allocations.items()
        ]
        self.broker_api_token_var.set("")
        self._set_fetch_busy(True)
        self.status_var.set(
            "Fetching five years of daily broker quotes, contract specs and history..."
        )

        def worker() -> None:
            try:
                symbols = list(dict.fromkeys(symbol for _, symbol in requested_rows))
                account_currency, symbols_data = fetch_broker_api_data(
                    endpoint,
                    token,
                    symbols,
                )
                rows = {
                    row_id: symbols_data[symbol.strip().upper()]
                    for row_id, symbol in requested_rows
                }
                result = MT5PortfolioResult(rows, account_currency)
            except (
                ValueError,
                OSError,
                TypeError,
                AttributeError,
                OverflowError,
                InvalidOperation,
                RuntimeError,
            ) as error:
                result = MT5PortfolioResult({}, "", str(error))
            self.quote_messages.put(("__broker_api__", "broker_api_done", result))

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
        if busy:
            self.quote_request_cancelled = False
            self.fetch_progress.pack(side="right", padx=(10, 0))
            self.fetch_progress.start(15)
        else:
            self.fetch_progress.stop()
            self.fetch_progress.pack_forget()
        state = "disabled" if busy else "normal"
        self.fetch_button.configure(state=state)
        if self.fetch_all_button is not None:
            self.fetch_all_button.configure(state=state)
        if self.fetch_mt5_button is not None:
            self.fetch_mt5_button.configure(state=state)
        if self.inspect_mt5_button is not None:
            self.inspect_mt5_button.configure(state=state)
        if self.fetch_broker_api_button is not None:
            self.fetch_broker_api_button.configure(state=state)

    def _poll_quote_result(self) -> None:
        try:
            row_id, status, result = self.quote_messages.get_nowait()
        except queue.Empty:
            if self.quote_busy:
                self.after(100, self._poll_quote_result)
            return
        if self.quote_request_cancelled:
            if status in (
                "one",
                "batch_done",
                "mt5_done",
                "broker_api_done",
                "startup_done",
                "prop_website_done",
                "mt5_status_done",
            ):
                self._set_fetch_busy(False)
                self._close_startup_data_wait()
                self.quote_request_cancelled = False
            else:
                self.after(100, self._poll_quote_result)
            return
        if status == "mt5_status_done":
            self._set_fetch_busy(False)
            if not isinstance(result, MT5InspectionResult):
                self.status_var.set("MT5 inspection returned an invalid result.")
                messagebox.showerror(
                    "MT5 connection", "Invalid inspection result format.", parent=self
                )
                return
            if result.error:
                self.mt5_connection.clear()
                self.status_var.set(f"MT5 inspection failed: {result.error}")
                messagebox.showerror("MT5 connection", result.error, parent=self)
                return
            data = result.connection
            self.mt5_connection = data
            try:
                catalog = json.loads(data.get("symbol_catalog", "[]"))
            except (TypeError, json.JSONDecodeError):
                catalog = []
            self.mt5_symbol_catalog = {
                item["symbol"]: item
                for item in catalog
                if isinstance(item, dict)
                and isinstance(item.get("symbol"), str)
                and item["symbol"].strip()
            }
            self._refresh_broker_symbol_choices(register_terminal_symbols=True)
            self.status_var.set(
                f"MT5 {data['account_type']} | {data['broker']} | "
                f"{data['server']} | {data['currency']}."
            )
            self._show_data_status()
            return
        if status == "prop_website_done":
            self._set_fetch_busy(False)
            temporary_path = ""
            try:
                if isinstance(result, str):
                    raise ValueError(result)
                snapshot = self._validate_prop_website_snapshot(result)
                os.makedirs(APP_DATA_DIRECTORY, exist_ok=True)
                descriptor, temporary_path = tempfile.mkstemp(
                    prefix=".prop-website-", suffix=".tmp", dir=APP_DATA_DIRECTORY,
                    text=True,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    json.dump(snapshot, file, ensure_ascii=False, indent=2)
                    file.write("\n")
                os.replace(
                    temporary_path,
                    os.path.join(APP_DATA_DIRECTORY, PROP_WEBSITE_FILE_NAME),
                )
                temporary_path = ""
                self.prop_website_snapshot = snapshot
                self._display_prop_website_snapshot()
                self.status_var.set(
                    "Website rule candidates saved locally. Select and verify a "
                    "program/stage before applying; account values are unchanged."
                )
            except (ValueError, OSError, TypeError) as error:
                self.status_var.set(f"Program website import failed: {error}")
                messagebox.showerror(
                    "Program website import", str(error), parent=self
                )
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.unlink(temporary_path)
            return
        if status == "startup_done":
            self._set_fetch_busy(False)
            self._close_startup_data_wait()
            self._calculate_portfolio(show_error=False)
            self._schedule_autosave()
            if result:
                self.status_var.set(
                    "Startup refresh finished with warnings; saved data retained "
                    "where refresh was unavailable."
                )
                messagebox.showwarning(
                    "Startup data refresh", "\n".join(result), parent=self
                )
            else:
                self.status_var.set("Startup market-data refresh completed.")
            return
        if status == "startup_yahoo":
            self._apply_yahoo_data_result(result, refresh_settings=False)
            if result.error:
                self.cached_data_warnings[row_id] = result.error
            self.after(100, self._poll_quote_result)
            return
        if status in (
            "mt5_done", "broker_api_done", "startup_mt5_done", "startup_api_done"
        ):
            startup = status.startswith("startup_")
            if not startup:
                self._set_fetch_busy(False)
            source_name = (
                "MT5 terminal"
                if status in ("mt5_done", "startup_mt5_done")
                else "Broker API"
            )
            if not isinstance(result, MT5PortfolioResult):
                self.status_var.set(
                    f"{source_name} returned an invalid portfolio response."
                )
                messagebox.showerror(
                    f"{source_name} data",
                    "The returned result had an invalid format.",
                    parent=self,
                )
                return
            if result.error:
                self.status_var.set(result.error)
                messagebox.showerror(
                    f"Could not read {source_name} contract/history",
                    result.error,
                    parent=self,
                )
                return
            currency = self.currency_var.get().strip().upper()
            if result.account_currency.strip().upper() != currency:
                error = (
                    f"{source_name} currency {result.account_currency} does not match "
                    f"the configured account currency {currency or '(empty)'}. "
                    "No data or cash amounts were changed. Configure a matching "
                    "account currency and re-enter all capital/loss-room amounts "
                    "in that currency before reconnecting; no FX conversion is assumed."
                )
                self.status_var.set(error)
                messagebox.showerror("Account currency mismatch", error, parent=self)
                if startup:
                    self.after(100, self._poll_quote_result)
                return
            contract_warnings = []
            for row_id, symbol_data in result.rows.items():
                if row_id not in self.allocations:
                    continue
                contract, review_required = merge_refreshed_contract(
                    self._contract_inputs_for_allocation(row_id), symbol_data.contract
                )
                if review_required:
                    contract_warnings.append(
                        f"{self.allocations[row_id].index}: contract specifications "
                        "changed. Re-enter EA pip conversion and commission; old "
                        "manual values were not copied to the new contract."
                    )
                self.contract_inputs[row_id] = contract
                self.history_bars[row_id] = symbol_data.bars
                self.historical_stresses[row_id] = calculate_historical_stress(
                    symbol_data.bars
                )
                self.history_sources[row_id] = source_name
                self._save_symbol_timeframe_charts(
                    self.allocations[row_id].index,
                    symbol_data.timeframe_charts,
                )
                self.saved_history_rows.discard(row_id)
                self.cached_data_warnings.pop(row_id, None)
                self.quotes[row_id] = symbol_data.quote
                self.saved_quote_rows.discard(row_id)
                values = list(self.allocation_tree.item(row_id, "values"))
                values[5] = (
                    f"{format_decimal(symbol_data.quote[0])} "
                    f"{symbol_data.quote[1]} ({source_name})"
                )
                self.allocation_tree.item(row_id, values=values)
            selected_row = self._selected_row_id()
            if selected_row in self.allocations:
                self._load_contract_inputs(selected_row)
                selected_quote = self.quotes.get(selected_row)
                if selected_quote is not None:
                    self.reference_price_var.set(format_decimal(selected_quote[0]))
                    self.stress_target_price_var.set("")
                    self.auto_stress_target_price = None
                    self._selection_changed()
            self._calculate_portfolio(show_error=False)
            self._schedule_autosave()
            if contract_warnings:
                messagebox.showwarning(
                    "Contract inputs need review", "\n".join(contract_warnings),
                    parent=self,
                )
                self.status_var.set("Contract changed; review manual values before sizing.")
                if startup:
                    self.after(100, self._poll_quote_result)
                return
            if startup:
                self.status_var.set(
                    f"Updated {source_name} data; finishing startup refresh..."
                )
                self.after(100, self._poll_quote_result)
                return
            self.status_var.set(
                f"Read {source_name} contract specs, quotes and available D1 history for "
                f"{len(result.rows)} allocation(s); account currency "
                f"{result.account_currency}. Generating the portfolio estimate..."
            )
            quality = [
                f"{self.allocations[row_id].index}: {stress.start_date} to "
                f"{stress.end_date} ({stress.bar_count} daily bars). "
                + " ".join(history_quality_warnings(stress))
                for row_id in result.rows
                if row_id in self.allocations
                for stress in (self.historical_stresses[row_id],)
                if history_quality_warnings(stress)
            ]
            if quality:
                self.status_var.set("History coverage warning: " + " | ".join(quality))
            self._suggest_portfolio_downside()
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
                        f"Updated Yahoo price and historical data for {result.row_id}."
                    )
            return
        if status == "batch_item":
            if isinstance(result, YahooDataResult):
                self._apply_yahoo_data_result(result, refresh_settings=False)
                self.batch_completed += 1
                if result.error:
                    if (
                        row_id in self.quotes
                        and row_id in self.historical_stresses
                        and self.history_sources.get(row_id) == "Yahoo"
                    ):
                        self.cached_data_warnings[row_id] = result.error
                    else:
                        allocation = self.allocations.get(row_id)
                        symbol = allocation.index if allocation is not None else row_id
                        self.batch_errors.append(
                            f"{symbol}: {result.error}"
                        )
                else:
                    self.cached_data_warnings.pop(row_id, None)
                self.status_var.set(
                    f"Fetched Yahoo data for {self.batch_completed} of "
                    f"{self.batch_total} allocation(s)..."
                )
            self.after(100, self._poll_quote_result)
            return
        if status == "batch_done":
            self._set_fetch_busy(False)
            self._calculate_portfolio(show_error=False)
            self._schedule_autosave()
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
                if self.batch_errors:
                    self._show_settings_hint(
                        "Yahoo refresh incomplete; no settings regenerated.\n\n"
                        + "\n".join(self.batch_errors)
                        + "\n\nExisting complete snapshots were kept. Retry the refresh "
                        "or explicitly generate from the retained data."
                    )
                else:
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
                    f"Fetched current prices and historical data for "
                    f"{self.batch_completed} allocation(s)."
                )
            elif self.cached_data_warnings:
                self.status_var.set(
                    "Some Yahoo refreshes failed; recommendations use the saved "
                    "history snapshots. Review the report warnings."
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
        quote = result.quote
        if (
            result.history is None
            and row_id in self.historical_stresses
            and row_id in self.quotes
        ):
            quote = self.quotes[row_id]
        else:
            self.quotes[row_id] = quote
            self.saved_quote_rows.discard(row_id)
        if result.history is not None:
            self.historical_stresses[row_id] = result.history
            self.history_bars.pop(row_id, None)
            self.history_sources[row_id] = "Yahoo"
            self.saved_history_rows.discard(row_id)
            self.cached_data_warnings.pop(row_id, None)
        price, currency, yahoo_symbol, timestamp = quote
        values = list(self.allocation_tree.item(row_id, "values"))
        values[5] = f"{format_decimal(price)} {currency}"
        self.allocation_tree.item(row_id, values=values)
        if self._selected_row_id() == row_id:
            historical = self.historical_stresses.get(row_id)
            history_source = self.history_sources.get(row_id, "Yahoo")
            history_label = (
                f" | {history_source} history ({historical.bar_count} bars)"
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
            if result.error:
                self.status_var.set(result.error)
            elif self.notebook.select() == str(self.settings_tab):
                self._main_tab_changed()
        self._schedule_autosave()

    def _begin_yahoo_batch(self, allocation_count: int) -> None:
        self.batch_total = allocation_count
        self.batch_completed = 0
        self.batch_errors: list[str] = []

    def _generate_settings(self) -> None:
        row_id = self._selected_row_id()
        needs_history = self.stress_mode_var.get() in HISTORICAL_STRESS_MODES
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

        self.stress_mode_var.set(HISTORICAL_DRAWDOWN_MODE)
        self.position_direction_var.set("Long (price falls)")
        self._update_stress_input_states()
        self.portfolio_suggestion_pending = True
        self.output_text.delete("1.0", "end")
        self.output_text.insert(
            "1.0",
            "Refreshing five-year Yahoo daily history for allocations without "
            "broker MT5/API history. Imported broker history is retained. The combined "
            "downside suggestion will follow.\n",
        )
        if all(
            self.history_sources.get(row_id) in BROKER_HISTORY_SOURCES
            and row_id in self.quotes
            and row_id in self.historical_stresses
            for row_id in self.allocations
        ):
            self._generate_portfolio_settings_checked()
            return
        self._fetch_all_yahoo_data(only_missing=True)

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
        selected_magic_number: int,
        take_profit_type: str,
        take_profit_value: str,
        include_candidate_settings: bool = False,
    ) -> list[str]:
        currency = self.currency_var.get().strip() or "account currency"
        stress_mode = self.stress_mode_var.get()
        historical_mode = stress_mode in HISTORICAL_STRESS_MODES
        drawdown_mode = stress_mode == HISTORICAL_DRAWDOWN_MODE
        is_long = self.position_direction_var.get() == "Long (price falls)"
        spread_points, slippage_points, _ = self._transaction_costs()
        rows: list[
            tuple[str, str, Decimal, int, Decimal, Decimal, str, str, int, str, str]
        ] = []
        missing: list[str] = []
        total_estimated_loss = ZERO
        account_currency = self.currency_var.get().strip().upper()
        candidate_limit = positive_integer(
            self.compare_trades_var.get(), "Max Trades candidates"
        )
        if candidate_limit > 20:
            raise ValueError("Compare at most 20 Max Trades values.")
        (
            account_capital,
            daily_limit,
            remaining_daily_room,
            prop_loss_room,
            effective_cap,
        ) = self._portfolio_risk_limits()

        for row_id, allocation_result in self.allocation_results.items():
            allocation = allocation_result.allocation
            allocation_label = f"{allocation.index} [{row_id}]"
            quote_data = self.quotes.get(row_id)
            contract = self._contract_inputs_for_allocation(row_id)
            _, _, commission_per_lot = self._sizing_costs(row_id, contract)
            if quote_data is None:
                missing.append(f"{allocation_label}: market reference price not loaded")
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
                    f"{allocation_label}: missing MT5 "
                    + ", ".join(missing_fields)
                )
                continue

            contract_currency = contract.get("contract_currency", "").strip().upper()
            if not account_currency:
                missing.append(f"{allocation_label}: missing account currency")
                continue
            if not contract_currency:
                missing.append(f"{allocation_label}: missing point-value currency")
                continue
            if account_currency and contract_currency != account_currency:
                missing.append(
                    f"{allocation_label}: point-value currency {contract_currency} "
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
                maximum_lot = (
                    decimal_value(
                        contract["maximum_lot"], f"{allocation.index} maximum lot"
                    )
                    if contract.get("maximum_lot", "").strip()
                    else None
                )
            except ValueError as error:
                missing.append(f"{allocation_label}: invalid MT5 contract ({error})")
                continue
            if min(point_value, point_size, lot_increment, minimum_lot) <= ZERO:
                missing.append(
                    f"{allocation_label}: MT5 point/volume specifications must be positive"
                )
                continue
            if maximum_lot is not None and maximum_lot < minimum_lot:
                missing.append(
                    f"{allocation_label}: broker maximum lot is below minimum lot"
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
                        f"{allocation_label}: MT5 or Yahoo daily history not loaded"
                    )
                    continue
                row_stress_percent = historical_stress_move(
                    history, stress_mode, is_long
                )
                observed_date = historical_stress_period(
                    history, stress_mode, is_long
                )
                history_bars = history.bar_count
                if row_stress_percent <= ZERO or (
                    is_long and row_stress_percent >= ONE_HUNDRED
                ):
                    missing.append(
                        f"{allocation_label}: no valid historical adverse move "
                        "is available (refresh history for the selected stress mode)"
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
                    mt5_bars = self.history_bars.get(row_id)
                    if drawdown_mode:
                        recommendation = suggest_safe_grid_settings(
                            stress_points=stress_points,
                            step_points=grid_step_points,
                            point_value_per_lot=point_value,
                            daily_budget=allocation_result.daily_loss_budget,
                            lot_step=lot_increment,
                            minimum_lot=minimum_lot,
                            spread_points=historical_spread_floor(
                                mt5_bars or (), spread_points
                            ),
                            slippage_points=slippage_points,
                            commission_per_lot=commission_per_lot,
                            maximum_lot=maximum_lot,
                            max_trades_limit=candidate_limit,
                        )
                    elif mt5_bars:
                        recommendation = suggest_safe_grid_settings_from_history(
                            bars=mt5_bars,
                            point_size=point_size,
                            point_value_per_lot=point_value,
                            step_value=(
                                step_value if step_type != "enum_fixed_pips"
                                else grid_step_points
                            ),
                            step_is_percentage=step_type != "enum_fixed_pips",
                            daily_budget=allocation_result.daily_loss_budget,
                            lot_step=lot_increment,
                            minimum_lot=minimum_lot,
                            spread_points=spread_points,
                            slippage_points=slippage_points,
                            commission_per_lot=commission_per_lot,
                            is_long=is_long,
                            maximum_lot=maximum_lot,
                            max_trades_limit=candidate_limit,
                        )
                    else:
                        recommendation = suggest_safe_grid_settings(
                            stress_points=stress_points,
                            step_points=grid_step_points,
                            point_value_per_lot=point_value,
                            daily_budget=allocation_result.daily_loss_budget,
                            lot_step=lot_increment,
                            minimum_lot=minimum_lot,
                            spread_points=spread_points,
                            slippage_points=slippage_points,
                            commission_per_lot=commission_per_lot,
                            maximum_lot=maximum_lot,
                            max_trades_limit=candidate_limit,
                        )
                except ValueError as error:
                    missing.append(
                        f"{allocation_label}: no safe MT5 lot/Max Trades combination "
                        f"({error})"
                    )
                    continue
                row_max_trades = recommendation.max_trades
                effective_lot = recommendation.initial_lot
                loss = recommendation.estimated_loss
                if recommendation.worst_date:
                    observed_date = recommendation.worst_date
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
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                )
                proposed_lot = (
                    (unit_stress.recommended_max_lot / lot_increment)
                    .to_integral_value(rounding=ROUND_FLOOR)
                    * lot_increment
                )
                if maximum_lot is not None:
                    proposed_lot = min(
                        proposed_lot,
                        (maximum_lot / lot_increment)
                        .to_integral_value(rounding=ROUND_FLOOR)
                        * lot_increment,
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
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
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
                    self.history_sources.get(row_id, "Yahoo"),
                    row_id,
                )
            )

        allocated_daily_budget = effective_cap
        portfolio_working_allowance = effective_cap * Decimal("0.8")

        report = [
            "",
            (
                "PORTFOLIO SUGGESTION (historical peak-to-trough drawdown; 1.0 multiplier)"
                if drawdown_mode and is_long
                else "PORTFOLIO SUGGESTION (historical trough-to-peak rally; 1.0 multiplier)"
                if drawdown_mode
                else "PORTFOLIO SUGGESTION (each symbol's worst daily bar; 1.0 multiplier)"
                if historical_mode
                else "PORTFOLIO STRESS (shared Step / Max Trades; 1.0 multiplier)"
            ),
            (
                "Sizes each grid against its largest historical adverse episode; "
                "all grid entries are assumed to remain open until the adverse extreme."
                if drawdown_mode
                else "Uses each allocation's own worst adverse daily OHLC bar; imported MT5 history is preferred, Yahoo 5y is fallback."
                if historical_mode
                else "Applies the same adverse percentage to every loaded index."
            ),
        ]
        if historical_mode:
            report.append(
                (
                    "Combined as if every index reached its own historical drawdown "
                    "at the same time."
                    if drawdown_mode
                    else "Combined as if every index reached its own worst downside "
                    "session at the same time."
                )
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
            history_source,
            allocation_id,
        ) in rows:
            report.append(
                f"{symbol:<14.14} {robot:<6} {format_decimal(row_percent, 2):>8} "
                f"{row_trades:>6} {format_decimal(lot):>10} "
                f"{format_decimal(loss, 2):>12}  {status}"
            )
            row_result = self.allocation_results[allocation_id]
            contract = self._contract_inputs_for_allocation(allocation_id)
            _, _, row_commission = self._transaction_costs(contract)
            commission_source = (
                "symbol override" if contract.get("commission_per_lot", "").strip()
                else "shared fallback; not supplied by MT5, verify manually"
            )
            report.append(
                f"  Round-turn commission: {format_decimal(row_commission)} "
                f"{currency}/lot ({commission_source})."
            )
            if self.risk_profile["enabled"]:
                _, _, reserved_cost = self._sizing_costs(allocation_id, contract)
                report.append(
                    f"  Overnight debit reserve: {format_decimal(reserved_cost - row_commission)} "
                    f"{currency}/lot; {self.risk_profile['holding_days']} charge-days "
                    "reserved on EVERY entry at entry time (no swap credit)."
                )
            report.append(
                f"  Allocation ID: {allocation_id}; capital "
                f"{format_decimal(row_result.allocation.capital, 2)} {currency}; "
                f"risk allowance (80%): "
                f"{format_decimal(row_result.daily_loss_budget * Decimal('0.8'), 2)} "
                f"{currency}."
            )
            if historical_mode:
                report.append(
                    (
                        f"  {history_bars} {history_source} daily bars; drawdown episode: "
                        f"{observed_date}"
                        if drawdown_mode
                        else f"  {history_bars} {history_source} daily bars; "
                        f"worst day: {observed_date}"
                    )
                )
            if allocation_id in self.cached_data_warnings:
                report.append(
                    "  WARNING: Yahoo refresh failed; this allocation uses its "
                    f"saved local snapshot. {self.cached_data_warnings[allocation_id]}"
                )
            history = self.historical_stresses.get(allocation_id)
            if history is not None and historical_mode:
                report.append(
                    f"  Actual history: {history.start_date} to {history.end_date}; "
                    f"{history.bar_count} daily bars."
                )
                for warning in history_quality_warnings(history):
                    report.append(f"  HISTORY WARNING: {warning}")
        if include_candidate_settings and rows:
            report.extend(
                [
                    "",
                    "PER-ROBOT CANDIDATE SETTINGS "
                    "(sizing values; verify every EA input name and strategy value):",
                ]
            )
            used_magic_numbers = set(self.magic_assignments.values())
            used_magic_numbers.add(selected_magic_number)
            next_magic_number = 10001
            for (
                symbol,
                robot,
                _row_percent,
                row_trades,
                lot,
                _loss,
                _status,
                _observed_date,
                _history_bars,
                _history_source,
                allocation_id,
            ) in rows:
                if allocation_id == selected_row:
                    magic_number = selected_magic_number
                else:
                    magic_number = self.magic_assignments.get(allocation_id, 0)
                    if not magic_number:
                        while next_magic_number in used_magic_numbers:
                            next_magic_number += 1
                        magic_number = next_magic_number
                        used_magic_numbers.add(magic_number)
                        next_magic_number += 1
                    self.magic_assignments[allocation_id] = magic_number
                minimum_lot = decimal_value(
                    self._contract_inputs_for_allocation(allocation_id)["minimum_lot"],
                    f"{symbol} minimum lot",
                )
                risk_setting = (
                    "0.0" if lot == minimum_lot else format_decimal(lot)
                )
                report.extend(
                    [
                        "",
                        f"{symbol} | {robot} | {allocation_id}",
                        f"Magic Number: {magic_number}",
                        f"Max Trades: {row_trades}",
                        f"Step Type: {step_type}",
                        f"Step Value: {format_decimal(step_value)}",
                        f"Take Profit Type: {take_profit_type}",
                        f"Take Profit Value: {take_profit_value}",
                        "Risk Type: Fixed lots",
                        f"Risk: {risk_setting}",
                        "Multiplier Factor: 1.0",
                    ]
                )
        if rows:
            report.extend(
                [
                    "-" * 80,
                    f"{'Partial' if missing else 'Combined'} modeled loss: "
                    f"{format_decimal(total_estimated_loss, 2)} {currency} / "
                    f"80% account-wide allowance {format_decimal(portfolio_working_allowance, 2)} "
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
                if total_estimated_loss > effective_cap:
                    report.append(
                        "PORTFOLIO WARNING: combined modeled loss exceeds the "
                        "account-wide daily risk cap."
                    )
                elif total_estimated_loss > portfolio_working_allowance:
                    report.append(
                        "PORTFOLIO WARNING: modeled loss exceeds the 20% safety-reserved "
                        "working allowance."
                    )
                else:
                    report.append(
                        "Portfolio modeled loss is within the safety-reserved allowance."
                    )
        advanced_missing: tuple[str, ...] = ()
        advanced_breaches: tuple[str, ...] = ()
        if self.risk_profile["enabled"]:
            checks = check_exposures(
                self.risk_profile, account_capital,
                tuple(
                    ModeledExposure(
                        f"{row[0]} [{row[-1]}]", row[4], row[3], row[5],
                        self.exposure_inputs.get(row[-1], default_exposure()),
                    )
                    for row in rows
                ),
            )
            advanced_missing, advanced_breaches = checks.missing, checks.breaches
            report.extend((
                "",
                "ADVANCED PROP / MARGIN CONSTRAINTS",
                f"Overall rule: {self.risk_profile['overall_rule']}; "
                f"daily baseline: {self.risk_profile['daily_baseline']}; reset "
                f"{self.risk_profile['reset_time']} at fixed UTC offset "
                f"{self.risk_profile['utc_offset_minutes']} minutes (no DST).",
                "Multi-day grid sizing keeps the tighter current daily/overall room "
                "for the ENTIRE episode; daily resets never replenish its risk budget.",
                "Margin uses configured worst-case cash/lot and simultaneous maximum "
                "grid exposure; broker netting, hedged discounts and price-dependent "
                "margin are not inferred. Existing positions must be included in "
                "the entered margin, equity and remaining loss room.",
                *checks.lines,
                *("ADVANCED MISSING: " + item for item in checks.missing),
                *("ADVANCED BREACH: " + item for item in checks.breaches),
            ))
        else:
            report.append(
                "ADVANCED CHECKS DISABLED: verdict excludes margin, swap, per-idea "
                "groups and explicit reset/static/trailing equity rules. Enable "
                "'Advanced prop, margin & swap' to include them."
            )
        history_unverified = historical_mode and any(
            history_quality_warnings(self.historical_stresses[row[-1]])
            for row in rows
            if row[-1] in self.historical_stresses
        )
        if advanced_breaches:
            report.append(
                "PORTFOLIO VERDICT: REJECTED — advanced margin/idea constraints "
                "breached: " + "; ".join(advanced_breaches)
            )
        elif missing or prop_loss_room is None or history_unverified or advanced_missing:
            if missing:
                report.append("Not included (missing data): " + "; ".join(missing))
            report.append(
                "PORTFOLIO VERDICT: UNVERIFIED — complete market/contract data "
                "and remaining prop overall-loss room are required for acceptance. "
                "Historical modes also require recent, sufficiently populated "
                "five-year coverage (see HISTORY WARNING). Enabled advanced "
                "checks require all ADVANCED MISSING inputs."
            )
        elif rows:
            if total_estimated_loss <= portfolio_working_allowance:
                report.append(
                    "PORTFOLIO VERDICT: ACCEPTED under the configured historical "
                    "stress model (at most 80% of allocated loss allowance; "
                    "modeled risk grade: LOWER)."
                )
            elif total_estimated_loss <= allocated_daily_budget:
                report.append(
                    "PORTFOLIO VERDICT: NOT ACCEPTED under the 80% safety-buffer "
                    "rule (modeled risk grade: ELEVATED; the loss buffer is exceeded)."
                )
            else:
                report.append(
                    "PORTFOLIO VERDICT: REJECTED — modeled loss exceeds the "
                    "allocated prop-loss allowance (modeled risk grade: HIGH)."
                )
            report.append(
                "This verdict applies only to the configured historical estimate; "
                "it is not a prop-firm approval or a live-loss guarantee."
            )
        if not rows:
            report.append(
                "No combined estimate: connect MT5 or fetch Yahoo prices and history "
                "for the allocations; enter missing contract data in Robot settings."
            )
        if drawdown_mode:
            report.append(
                "Step Type/Value is shared from the selected row; verify it against "
                "each EA's actual configuration. The drawdown stress assumes no "
                "intermediate take-profit closes."
            )
        elif historical_mode:
            report.append(
                "Step Type/Value is shared from the selected row; verify it against "
                "each EA's actual configuration."
            )
        else:
            report.append(
                "Other robots use this row's Step Type/Value, Max Trades, and 1.0 "
                "multiplier for comparison; verify their actual EA settings."
            )
        return report

    def _generate_settings_checked(
        self,
        show_errors: bool = True,
        require_complete_portfolio: bool = False,
    ) -> None:
        self.generated_scenario = None
        self.generated_output = ""
        self.generated_requires_accepted_portfolio = require_complete_portfolio
        self.output_text.delete("1.0", "end")
        if not self._calculate_portfolio(show_error=show_errors):
            if require_complete_portfolio:
                raise ValueError(self.status_var.get())
            return
        if require_complete_portfolio and (
            self.stress_mode_var.get() != HISTORICAL_DRAWDOWN_MODE
            or self.position_direction_var.get() != "Long (price falls)"
        ):
            raise ValueError(
                "A full-portfolio suggestion requires the historical "
                "peak-to-trough downward stress scenario."
            )
        row_id = self._selected_row_id()
        if row_id is None:
            raise ValueError("Select an allocation.")
        allocation_result = self.allocation_results[row_id]
        robot_risk_budget = allocation_result.daily_loss_budget
        allocation = allocation_result.allocation
        contract = self._contract_inputs_for_allocation(row_id)
        spread_points, slippage_points, commission_per_lot = self._sizing_costs(
            row_id, contract
        )
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
        account_currency = self.currency_var.get().strip().upper()
        value_currency = contract["contract_currency"].strip().upper()
        if not account_currency or value_currency != account_currency:
            raise ValueError(
                "Risk suggestions need point value expressed in the account currency. "
                "Enter the account currency and matching MT5 contract currency; "
                "automatic currency conversion is not applied."
            )
        if row_id not in self.quotes:
            raise ValueError(
                "Connect MT5 or fetch a Yahoo price/history for this allocation first."
            )
        price, quote_currency, yahoo_symbol, quote_time = self.quotes[row_id]
        price_in_account = decimal_value(
            self.reference_price_var.get(), "Market reference price"
        )
        if price_in_account <= ZERO:
            raise ValueError("Market reference price must be greater than zero.")

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
        stress_mode = self.stress_mode_var.get()
        historical_mode = stress_mode in HISTORICAL_STRESS_MODES
        drawdown_mode = stress_mode == HISTORICAL_DRAWDOWN_MODE
        historical_worst_day = ""
        if self.stress_mode_var.get() == "Target price":
            target_price = decimal_value(
                self.stress_target_price_var.get(), "Stress target price"
            )
            if target_price <= ZERO:
                raise ValueError("Stress target price must be greater than zero.")
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
                    "Connect MT5 or fetch Yahoo daily history for this "
                    "allocation before using historical stress settings."
                )
            stress_percent = historical_stress_move(
                historical_stress, stress_mode, is_long
            )
            if stress_percent <= ZERO or (
                is_long and stress_percent >= ONE_HUNDRED
            ):
                move_name = (
                    "peak-to-trough drawdown"
                    if drawdown_mode
                    else "daily adverse move"
                )
                raise ValueError(
                    f"No valid historical {move_name} is available "
                    "(must be positive and, for long positions, below 100%). "
                    "Refresh the history before generating settings."
                )
            historical_worst_day = historical_stress_period(
                historical_stress, stress_mode, is_long
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
            if stress_percent <= ZERO or (
                is_long and stress_percent >= ONE_HUNDRED
            ):
                raise ValueError(
                    "Adverse stress move percent must be greater than 0 and, "
                    "for long positions, less than 100."
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
        maximum_lot_text = contract.get("maximum_lot", "").strip()
        broker_maximum_lot = (
            decimal_value(maximum_lot_text, f"{allocation.index} broker maximum lot")
            if maximum_lot_text
            else None
        )
        if lot_increment <= ZERO or minimum_lot <= ZERO:
            raise ValueError("Broker lot increment and minimum lot must be greater than zero.")
        if broker_maximum_lot is not None and broker_maximum_lot < minimum_lot:
            raise ValueError("Broker maximum lot cannot be below the minimum lot.")

        compare_count = positive_integer(
            self.compare_trades_var.get(), "Max Trades candidates"
        )
        if compare_count > 20:
            raise ValueError("Compare at most 20 Max Trades values.")
        if historical_mode:
            mt5_bars = self.history_bars.get(row_id)
            if mt5_bars and not drawdown_mode:
                suggestion = suggest_safe_grid_settings_from_history(
                    bars=mt5_bars,
                    point_size=point_size,
                    point_value_per_lot=point_value,
                    step_value=(
                        step_value if step_type != "enum_fixed_pips" else step_points
                    ),
                    step_is_percentage=step_type != "enum_fixed_pips",
                    daily_budget=robot_risk_budget,
                    lot_step=lot_increment,
                    minimum_lot=minimum_lot,
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                    is_long=is_long,
                    maximum_lot=broker_maximum_lot,
                    max_trades_limit=compare_count,
                )
            else:
                suggestion = suggest_safe_grid_settings(
                    stress_points=stress_points,
                    step_points=step_points,
                    point_value_per_lot=point_value,
                    daily_budget=robot_risk_budget,
                    lot_step=lot_increment,
                    minimum_lot=minimum_lot,
                    spread_points=historical_spread_floor(
                        mt5_bars or (), spread_points
                    )
                    if drawdown_mode
                    else spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                    maximum_lot=broker_maximum_lot,
                    max_trades_limit=compare_count,
                )
            if suggestion.worst_date:
                historical_worst_day = suggestion.worst_date
                stress_points = suggestion.stress_points
                adverse_difference = stress_points * point_size
                stress_percent = adverse_difference * ONE_HUNDRED / price_in_account
                target_price = (
                    price_in_account - adverse_difference
                    if is_long
                    else price_in_account + adverse_difference
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

        candidate_spread_points = (
            historical_spread_floor(
                self.history_bars.get(row_id, ()), spread_points
            )
            if drawdown_mode
            else spread_points
        )
        candidates: dict[int, tuple[Decimal, Decimal]] = {}
        for trades in range(1, compare_count + 1):
            if historical_mode and not drawdown_mode and self.history_bars.get(row_id):
                calculation = replay_historical_grid(
                    bars=self.history_bars[row_id],
                    point_size=point_size,
                    point_value_per_lot=point_value,
                    step_value=(
                        step_value if step_type != "enum_fixed_pips" else step_points
                    ),
                    step_is_percentage=step_type != "enum_fixed_pips",
                    initial_lot=ONE,
                    max_trades=trades,
                    multiplier=ONE,
                    daily_budget=robot_risk_budget,
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                    is_long=is_long,
                )
                calculated_maximum_lot = calculation.recommended_max_lot
            else:
                calculation = calculate_grid_stress(
                    initial_lot=ONE,
                    point_value_per_lot=point_value,
                    step_points=step_points,
                    multiplier=ONE,
                    max_trades=trades,
                    stress_points=stress_points,
                    daily_budget=robot_risk_budget,
                    spread_points=candidate_spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                )
                calculated_maximum_lot = calculation.recommended_max_lot
            lot = (
                (calculated_maximum_lot / lot_increment)
                .to_integral_value(rounding=ROUND_FLOOR)
                * lot_increment
            )
            if broker_maximum_lot is not None:
                lot = min(
                    lot,
                    (broker_maximum_lot / lot_increment)
                    .to_integral_value(rounding=ROUND_FLOOR)
                    * lot_increment,
                )
            candidate_lot = lot if lot >= minimum_lot else minimum_lot
            if historical_mode and not drawdown_mode and self.history_bars.get(row_id):
                loss = replay_historical_grid(
                    bars=self.history_bars[row_id],
                    point_size=point_size,
                    point_value_per_lot=point_value,
                    step_value=(
                        step_value if step_type != "enum_fixed_pips" else step_points
                    ),
                    step_is_percentage=step_type != "enum_fixed_pips",
                    initial_lot=candidate_lot,
                    max_trades=trades,
                    multiplier=ONE,
                    daily_budget=robot_risk_budget,
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                    is_long=is_long,
                ).estimated_loss
            else:
                loss = calculate_grid_stress(
                    initial_lot=candidate_lot,
                    point_value_per_lot=point_value,
                    step_points=step_points,
                    multiplier=ONE,
                    max_trades=trades,
                    stress_points=stress_points,
                    daily_budget=robot_risk_budget,
                    spread_points=candidate_spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
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
        risk_setting = (
            "0.0"
            if selected_lot == minimum_lot
            else format_decimal(selected_lot)
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
        take_profit_value: Decimal | None = None
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
            f"Allocation ID: {row_id}",
            f"Market reference ({self.history_sources.get(row_id, 'Yahoo')}): "
            f"{yahoo_symbol} = {format_decimal(price_in_account)} "
            f"{quote_currency} ({quote_time})",
            f"Tested adverse target: {format_decimal(target_price)} "
            f"({self.position_direction_var.get()})",
            f"Adverse move: {format_decimal(stress_percent, 2)}% = "
            f"{format_decimal(stress_points, 2)} MT5 points",
            f"Robot daily risk budget: "
            f"{format_decimal(robot_risk_budget, 2)} "
            f"{self.currency_var.get().strip() or 'account currency'}",
            f"Risk allowance used (80%): "
            f"{format_decimal(robot_risk_budget * Decimal('0.8'), 2)}",
            "",
            "MAX TRADES CANDIDATES (Multiplier Factor = 1.0)",
            f"{'Max Trades':>12} {'Risk Type':>14} {'Risk (lots)':>16}",
            "-" * 46,
        ]
        if historical_mode and historical_stress is not None:
            observed_date = historical_stress_period(
                historical_stress, stress_mode, is_long
            )
            if historical_worst_day:
                observed_date = historical_worst_day
            output.extend(
                [
                    (
                        "Historical basis: largest adverse historical episode. All grid entries "
                        "are assumed to remain open until the adverse extreme; intermediate "
                        "take-profit closes are not credited."
                        if drawdown_mode
                        else "Historical basis: independent daily OHLC shocks. MT5 bars are "
                        "used when imported; otherwise Yahoo's 5-year daily history."
                    ),
                    f"Valid daily bars: {historical_stress.bar_count} "
                    f"({historical_stress.start_date} to {historical_stress.end_date})",
                    (
                        f"Historical adverse episode: {observed_date}"
                        if drawdown_mode
                        else f"Worst {self.position_direction_var.get()} session: "
                        f"{observed_date}"
                    ),
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
                f"Risk: {risk_setting}",
                "Multiplier Factor: 1.0",
            ]
        )

        if robot == "DCA":
            enabled = self.entry_break_var.get()
            price_break_type = self.price_break_type_var.get()
            if price_break_type == "break Above":
                price_break_type = "break above"
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
                    f"InpPriceBreakType: {price_break_type}",
                    f"Reference Price: {format_decimal(reference_price)}",
                    f"Trade on new candle: {str(self.trade_new_candle_var.get()).lower()}",
                    "Show Invested Money: true",
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
                f"Transaction-cost model per trade: configured spread floor "
                f"{format_decimal(spread_points)} points + slippage "
                f"{format_decimal(slippage_points)} points + round-turn commission"
                f"{' including prepaid swap reserve' if self.risk_profile['enabled'] else ''} "
                f"{format_decimal(commission_per_lot)} per 1.00 lot.",
                f"Estimated loss at selected settings: "
                f"{format_decimal(selected_loss, 2)} "
                f"{self.currency_var.get().strip() or 'account currency'}",
            ]
        )
        mt5_bars = self.history_bars.get(row_id, ())
        observed_spreads = [
            bar.spread_points
            for bar in mt5_bars
            if bar.spread_points is not None
        ]
        if historical_mode and observed_spreads:
            sampled_bars = [
                bar
                for bar in mt5_bars
                if bar.spread_sample_count is not None
            ]
            tick_sample_count = sum(
                bar.spread_sample_count or 0 for bar in sampled_bars
            )
            tick_sampled_bar_count = sum(
                (bar.spread_sample_count or 0) > 0 for bar in sampled_bars
            )
            output.append(
                "Observed MT5 spread maximum: "
                f"{format_decimal(max(observed_spreads))} points; "
                "applied as a per-bar spread floor against the configured value."
            )
            if tick_sample_count:
                output.append(
                    "Tick-derived spread observations: "
                    f"{tick_sample_count} valid Bid/Ask updates across "
                    f"{tick_sampled_bar_count} bars. "
                    "This is not a guarantee that every spread spike was captured."
                )
            elif sampled_bars:
                output.append(
                    "No valid tick Bid/Ask spreads were exported; bars use the "
                    "MT5 bar spread fallback."
                )
        if not mt5_bars:
            output.extend(
                [
                    "",
                    "CHRONOLOGICAL GRID CAMPAIGN SIMULATION: not run; connect MT5 "
                    "and fetch broker history first (Yahoo-only history is not sufficient).",
                ]
            )
        elif not take_profit_text:
            output.extend(
                [
                    "",
                    "CHRONOLOGICAL GRID CAMPAIGN SIMULATION: not run; enter a "
                    "strategy-specific Take Profit Value first.",
                ]
            )
        else:
            assert take_profit_value is not None
            if self.take_profit_type_var.get() == "Fixed pips":
                points_per_pip_text = contract["points_per_pip"].strip()
                take_profit_points = (
                    take_profit_value
                    * decimal_value(
                        points_per_pip_text,
                        f"{allocation.index} points per EA pip",
                    )
                    if points_per_pip_text
                    else ZERO
                )
            else:
                take_profit_points = (
                    price_in_account
                    * take_profit_value
                    / ONE_HUNDRED
                    / point_size
                )
            if take_profit_points <= ZERO:
                output.extend(
                    [
                        "",
                        "CHRONOLOGICAL GRID CAMPAIGN SIMULATION: not run; "
                        "a positive points-per-pip value is required for "
                        "fixed-pips Take Profit.",
                    ]
                )
            else:
                campaign = backtest_historical_grid_campaign(
                    bars=mt5_bars,
                    initial_equity=allocation.capital,
                    point_size=point_size,
                    point_value_per_lot=point_value,
                    step_points=step_points,
                    take_profit_points=take_profit_points,
                    initial_lot=selected_lot,
                    max_trades=selected_trades,
                    multiplier=ONE,
                    spread_points=spread_points,
                    slippage_points=slippage_points,
                    commission_per_lot=commission_per_lot,
                    is_long=is_long,
                )
                output.extend(
                    [
                        "",
                        "CHRONOLOGICAL GRID CAMPAIGN SIMULATION "
                        "(generic OHLC model)",
                        f"Bars: {len(mt5_bars)} daily bars; campaign period "
                        f"{mt5_bars[0].date} to {campaign.end_date}.",
                        f"Net result: {format_decimal(campaign.net_profit, 2)} "
                        f"{self.currency_var.get().strip() or 'account currency'} "
                        f"on allocation equity "
                        f"{format_decimal(campaign.initial_equity, 2)}.",
                        f"Maximum peak-to-trough equity drawdown: "
                        f"{format_decimal(campaign.max_drawdown_cash, 2)} "
                        f"{self.currency_var.get().strip() or 'account currency'}, "
                        f"{campaign.drawdown_peak_date} to "
                        f"{campaign.drawdown_trough_date}.",
                        f"Maximum percentage equity drawdown: "
                        f"{format_decimal(campaign.max_drawdown_pct, 2)}% "
                        "(tracked independently of the cash maximum).",
                        f"Worst modeled daily equity loss: "
                        f"{format_decimal(campaign.worst_daily_loss, 2)} "
                        f"on {campaign.worst_daily_loss_date}.",
                        (
                            "Daily allowance check (80% reserved budget): PASS."
                            if campaign.worst_daily_loss
                            <= robot_risk_budget * Decimal("0.8")
                            else "WARNING: modeled daily loss exceeds the "
                            "80%-reserved account-wide allowance."
                        ),
                        f"Maximum concurrent entries: "
                        f"{campaign.max_open_trades}; basket TP closes: "
                        f"{campaign.take_profit_count}.",
                        (
                            "WARNING: the grid reached Max Trades while price "
                            "crossed the next entry level."
                            if campaign.grid_exhausted
                            else "The grid did not cross its next entry level "
                            "after reaching Max Trades."
                        ),
                        "This is one campaign only: the model does not create "
                        "another campaign after TP because the EA entry signal "
                        "is unknown.",
                        "Execution assumption: market-on-threshold entries; "
                        "gaps fill at the daily open and reanchor the next step. "
                        "An opening gap beyond basket TP closes at that open "
                        "before later intraday moves. This is not a pending-order model.",
                        (
                            "WARNING: history has missing daily opens; those bars "
                            "use the previous close clamped to their high/low range. "
                            "Gap execution is approximate; refresh MT5 history."
                            if any(bar.open is None for bar in mt5_bars[1:])
                            else "Daily opens are available for gap modeling; "
                            "intraday order still uses the adverse-first assumption."
                        ),
                        "",
                    ]
                )
        portfolio_report = self._portfolio_stress_report(
            row_id,
            step_type,
            step_value,
            stress_percent,
            selected_trades,
            magic_number,
            take_profit_type,
            take_profit_output,
            require_complete_portfolio,
        )
        output.extend(portfolio_report)
        output.extend(
            [
                "",
                "IMPORTANT:",
                "- The step and take-profit values are strategy choices, not values "
                "derived from the daily drawdown limit.",
                "- Yahoo prices may be delayed and differ from the broker CFD; "
                "imported MT5 bars are broker-specific but do not predict future execution.",
                "- Point value and volume rules must match the MT5 broker contract.",
                "- Candidate sizing's historical replay treats daily OHLC bars as "
                "independent shocks. The separate chronological campaign model keeps "
                "grid entries overnight but uses an assumed adverse-first daily path; "
                "it does not model RSI signals, dynamic margin/liquidation, actual "
                "swap accrual or exact EA execution. Enabled advanced checks add a "
                "prepaid swap reserve and a separate maximum-exposure margin screen.",
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
        self.generated_output = "\n".join(output).strip()
        self.generated_scenario = self._scenario_data()
        self._schedule_autosave()
        self.status_var.set(
            f"Settings generated for {allocation.index} / {robot}; review broker units."
        )

    def _validated_generated_output(self) -> str:
        if self.generated_scenario is None:
            raise ValueError("Generate candidate settings first.")
        content = self.output_text.get("1.0", "end").strip()
        if (
            content != self.generated_output
            or self._scenario_data() != self.generated_scenario
        ):
            raise ValueError(
                "Inputs, market data, selection, or report text have changed. "
                "Regenerate candidate settings before copying or exporting."
            )
        if (
            self.generated_requires_accepted_portfolio
            and "PORTFOLIO VERDICT: ACCEPTED" not in content
        ):
            raise ValueError(
                "Full-portfolio settings can only be copied or exported when "
                "the final portfolio verdict is ACCEPTED. Review the report."
            )
        return content

    def _copy_output(self) -> None:
        content = self.output_text.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo(
                "Nothing to copy",
                "Generate settings first.",
                parent=self,
            )
            return
        if self.generated_scenario is not None:
            try:
                content = self._validated_generated_output()
            except ValueError as error:
                self.status_var.set("Settings copy blocked; regenerate candidate settings.")
                messagebox.showerror("Cannot copy outdated settings", str(error), parent=self)
                return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_var.set("Settings copied to clipboard.")

    def _export_set_template(self) -> None:
        try:
            content = self._validated_generated_output()
        except ValueError as error:
            self.status_var.set("MT5 .set export blocked; regenerate candidate settings.")
            messagebox.showerror("Cannot export settings", str(error), parent=self)
            return
        selected_start = next(
            (
                line
                for line in content.splitlines()
                if line.startswith("SELECTED ") and line.endswith(" EA SETTINGS")
            ),
            None,
        )
        if selected_start is None:
            messagebox.showinfo(
                "Generate settings first",
                "Generate candidate settings before exporting a .set template.",
                parent=self,
            )
            return
        robot = selected_start.removeprefix("SELECTED ").removesuffix(" EA SETTINGS")
        settings: dict[str, str] = {}
        for line in content.splitlines():
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            if key in {
                "Magic Number",
                "Max Trades",
                "Step Type",
                "Step Value",
                "Take Profit Type",
                "Take Profit Value",
                "Risk Type",
                "Risk",
                "Multiplier Factor",
                "Entry on price break",
                "InpPriceBreakType",
                "Reference Price",
                "Trade on new candle",
                "Show Invested Money",
                "Close When Overbought",
                "RSI oversold",
                "RSI Overbought",
                "RSI Period",
            }:
                settings[key] = value
        try:
            preset_text = build_mt5_set_template(robot, settings)
        except ValueError as error:
            messagebox.showerror(
                "Could not create .set template", str(error), parent=self
            )
            return

        row_id = self._selected_row_id()
        symbol = self.allocations[row_id].index if row_id else "robot"
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export MT5 .set template",
            defaultextension=".set",
            filetypes=(("MT5 set files", "*.set"), ("All files", "*.*")),
            initialfile=f"{symbol}_{robot}.set",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as preset_file:
                preset_file.write(preset_text)
        except OSError as error:
            messagebox.showerror(
                "Could not save .set template", str(error), parent=self
            )
            self.status_var.set("MT5 .set export failed.")
            return
        self.status_var.set(f"MT5 .set template exported: {path}")
        messagebox.showwarning(
            "Verify the MT5 inputs",
            "This .set file uses canonical input names and enum order based on the "
            "provided parameter list. The EA source or an existing .set preset was "
            "not available to verify its actual input identifiers. Check every field "
            "in MT5 before loading it on a live account.",
            parent=self,
        )


if __name__ == "__main__":
    RiskCalculatorApp().mainloop()
