"""Explicit cash-based prop constraints; no broker or EA semantics are inferred."""

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import TypedDict


ZERO = Decimal("0")
HUNDRED = Decimal("100")


class RiskProfile(TypedDict):
    enabled: bool
    current_equity: str
    daily_start_equity: str
    daily_start_balance: str
    daily_session_date: str
    daily_baseline: str
    overall_rule: str
    total_limit_pct: str
    high_water_equity: str
    reset_time: str
    utc_offset_minutes: str
    idea_limit_pct: str
    free_margin: str
    existing_margin: str
    stopout_pct: str
    holding_days: str


class ExposureInputs(TypedDict):
    margin_per_lot: str
    swap_long_debit: str
    swap_short_debit: str
    idea_group: str


def default_profile() -> RiskProfile:
    return RiskProfile(
        enabled=False, current_equity="", daily_start_equity="",
        daily_start_balance="", daily_session_date="", daily_baseline="Equity", overall_rule="Static",
        total_limit_pct="", high_water_equity="", reset_time="00:00",
        utc_offset_minutes="0", idea_limit_pct="", free_margin="",
        existing_margin="", stopout_pct="", holding_days="0",
    )


def default_exposure() -> ExposureInputs:
    return ExposureInputs(
        margin_per_lot="", swap_long_debit="", swap_short_debit="", idea_group=""
    )


def number(text: str, label: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"{label} must be numeric.") from error
    if not result.is_finite() or result < ZERO or (positive and result == ZERO):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'non-negative'}.")
    return result


def reset_zone(profile: RiskProfile) -> tuple[timezone, int, int]:
    try:
        hour, minute = (int(part) for part in profile["reset_time"].split(":"))
        offset = int(profile["utc_offset_minutes"])
    except (ValueError, TypeError) as error:
        raise ValueError("Reset needs HH:MM and an integer UTC offset in minutes.") from error
    if (
        not 0 <= hour <= 23 or not 0 <= minute <= 59 or not -840 <= offset <= 840
        or profile["reset_time"] != f"{hour:02d}:{minute:02d}"
    ):
        raise ValueError("Invalid reset time or UTC offset (allowed -840 to 840 minutes).")
    return timezone(timedelta(minutes=offset)), hour, minute


def validate_profile(value: object) -> RiskProfile:
    if not isinstance(value, dict):
        raise ValueError("Advanced risk profile must be an object.")
    profile = default_profile()
    for key in profile:
        if key not in value:
            raise ValueError(f"Advanced risk profile is missing {key}.")
    if not isinstance(value["enabled"], bool):
        raise ValueError("Advanced risk enabled must be boolean.")
    profile["enabled"] = value["enabled"]
    # Explicit assignments preserve the TypedDict shape for scenario boundaries.
    for key in (
        "current_equity", "daily_start_equity", "daily_start_balance",
        "daily_session_date",
        "daily_baseline", "overall_rule", "total_limit_pct", "high_water_equity",
        "reset_time", "utc_offset_minutes", "idea_limit_pct", "free_margin",
        "existing_margin", "stopout_pct", "holding_days",
    ):
        if not isinstance(value[key], str):
            raise ValueError(f"Advanced risk {key} must be text.")
    profile.update(
        current_equity=value["current_equity"].strip(),
        daily_start_equity=value["daily_start_equity"].strip(),
        daily_start_balance=value["daily_start_balance"].strip(),
        daily_session_date=value["daily_session_date"].strip(),
        daily_baseline=value["daily_baseline"],
        overall_rule=value["overall_rule"],
        total_limit_pct=value["total_limit_pct"].strip(),
        high_water_equity=value["high_water_equity"].strip(),
        reset_time=value["reset_time"],
        utc_offset_minutes=value["utc_offset_minutes"].strip(),
        idea_limit_pct=value["idea_limit_pct"].strip(),
        free_margin=value["free_margin"].strip(),
        existing_margin=value["existing_margin"].strip(),
        stopout_pct=value["stopout_pct"].strip(),
        holding_days=value["holding_days"].strip(),
    )
    if profile["daily_baseline"] not in ("Equity", "Balance", "Higher of balance/equity"):
        raise ValueError("Unsupported daily baseline.")
    if profile["overall_rule"] not in ("Static", "Trailing equity"):
        raise ValueError("Unsupported overall rule.")
    reset_zone(profile)
    if profile["daily_session_date"]:
        try:
            parsed_date = datetime.strptime(profile["daily_session_date"], "%Y-%m-%d").date()
        except ValueError as error:
            raise ValueError("Daily session date must be YYYY-MM-DD.") from error
        if parsed_date.isoformat() != profile["daily_session_date"]:
            raise ValueError("Daily session date must be YYYY-MM-DD.")
    for field in (
        "current_equity", "daily_start_equity", "daily_start_balance",
        "total_limit_pct", "high_water_equity", "idea_limit_pct",
        "free_margin", "existing_margin", "stopout_pct",
    ):
        text = profile[field]
        if text:
            result = number(text, field)
            if field in ("total_limit_pct", "idea_limit_pct") and not ZERO < result <= HUNDRED:
                raise ValueError(f"{field} must be greater than 0 and at most 100.")
    days = profile["holding_days"]
    if not days.isascii() or not days.isdigit() or int(days) > 3650:
        raise ValueError("Holding days must be an integer from 0 to 3650.")
    return profile


def validate_exposure(value: object) -> ExposureInputs:
    if not isinstance(value, dict):
        raise ValueError("Exposure inputs must be an object.")
    for key in default_exposure():
        if not isinstance(value.get(key), str):
            raise ValueError(f"Exposure input {key} must be text.")
    exposure = ExposureInputs(
        margin_per_lot=value["margin_per_lot"].strip(),
        swap_long_debit=value["swap_long_debit"].strip(),
        swap_short_debit=value["swap_short_debit"].strip(),
        idea_group=value["idea_group"].strip(),
    )
    for field in ("margin_per_lot", "swap_long_debit", "swap_short_debit"):
        if exposure[field]:
            number(exposure[field], field, positive=field == "margin_per_lot")
    if len(exposure["idea_group"]) > 100:
        raise ValueError("Idea group must not exceed 100 characters.")
    return exposure


def daily_baseline(profile: RiskProfile, equity: Decimal, balance: Decimal) -> Decimal:
    if profile["daily_baseline"] == "Balance":
        return balance
    if profile["daily_baseline"] == "Higher of balance/equity":
        return max(balance, equity)
    return equity


def remaining_rooms(
    profile: RiskProfile, initial_balance: Decimal, daily_limit: Decimal,
    now: datetime | None = None,
) -> tuple[Decimal, Decimal]:
    zone, hour, minute = reset_zone(profile)
    local = (now or datetime.now(timezone.utc)).astimezone(zone)
    session = (local - timedelta(hours=hour, minutes=minute)).date().isoformat()
    if profile["daily_session_date"] != session:
        raise ValueError(
            f"Daily baseline is missing/stale: confirm equity and balance at the "
            f"configured reset for session {session}, then enter that session date."
        )
    equity = number(profile["current_equity"], "Current equity", positive=True)
    start_equity = number(profile["daily_start_equity"], "Daily start equity", positive=True)
    start_balance = number(profile["daily_start_balance"], "Daily start balance", positive=True)
    overall = number(profile["total_limit_pct"], "Overall loss percent", positive=True)
    peak = initial_balance
    if profile["overall_rule"] == "Trailing equity":
        peak = number(profile["high_water_equity"], "High-water equity", positive=True)
        if peak < max(initial_balance, equity):
            raise ValueError("High-water equity cannot be below initial balance or current equity.")
    baseline = daily_baseline(profile, start_equity, start_balance)
    return (
        max(ZERO, equity - (baseline - daily_limit)),
        max(ZERO, equity - (peak - initial_balance * overall / HUNDRED)),
    )


@dataclass(frozen=True)
class ModeledExposure:
    label: str
    lots: Decimal
    trades: int
    loss: Decimal
    inputs: ExposureInputs


@dataclass(frozen=True)
class ConstraintResult:
    lines: tuple[str, ...]
    missing: tuple[str, ...]
    breaches: tuple[str, ...]


def check_exposures(
    profile: RiskProfile, initial_balance: Decimal,
    exposures: tuple[ModeledExposure, ...],
) -> ConstraintResult:
    lines: list[str] = []
    missing: list[str] = []
    breaches: list[str] = []
    margin = ZERO
    groups: dict[str, Decimal] = {}
    for item in exposures:
        data = item.inputs
        if not data["margin_per_lot"]:
            missing.append(f"{item.label}: margin per lot")
        else:
            requirement = number(data["margin_per_lot"], "Margin per lot", positive=True)
            requirement *= item.lots * item.trades
            margin += requirement
            lines.append(f"{item.label}: maximum grid margin {requirement}.")
        if not data["idea_group"]:
            missing.append(f"{item.label}: correlated idea group")
        else:
            group = data["idea_group"].casefold()
            groups[group] = groups.get(group, ZERO) + item.loss
    if not profile["idea_limit_pct"]:
        missing.append("Per-idea loss limit percent")
    else:
        cap = initial_balance * number(profile["idea_limit_pct"], "Idea limit") / HUNDRED
        for group, loss in groups.items():
            lines.append(f"Idea {group}: modeled loss {loss} / cap {cap}.")
            if loss >= cap:
                breaches.append(f"Idea {group} reaches/exceeds its loss cap.")
    for field in ("free_margin", "existing_margin", "stopout_pct", "current_equity"):
        if not profile[field]:
            missing.append(field)
    margin_complete = all(item.inputs["margin_per_lot"] for item in exposures) and all(
        profile[field] for field in ("free_margin", "existing_margin", "stopout_pct", "current_equity")
    )
    if margin_complete:
        free = number(profile["free_margin"], "Free margin")
        existing = number(profile["existing_margin"], "Existing margin")
        equity = number(profile["current_equity"], "Current equity", positive=True)
        if abs(equity - existing - free) > Decimal("0.02"):
            raise ValueError("Equity, existing margin and free margin must reconcile within 0.02 cash.")
        loss = sum((item.loss for item in exposures), ZERO)
        stressed_equity = equity - loss
        used = existing + margin
        lines.append(f"Combined grid margin {margin}; stressed equity {stressed_equity}; used margin {used}.")
        if margin + loss >= free:
            breaches.append("Stressed grid margin and losses exhaust available free margin.")
        if used > ZERO and stressed_equity / used * HUNDRED <= number(profile["stopout_pct"], "Stop-out"):
            breaches.append("Stressed margin level reaches/breaches the configured percent stop-out.")
    return ConstraintResult(tuple(lines), tuple(missing), tuple(breaches))


@dataclass(frozen=True)
class EquitySample:
    time: datetime
    balance: Decimal
    equity: Decimal


def parse_equity_csv(text: str) -> tuple[EquitySample, ...]:
    reader = csv.DictReader(text.lstrip("\ufeff").splitlines(), strict=True)
    if reader.fieldnames != ["timestamp", "balance", "equity"]:
        raise ValueError("Equity CSV header must be exactly timestamp,balance,equity.")
    samples = []
    try:
        rows = list(reader)
    except csv.Error as error:
        raise ValueError(f"Invalid equity CSV: {error}") from error
    for position, row in enumerate(rows, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Equity CSV row {position} is incomplete or has extra columns.")
        try:
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("Timestamp needs an explicit UTC offset.")
            sample = EquitySample(
                timestamp.astimezone(timezone.utc),
                number(row["balance"], "Balance", positive=True),
                number(row["equity"], "Equity"),
            )
        except (ValueError, TypeError, AttributeError, KeyError) as error:
            raise ValueError(f"Equity CSV row {position}: {error}") from error
        if samples and sample.time <= samples[-1].time:
            raise ValueError("Equity timestamps must be unique and increasing.")
        samples.append(sample)
    if len(samples) < 2:
        raise ValueError("Equity curve needs at least two samples.")
    return tuple(samples)


def evaluate_equity_curve(
    samples: tuple[EquitySample, ...], profile: RiskProfile,
    initial_balance: Decimal, daily_limit: Decimal,
) -> ConstraintResult:
    if len(samples) < 2:
        raise ValueError("Equity curve needs at least two samples.")
    zone, hour, minute = reset_zone(profile)
    total_cash = initial_balance * number(
        profile["total_limit_pct"], "Overall loss percent", positive=True
    ) / HUNDRED
    peak = initial_balance
    if profile["overall_rule"] == "Trailing equity":
        peak = number(profile["high_water_equity"], "Starting high-water equity", positive=True)
        if peak < max(initial_balance, samples[0].equity):
            raise ValueError("Starting high-water equity must cover initial balance and first equity.")
    day_key = None
    daily_known = False
    baseline = ZERO
    missing: list[str] = []
    breaches: list[str] = []
    max_daily = ZERO
    max_overall = ZERO
    previous = None
    for sample in samples:
        if previous is not None and sample.time <= previous:
            raise ValueError("Equity samples must be strictly chronological.")
        previous = sample.time
        local = sample.time.astimezone(zone)
        shifted = local - timedelta(hours=hour, minutes=minute)
        key = shifted.date()
        if key != day_key:
            exact_reset = (
                local.hour == hour and local.minute == minute
                and local.second == 0 and local.microsecond == 0
            )
            if not exact_reset:
                missing.append(f"{key}: no exact equity/balance sample at daily reset.")
            daily_known = exact_reset
            if day_key is not None and (key - day_key).days > 1:
                missing.append(f"{day_key} to {key}: missing daily sessions.")
            day_key = key
            baseline = daily_baseline(profile, sample.equity, sample.balance)
        daily_loss = max(ZERO, baseline - sample.equity)
        max_daily = max(max_daily, daily_loss)
        if profile["overall_rule"] == "Trailing equity":
            peak = max(peak, sample.equity)
        overall_loss = max(ZERO, peak - sample.equity)
        max_overall = max(max_overall, overall_loss)
        if daily_known and sample.equity <= baseline - daily_limit:
            breaches.append(f"{sample.time.isoformat()}: daily equity floor reached/breached.")
        if sample.equity <= peak - total_cash:
            breaches.append(f"{sample.time.isoformat()}: overall equity floor reached/breached.")
    return ConstraintResult(
        (
            f"Samples: {len(samples)}; {samples[0].time.isoformat()} to {samples[-1].time.isoformat()}.",
            f"Maximum sampled daily loss: {max_daily}; daily cap: {daily_limit}.",
            f"Maximum sampled {profile['overall_rule']} drawdown: {max_overall}; total cap: {total_cash}.",
            "Sampled results only: unobserved intrabar equity, deposits/withdrawals and missing resets "
            "cannot be reconstructed. Use an unchanged-capital, single-account curve.",
        ),
        tuple(missing), tuple(breaches),
    )
