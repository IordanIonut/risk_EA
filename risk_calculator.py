"""Portfolio cash-risk, grid-stress, and historical OHLC calculations.

For the desktop interface, open risk_calculator_app.pyw.
Terminal fallback: python risk_calculator.py
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import sys
from typing import Sequence


ZERO = Decimal("0")
ONE = Decimal("1")
ONE_HUNDRED = Decimal("100")
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Allocation:
    index: str
    robot: str
    capital: Decimal


@dataclass(frozen=True)
class AllocationResult:
    allocation: Allocation
    account_share_pct: Decimal
    daily_loss_budget: Decimal


@dataclass(frozen=True)
class PortfolioResult:
    account_capital: Decimal
    daily_loss_limit: Decimal
    allocated_capital: Decimal
    reserved_capital: Decimal
    allocated_daily_budget: Decimal
    reserved_daily_budget: Decimal
    allocations: tuple[AllocationResult, ...]


@dataclass(frozen=True)
class StressResult:
    estimated_loss: Decimal
    loss_budget: Decimal
    recommended_max_lot: Decimal
    max_trades_within_budget: int


@dataclass(frozen=True)
class DailyBar:
    date: str
    high: Decimal
    low: Decimal
    close: Decimal
    spread_points: Decimal | None = None
    spread_sample_count: int | None = None
    open: Decimal | None = None


@dataclass(frozen=True)
class HistoricalStress:
    long_adverse_pct: Decimal
    long_observed_date: str
    short_adverse_pct: Decimal
    short_observed_date: str
    bar_count: int
    start_date: str
    end_date: str
    long_drawdown_pct: Decimal = ZERO
    long_drawdown_peak_date: str = ""
    long_drawdown_trough_date: str = ""
    short_rally_pct: Decimal = ZERO
    short_rally_trough_date: str = ""
    short_rally_peak_date: str = ""


@dataclass(frozen=True)
class GridSettingsSuggestion:
    max_trades: int
    initial_lot: Decimal
    estimated_loss: Decimal
    loss_budget: Decimal
    stress_points: Decimal
    step_points: Decimal
    worst_date: str = ""


@dataclass(frozen=True)
class HistoricalGridStress:
    estimated_loss: Decimal
    loss_budget: Decimal
    recommended_max_lot: Decimal
    worst_date: str
    stress_points: Decimal
    step_points: Decimal


@dataclass(frozen=True)
class HistoricalGridBacktest:
    initial_equity: Decimal
    final_equity: Decimal
    net_profit: Decimal
    max_drawdown_cash: Decimal
    max_drawdown_pct: Decimal
    drawdown_peak_date: str
    drawdown_trough_date: str
    worst_daily_loss: Decimal
    worst_daily_loss_date: str
    take_profit_count: int
    max_open_trades: int
    grid_exhausted: bool
    end_date: str


def calculate_portfolio(
    account_capital: Decimal,
    daily_loss_limit: Decimal,
    allocations: Sequence[Allocation],
) -> PortfolioResult:
    """Distribute the account's daily cash limit in proportion to allocated capital."""
    if not account_capital.is_finite() or not daily_loss_limit.is_finite():
        raise ValueError("Account capital and daily loss limit must be finite numbers.")
    if account_capital <= ZERO:
        raise ValueError("Account capital must be greater than zero.")
    if daily_loss_limit <= ZERO:
        raise ValueError("Daily loss limit must be greater than zero.")
    if daily_loss_limit > account_capital:
        raise ValueError("Daily loss limit cannot exceed account capital.")
    if not allocations:
        raise ValueError("Add at least one index/robot allocation.")

    for item in allocations:
        if not item.capital.is_finite():
            raise ValueError("Each allocation capital must be a finite number.")
        if not item.index.strip() or not item.robot.strip():
            raise ValueError("Index and robot names cannot be empty.")
        if item.capital <= ZERO:
            raise ValueError("Each allocation must be greater than zero.")

    allocated_capital = sum((item.capital for item in allocations), ZERO)
    if allocated_capital > account_capital:
        raise ValueError("The sum of allocations cannot exceed account capital.")

    rows = tuple(
        AllocationResult(
            allocation=item,
            account_share_pct=item.capital * ONE_HUNDRED / account_capital,
            daily_loss_budget=daily_loss_limit * item.capital / account_capital,
        )
        for item in allocations
    )
    allocated_daily_budget = sum(
        (row.daily_loss_budget for row in rows), ZERO
    )

    return PortfolioResult(
        account_capital=account_capital,
        daily_loss_limit=daily_loss_limit,
        allocated_capital=allocated_capital,
        reserved_capital=account_capital - allocated_capital,
        allocated_daily_budget=allocated_daily_budget,
        reserved_daily_budget=daily_loss_limit - allocated_daily_budget,
        allocations=rows,
    )


def effective_portfolio_risk_cap(
    daily_loss_limit: Decimal,
    remaining_daily_loss_room: Decimal | None = None,
    remaining_total_loss_room: Decimal | None = None,
) -> Decimal:
    """Use the tightest configured daily and prop-account loss constraints."""
    if not daily_loss_limit.is_finite() or daily_loss_limit <= ZERO:
        raise ValueError("Daily loss limit must be a finite positive amount.")
    risk_caps = [daily_loss_limit]
    for label, room in (
        ("Remaining daily-loss room", remaining_daily_loss_room),
        ("Remaining total-loss room", remaining_total_loss_room),
    ):
        if room is None:
            continue
        if not room.is_finite() or room <= ZERO:
            raise ValueError(f"{label} must be a finite positive amount.")
        risk_caps.append(room)
    return min(risk_caps)


def calculate_historical_stress(
    bars: Sequence[DailyBar],
    minimum_bars: int = 20,
) -> HistoricalStress:
    """Find worst daily shocks and peak-to-trough moves over the history."""
    if (
        isinstance(minimum_bars, bool)
        or not isinstance(minimum_bars, int)
        or minimum_bars <= 0
    ):
        raise ValueError("Minimum history length must be a positive integer.")
    if len(bars) < minimum_bars:
        raise ValueError(
            f"At least {minimum_bars} valid daily bars are required; received {len(bars)}."
        )

    long_move = ZERO
    short_move = ZERO
    long_date = ""
    short_date = ""
    previous_close: Decimal | None = None
    previous_date = ""
    peak_price = ZERO
    peak_date = ""
    long_drawdown = ZERO
    long_drawdown_peak_date = ""
    long_drawdown_trough_date = ""
    trough_price: Decimal | None = None
    trough_date = ""
    short_rally = ZERO
    short_rally_trough_date = ""
    short_rally_peak_date = ""

    for bar in bars:
        if not bar.date or (previous_date and bar.date <= previous_date):
            raise ValueError("Historical bars must have unique, ascending dates.")
        if (
            not all(value.is_finite() for value in (bar.high, bar.low, bar.close))
            or min(bar.high, bar.low, bar.close) <= ZERO
            or not bar.low <= bar.close <= bar.high
            or (
                bar.open is not None
                and (
                    not bar.open.is_finite()
                    or not bar.low <= bar.open <= bar.high
                )
            )
        ):
            raise ValueError(f"Historical bar {bar.date} contains invalid prices.")
        if bar.spread_points is not None and (
            not bar.spread_points.is_finite() or bar.spread_points < ZERO
        ):
            raise ValueError(f"Historical bar {bar.date} contains invalid spread.")
        if bar.spread_sample_count is not None and (
            not isinstance(bar.spread_sample_count, int)
            or isinstance(bar.spread_sample_count, bool)
            or bar.spread_sample_count < 0
        ):
            raise ValueError(
                f"Historical bar {bar.date} contains an invalid spread sample count."
            )

        reference = previous_close or bar.close
        daily_range = bar.high - bar.low
        long_adverse = max(daily_range, reference - bar.low, ZERO)
        short_adverse = max(daily_range, bar.high - reference, ZERO)
        long_pct = long_adverse * ONE_HUNDRED / reference
        short_pct = short_adverse * ONE_HUNDRED / reference
        if long_pct > long_move:
            long_move = long_pct
            long_date = bar.date
        if short_pct > short_move:
            short_move = short_pct
            short_date = bar.date

        if bar.high > peak_price:
            peak_price = bar.high
            peak_date = bar.date
        drawdown_pct = (peak_price - bar.low) * ONE_HUNDRED / peak_price
        if drawdown_pct > long_drawdown:
            long_drawdown = drawdown_pct
            long_drawdown_peak_date = peak_date
            long_drawdown_trough_date = bar.date

        if trough_price is None or bar.low < trough_price:
            trough_price = bar.low
            trough_date = bar.date
        rally_pct = (bar.high - trough_price) * ONE_HUNDRED / trough_price
        if rally_pct > short_rally:
            short_rally = rally_pct
            short_rally_trough_date = trough_date
            short_rally_peak_date = bar.date

        previous_close = bar.close
        previous_date = bar.date

    return HistoricalStress(
        long_adverse_pct=long_move,
        long_observed_date=long_date,
        short_adverse_pct=short_move,
        short_observed_date=short_date,
        bar_count=len(bars),
        start_date=bars[0].date,
        end_date=bars[-1].date,
        long_drawdown_pct=long_drawdown,
        long_drawdown_peak_date=long_drawdown_peak_date,
        long_drawdown_trough_date=long_drawdown_trough_date,
        short_rally_pct=short_rally,
        short_rally_trough_date=short_rally_trough_date,
        short_rally_peak_date=short_rally_peak_date,
    )


def calculate_grid_stress(
    initial_lot: Decimal,
    point_value_per_lot: Decimal,
    step_points: Decimal,
    multiplier: Decimal,
    max_trades: int,
    stress_points: Decimal,
    daily_budget: Decimal,
    budget_fraction: Decimal = Decimal("0.8"),
    spread_points: Decimal = ZERO,
    slippage_points: Decimal = ZERO,
    commission_per_lot: Decimal = ZERO,
) -> StressResult:
    """Estimate open-position loss after an adverse move through a grid."""
    numeric_inputs = (
        initial_lot,
        point_value_per_lot,
        step_points,
        multiplier,
        stress_points,
        daily_budget,
        budget_fraction,
    )
    if any(not value.is_finite() for value in numeric_inputs):
        raise ValueError("Grid inputs must be finite numbers.")
    if initial_lot <= ZERO:
        raise ValueError("Initial lot must be greater than zero.")
    if point_value_per_lot <= ZERO:
        raise ValueError("Point value must be greater than zero.")
    if step_points <= ZERO:
        raise ValueError("Step in points must be greater than zero.")
    if multiplier <= ZERO:
        raise ValueError("Multiplier must be greater than zero.")
    if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades <= 0:
        raise ValueError("Maximum trades must be a positive integer.")
    if stress_points < ZERO:
        raise ValueError("Stress move in points must be non-negative.")
    if daily_budget <= ZERO:
        raise ValueError("Daily budget must be greater than zero.")
    if not ZERO < budget_fraction <= ONE:
        raise ValueError("Budget fraction must be greater than 0 and at most 1.")
    if any(
        not value.is_finite() or value < ZERO
        for value in (spread_points, slippage_points, commission_per_lot)
    ):
        raise ValueError("Spread, slippage, and commission must be finite and non-negative.")

    risk_budget = daily_budget * budget_fraction

    estimated_loss = ZERO
    unit_lot_loss = ZERO
    feasible_trades = 0
    budget_exceeded = False
    for trade_index in range(max_trades):
        entry_offset = step_points * trade_index
        if entry_offset > stress_points:
            break
        volume_factor = multiplier ** trade_index
        trade_lot = initial_lot * volume_factor
        loss_per_lot = (
            point_value_per_lot
            * (stress_points - entry_offset + spread_points + slippage_points)
            + commission_per_lot
        )
        estimated_loss += trade_lot * loss_per_lot
        unit_lot_loss += volume_factor * loss_per_lot
        if estimated_loss > risk_budget:
            budget_exceeded = True
        if not budget_exceeded:
            feasible_trades = trade_index + 1
    if not budget_exceeded:
        feasible_trades = max_trades
    recommended_max_lot = risk_budget / unit_lot_loss if unit_lot_loss > ZERO else ZERO

    return StressResult(
        estimated_loss=estimated_loss,
        loss_budget=risk_budget,
        recommended_max_lot=recommended_max_lot,
        max_trades_within_budget=feasible_trades,
    )


def suggest_safe_grid_settings(
    stress_points: Decimal,
    step_points: Decimal,
    point_value_per_lot: Decimal,
    daily_budget: Decimal,
    lot_step: Decimal,
    minimum_lot: Decimal,
    max_trades_limit: int = 20,
    budget_fraction: Decimal = Decimal("0.8"),
    spread_points: Decimal = ZERO,
    slippage_points: Decimal = ZERO,
    commission_per_lot: Decimal = ZERO,
    maximum_lot: Decimal | None = None,
) -> GridSettingsSuggestion:
    """Suggest fixed-lot settings that fit a modeled move and broker volume rules."""
    if any(
        not value.is_finite()
        for value in (
            stress_points,
            step_points,
            point_value_per_lot,
            daily_budget,
            lot_step,
            minimum_lot,
            budget_fraction,
        )
    ):
        raise ValueError("Grid suggestion inputs must be finite numbers.")
    if stress_points <= ZERO or step_points <= ZERO:
        raise ValueError("Stress distance and Step must be greater than zero.")
    if point_value_per_lot <= ZERO or daily_budget <= ZERO:
        raise ValueError("Point value and daily budget must be greater than zero.")
    if lot_step <= ZERO or minimum_lot <= ZERO:
        raise ValueError("Broker lot step and minimum lot must be greater than zero.")
    if maximum_lot is not None and (
        not maximum_lot.is_finite() or maximum_lot < minimum_lot
    ):
        raise ValueError("Broker maximum lot must be finite and at least the minimum lot.")
    if (
        isinstance(max_trades_limit, bool)
        or not isinstance(max_trades_limit, int)
        or max_trades_limit <= 0
    ):
        raise ValueError("Max Trades limit must be a positive integer.")
    if not ZERO < budget_fraction <= ONE:
        raise ValueError("Budget fraction must be greater than 0 and at most 1.")

    entries_in_stress = int(
        (stress_points / step_points).to_integral_value(rounding=ROUND_FLOOR)
    ) + 1
    candidate_trades = min(max_trades_limit, max(1, entries_in_stress))
    risk_budget = daily_budget * budget_fraction

    for max_trades in range(candidate_trades, 0, -1):
        minimum_lot_result = calculate_grid_stress(
            initial_lot=minimum_lot,
            point_value_per_lot=point_value_per_lot,
            step_points=step_points,
            multiplier=ONE,
            max_trades=max_trades,
            stress_points=stress_points,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
        )
        if minimum_lot_result.estimated_loss > risk_budget:
            continue

        unit_lot_result = calculate_grid_stress(
            initial_lot=ONE,
            point_value_per_lot=point_value_per_lot,
            step_points=step_points,
            multiplier=ONE,
            max_trades=max_trades,
            stress_points=stress_points,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
        )
        initial_lot = (
            (unit_lot_result.recommended_max_lot / lot_step)
            .to_integral_value(rounding=ROUND_FLOOR)
            * lot_step
        )
        if maximum_lot is not None:
            initial_lot = min(
                initial_lot,
                (maximum_lot / lot_step).to_integral_value(rounding=ROUND_FLOOR)
                * lot_step,
            )
        if initial_lot < minimum_lot:
            continue

        result = calculate_grid_stress(
            initial_lot=initial_lot,
            point_value_per_lot=point_value_per_lot,
            step_points=step_points,
            multiplier=ONE,
            max_trades=max_trades,
            stress_points=stress_points,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
        )
        if result.estimated_loss <= risk_budget:
            return GridSettingsSuggestion(
                max_trades=max_trades,
                initial_lot=initial_lot,
                estimated_loss=result.estimated_loss,
                loss_budget=risk_budget,
                stress_points=stress_points,
                step_points=step_points,
            )

    minimum_loss = calculate_grid_stress(
        initial_lot=minimum_lot,
        point_value_per_lot=point_value_per_lot,
        step_points=step_points,
        multiplier=ONE,
        max_trades=1,
        stress_points=stress_points,
        daily_budget=daily_budget,
        budget_fraction=budget_fraction,
        spread_points=spread_points,
        slippage_points=slippage_points,
        commission_per_lot=commission_per_lot,
    ).estimated_loss
    raise ValueError(
        "No safe setting fits the broker's minimum lot, even with Max Trades = 1: "
        f"modeled loss {minimum_loss} exceeds the risk allowance {risk_budget}."
    )


def replay_historical_grid(
    bars: Sequence[DailyBar],
    point_size: Decimal,
    point_value_per_lot: Decimal,
    step_value: Decimal,
    step_is_percentage: bool,
    initial_lot: Decimal,
    max_trades: int,
    multiplier: Decimal,
    daily_budget: Decimal,
    budget_fraction: Decimal = Decimal("0.8"),
    spread_points: Decimal = ZERO,
    slippage_points: Decimal = ZERO,
    commission_per_lot: Decimal = ZERO,
    is_long: bool = True,
) -> HistoricalGridStress:
    """Replay each daily bar as an independent adverse shock, not an EA backtest."""
    calculate_historical_stress(bars)
    if any(
        not value.is_finite() or value < ZERO
        for value in (spread_points, slippage_points, commission_per_lot)
    ):
        raise ValueError("Spread, slippage, and commission must be finite and non-negative.")
    if not point_size.is_finite() or point_size <= ZERO:
        raise ValueError("MT5 point size must be a finite positive number.")
    if not step_value.is_finite() or step_value <= ZERO:
        raise ValueError("Step value must be a finite positive number.")

    worst: HistoricalGridStress | None = None
    previous_close: Decimal | None = None
    for bar in bars:
        reference = previous_close or bar.close
        adverse_price_move = max(
            bar.high - bar.low,
            reference - bar.low if is_long else bar.high - reference,
            ZERO,
        )
        if step_is_percentage:
            step_points = reference * step_value / ONE_HUNDRED / point_size
        else:
            step_points = step_value
        if step_points <= ZERO:
            raise ValueError("Converted historical grid step must be positive.")
        stress_points = adverse_price_move / point_size
        stress = calculate_grid_stress(
            initial_lot=initial_lot,
            point_value_per_lot=point_value_per_lot,
            step_points=step_points,
            multiplier=multiplier,
            max_trades=max_trades,
            stress_points=stress_points,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=max(
                spread_points,
                bar.spread_points if bar.spread_points is not None else ZERO,
            ),
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
        )
        candidate = HistoricalGridStress(
            estimated_loss=stress.estimated_loss,
            loss_budget=stress.loss_budget,
            recommended_max_lot=stress.recommended_max_lot,
            worst_date=bar.date,
            stress_points=stress_points,
            step_points=step_points,
        )
        if worst is None or candidate.estimated_loss > worst.estimated_loss:
            worst = candidate
        previous_close = bar.close

    if worst is None or worst.estimated_loss == ZERO:
        raise ValueError(
            "No modeled price or transaction-cost loss was found in the history."
        )
    return worst


def backtest_historical_grid_campaign(
    bars: Sequence[DailyBar],
    initial_equity: Decimal,
    point_size: Decimal,
    point_value_per_lot: Decimal,
    step_points: Decimal,
    take_profit_points: Decimal,
    initial_lot: Decimal,
    max_trades: int,
    multiplier: Decimal = ONE,
    spread_points: Decimal = ZERO,
    slippage_points: Decimal = ZERO,
    commission_per_lot: Decimal = ZERO,
    is_long: bool = True,
) -> HistoricalGridBacktest:
    """Replay one generic grid campaign in date order using adverse-first OHLC paths.

    The campaign opens at the first bar's close, adds fixed-step entries, and
    closes its basket once the weighted-average take-profit is reached. Entries
    are market-on-threshold, reanchored to the last fill; gaps fill at the open.
    Missing opens use the previous close clamped to the bar's range. It does not
    restart because an unknown EA's entry signal cannot be inferred.
    """
    calculate_historical_stress(bars)
    positive_inputs = (
        initial_equity,
        point_size,
        point_value_per_lot,
        step_points,
        take_profit_points,
        initial_lot,
        multiplier,
    )
    if any(not value.is_finite() or value <= ZERO for value in positive_inputs):
        raise ValueError(
            "Backtest prices, equity, lot, and grid settings must be positive "
            "and finite."
        )
    if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades <= 0:
        raise ValueError("Maximum trades must be a positive integer.")
    if any(
        not value.is_finite() or value < ZERO
        for value in (spread_points, slippage_points, commission_per_lot)
    ):
        raise ValueError("Spread, slippage, and commission must be finite and non-negative.")

    positions: list[tuple[Decimal, Decimal]] = []
    balance = initial_equity
    equity_peak = initial_equity
    equity_peak_date = bars[0].date
    max_drawdown = ZERO
    max_drawdown_pct = ZERO
    drawdown_peak_date = bars[0].date
    drawdown_trough_date = bars[0].date
    worst_daily_loss = ZERO
    worst_daily_loss_date = bars[0].date
    max_open_trades = 0
    take_profit_count = 0
    grid_exhausted = False
    day_open_equity = initial_equity

    def spread_for(bar: DailyBar) -> Decimal:
        return max(
            spread_points,
            bar.spread_points if bar.spread_points is not None else ZERO,
        )

    def equity_at(price: Decimal) -> Decimal:
        floating = sum(
            (
                (price - entry if is_long else entry - price)
                / point_size
                * point_value_per_lot
                * lot
                for entry, lot in positions
            ),
            ZERO,
        )
        return balance + floating

    def observe_equity(value: Decimal, bar_date: str) -> None:
        nonlocal equity_peak, equity_peak_date, max_drawdown, max_drawdown_pct
        nonlocal drawdown_peak_date, drawdown_trough_date
        nonlocal worst_daily_loss, worst_daily_loss_date
        if value > equity_peak:
            equity_peak = value
            equity_peak_date = bar_date
        drawdown = equity_peak - value
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            drawdown_peak_date = equity_peak_date
            drawdown_trough_date = bar_date
        max_drawdown_pct = max(
            max_drawdown_pct, drawdown * ONE_HUNDRED / equity_peak
        )
        daily_loss = max(day_open_equity - value, ZERO)
        if daily_loss > worst_daily_loss:
            worst_daily_loss = daily_loss
            worst_daily_loss_date = bar_date

    def open_position(price: Decimal, bar: DailyBar) -> None:
        nonlocal balance, max_open_trades
        observe_equity(equity_at(price), bar.date)
        lot = initial_lot * (multiplier ** len(positions))
        positions.append((price, lot))
        balance -= lot * (
            point_value_per_lot
            * (spread_for(bar) + slippage_points)
            + commission_per_lot
        )
        max_open_trades = max(max_open_trades, len(positions))
        observe_equity(equity_at(price), bar.date)

    def basket_take_profit() -> Decimal:
        total_lots = sum((lot for _, lot in positions), ZERO)
        weighted_entry = sum(
            (entry * lot for entry, lot in positions), ZERO
        ) / total_lots
        distance = take_profit_points * point_size
        return weighted_entry + distance if is_long else weighted_entry - distance

    def close_basket(price: Decimal, bar: DailyBar) -> None:
        nonlocal balance, take_profit_count
        balance = equity_at(price)
        positions.clear()
        take_profit_count += 1
        observe_equity(balance, bar.date)

    first_bar = bars[0]
    open_position(first_bar.close, first_bar)
    previous_close = first_bar.close
    day_open_equity = balance

    for bar in bars[1:]:
        if not positions:
            previous_close = bar.close
            day_open_equity = balance
            continue
        step_price = step_points * point_size
        adverse_price = bar.low if is_long else bar.high
        favorable_price = bar.high if is_long else bar.low
        opening_price = (
            bar.open
            if bar.open is not None
            else min(max(previous_close, bar.low), bar.high)
        )
        observe_equity(equity_at(opening_price), bar.date)
        take_profit_price = basket_take_profit()
        if (
            opening_price >= take_profit_price
            if is_long else opening_price <= take_profit_price
        ):
            close_basket(opening_price, bar)
            day_open_equity = balance
            previous_close = bar.close
            continue

        next_entry = (
            positions[-1][0] - step_price
            if is_long
            else positions[-1][0] + step_price
        )

        while len(positions) < max_trades and (
            adverse_price <= next_entry if is_long else adverse_price >= next_entry
        ):
            fill_price = (
                min(next_entry, opening_price)
                if is_long
                else max(next_entry, opening_price)
            )
            open_position(fill_price, bar)
            next_entry = (
                positions[-1][0] - step_price
                if is_long
                else positions[-1][0] + step_price
            )

        if len(positions) == max_trades and (
            adverse_price <= next_entry if is_long else adverse_price >= next_entry
        ):
            grid_exhausted = True

        observe_equity(equity_at(adverse_price), bar.date)
        take_profit_price = basket_take_profit()
        take_profit_hit = (
            favorable_price >= take_profit_price
            if is_long
            else favorable_price <= take_profit_price
        )
        if take_profit_hit:
            close_basket(take_profit_price, bar)
        else:
            observe_equity(equity_at(favorable_price), bar.date)

        closing_equity = equity_at(bar.close)
        observe_equity(closing_equity, bar.date)
        day_open_equity = closing_equity
        previous_close = bar.close

    if positions:
        last_bar = bars[-1]
        balance += sum(
            (
                (last_bar.close - entry if is_long else entry - last_bar.close)
                / point_size
                * point_value_per_lot
                * lot
                for entry, lot in positions
            ),
            ZERO,
        )
    final_equity = balance
    observe_equity(final_equity, bars[-1].date)
    return HistoricalGridBacktest(
        initial_equity=initial_equity,
        final_equity=final_equity,
        net_profit=final_equity - initial_equity,
        max_drawdown_cash=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        drawdown_peak_date=drawdown_peak_date,
        drawdown_trough_date=drawdown_trough_date,
        worst_daily_loss=worst_daily_loss,
        worst_daily_loss_date=worst_daily_loss_date,
        take_profit_count=take_profit_count,
        max_open_trades=max_open_trades,
        grid_exhausted=grid_exhausted,
        end_date=bars[-1].date,
    )


def suggest_safe_grid_settings_from_history(
    bars: Sequence[DailyBar],
    point_size: Decimal,
    point_value_per_lot: Decimal,
    step_value: Decimal,
    step_is_percentage: bool,
    daily_budget: Decimal,
    lot_step: Decimal,
    minimum_lot: Decimal,
    max_trades_limit: int = 20,
    budget_fraction: Decimal = Decimal("0.8"),
    spread_points: Decimal = ZERO,
    slippage_points: Decimal = ZERO,
    commission_per_lot: Decimal = ZERO,
    is_long: bool = True,
    maximum_lot: Decimal | None = None,
) -> GridSettingsSuggestion:
    """Suggest fixed lots using the worst independent daily OHLC shock in history."""
    calculate_historical_stress(bars)
    if any(
        not value.is_finite()
        for value in (
            point_size,
            point_value_per_lot,
            step_value,
            daily_budget,
            lot_step,
            minimum_lot,
            budget_fraction,
        )
    ):
        raise ValueError("Historical grid inputs must be finite numbers.")
    if point_size <= ZERO:
        raise ValueError("MT5 point size must be a finite positive number.")
    if point_value_per_lot <= ZERO or daily_budget <= ZERO:
        raise ValueError("Point value and daily budget must be positive.")
    if step_value <= ZERO:
        raise ValueError("Step value must be a finite positive number.")
    if lot_step <= ZERO or minimum_lot <= ZERO:
        raise ValueError("Broker lot step and minimum lot must be greater than zero.")
    if maximum_lot is not None and (
        not maximum_lot.is_finite() or maximum_lot < minimum_lot
    ):
        raise ValueError("Broker maximum lot must be finite and at least the minimum lot.")
    if not ZERO < budget_fraction <= ONE:
        raise ValueError("Budget fraction must be greater than 0 and at most 1.")
    if any(
        not value.is_finite() or value < ZERO
        for value in (spread_points, slippage_points, commission_per_lot)
    ):
        raise ValueError("Spread, slippage, and commission must be finite and non-negative.")
    if (
        isinstance(max_trades_limit, bool)
        or not isinstance(max_trades_limit, int)
        or max_trades_limit <= 0
    ):
        raise ValueError("Max Trades limit must be a positive integer.")

    candidate_trades = 0
    previous_close: Decimal | None = None
    for bar in bars:
        reference = previous_close or bar.close
        adverse_points = max(
            bar.high - bar.low,
            reference - bar.low if is_long else bar.high - reference,
            ZERO,
        ) / point_size
        step_points = (
            reference * step_value / ONE_HUNDRED / point_size
            if step_is_percentage
            else step_value
        )
        if step_points > ZERO:
            candidate_trades = max(
                candidate_trades,
                int((adverse_points / step_points).to_integral_value(rounding=ROUND_FLOOR))
                + 1,
            )
        previous_close = bar.close
    candidate_trades = min(max_trades_limit, max(1, candidate_trades))
    risk_budget = daily_budget * budget_fraction

    for max_trades in range(candidate_trades, 0, -1):
        minimum_stress = replay_historical_grid(
            bars=bars,
            point_size=point_size,
            point_value_per_lot=point_value_per_lot,
            step_value=step_value,
            step_is_percentage=step_is_percentage,
            initial_lot=minimum_lot,
            max_trades=max_trades,
            multiplier=ONE,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
            is_long=is_long,
        )
        if minimum_stress.estimated_loss > risk_budget:
            continue
        unit_stress = replay_historical_grid(
            bars=bars,
            point_size=point_size,
            point_value_per_lot=point_value_per_lot,
            step_value=step_value,
            step_is_percentage=step_is_percentage,
            initial_lot=ONE,
            max_trades=max_trades,
            multiplier=ONE,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
            is_long=is_long,
        )
        initial_lot = (
            (unit_stress.recommended_max_lot / lot_step)
            .to_integral_value(rounding=ROUND_FLOOR)
            * lot_step
        )
        if maximum_lot is not None:
            initial_lot = min(
                initial_lot,
                (maximum_lot / lot_step).to_integral_value(rounding=ROUND_FLOOR)
                * lot_step,
            )
        if initial_lot < minimum_lot:
            continue
        selected = replay_historical_grid(
            bars=bars,
            point_size=point_size,
            point_value_per_lot=point_value_per_lot,
            step_value=step_value,
            step_is_percentage=step_is_percentage,
            initial_lot=initial_lot,
            max_trades=max_trades,
            multiplier=ONE,
            daily_budget=daily_budget,
            budget_fraction=budget_fraction,
            spread_points=spread_points,
            slippage_points=slippage_points,
            commission_per_lot=commission_per_lot,
            is_long=is_long,
        )
        if selected.estimated_loss <= risk_budget:
            return GridSettingsSuggestion(
                max_trades=max_trades,
                initial_lot=initial_lot,
                estimated_loss=selected.estimated_loss,
                loss_budget=risk_budget,
                stress_points=selected.stress_points,
                step_points=selected.step_points,
                worst_date=selected.worst_date,
            )

    minimum_stress = replay_historical_grid(
        bars=bars,
        point_size=point_size,
        point_value_per_lot=point_value_per_lot,
        step_value=step_value,
        step_is_percentage=step_is_percentage,
        initial_lot=minimum_lot,
        max_trades=1,
        multiplier=ONE,
        daily_budget=daily_budget,
        budget_fraction=budget_fraction,
        spread_points=spread_points,
        slippage_points=slippage_points,
        commission_per_lot=commission_per_lot,
        is_long=is_long,
    )
    raise ValueError(
        "No safe setting fits the broker's minimum lot, even with Max Trades = 1: "
        f"modeled loss {minimum_stress.estimated_loss} exceeds the risk allowance "
        f"{risk_budget}."
    )


def parse_decimal(prompt: str) -> Decimal:
    while True:
        raw = input(prompt).strip().replace(",", ".")
        try:
            value = Decimal(raw)
            if value.is_finite():
                return value
        except InvalidOperation:
            pass
        print("Enter a valid number, for example 10000 or 4.5.")


def read_positive_integer(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("Enter a whole number greater than zero.")


def money(value: Decimal) -> str:
    return f"{value.quantize(CENT):,.2f}"


def run_stress_check(
    allocation: AllocationResult,
    currency: str,
) -> None:
    print(
        f"\nStress test for {allocation.allocation.index} / "
        f"{allocation.allocation.robot}"
    )
    print(
        "Model: positions open in one direction at each adverse step; "
        "loss is measured at the entered stress move."
    )
    print("  1 - Find candidate settings from the risk budget")
    print("  2 - Check settings I already have")
    while True:
        mode = input("Choose 1 or 2: ").strip()
        if mode in {"1", "2"}:
            break
        print("Choose 1 or 2.")

    point_value = parse_decimal(
        "Cash value of 1 point for 1.00 lot in account currency: "
    )
    print("Step Type:")
    print("  1 - enum_fixed_pips")
    print("  2 - Enum_percentage_pips")
    while True:
        step_type_choice = input("Choose 1 or 2: ").strip()
        if step_type_choice in {"1", "2"}:
            break
        print("Choose 1 or 2.")

    step_value = parse_decimal("Step Value for the EA: ")
    if step_value <= ZERO:
        raise ValueError("Step Value must be greater than zero.")
    if step_type_choice == "1":
        points_per_pip = parse_decimal(
            "How many MT5 points equal 1 EA pip for this symbol? "
        )
        if points_per_pip <= ZERO:
            raise ValueError("Points per EA pip must be greater than zero.")
        step_points = step_value * points_per_pip
        step_type_name = "enum_fixed_pips"
    else:
        reference_price = parse_decimal(
            "Current/reference price (assumes percentage of this price): "
        )
        point_size = parse_decimal(
            "Price size of 1 MT5 point for this symbol: "
        )
        if reference_price <= ZERO or point_size <= ZERO:
            raise ValueError("Reference price and point size must be greater than zero.")
        step_points = reference_price * step_value / Decimal("100") / point_size
        step_type_name = "Enum_percentage_pips"

    stress_points = parse_decimal(
        "Adverse move to test, in points from the first entry: "
    )
    risk_allowance = allocation.daily_loss_budget * Decimal("0.8")

    print("\nIndicative stress-test settings")
    print(
        f"Daily risk budget for this robot: "
        f"{money(allocation.daily_loss_budget)} {currency}"
    )
    print(
        f"Settings allowance (80%): {money(risk_allowance)} {currency}; "
        f"reserved buffer: "
        f"{money(allocation.daily_loss_budget - risk_allowance)} {currency}"
    )

    if mode == "1":
        if stress_points <= ZERO:
            raise ValueError(
                "A positive adverse move is required to find a finite lot ceiling "
                "when execution costs are not modeled."
            )
        candidate_limit = read_positive_integer(
            "How many Max Trades values should I compare? (1-20): "
        )
        if candidate_limit > 20:
            raise ValueError("Compare at most 20 Max Trades values.")

        print(
            f"\n{'Max Trades':>12} {'Risk Type':>14} {'Multiplier':>12} "
            f"{'Max initial lot':>18}"
        )
        print("-" * 60)
        for max_trades in range(1, candidate_limit + 1):
            candidate = calculate_grid_stress(
                initial_lot=ONE,
                point_value_per_lot=point_value,
                step_points=step_points,
                multiplier=ONE,
                max_trades=max_trades,
                stress_points=stress_points,
                daily_budget=allocation.daily_loss_budget,
            )
            print(
                f"{max_trades:>12} {'Fixed lots':>14} {ONE:>12} "
                f"{candidate.recommended_max_lot:>18f}"
            )

        selected_trades = read_positive_integer(
            f"Choose Max Trades from 1 to {candidate_limit}: "
        )
        if selected_trades > candidate_limit:
            raise ValueError("Selected Max Trades was not in the comparison table.")
        selected = calculate_grid_stress(
            initial_lot=ONE,
            point_value_per_lot=point_value,
            step_points=step_points,
            multiplier=ONE,
            max_trades=selected_trades,
            stress_points=stress_points,
            daily_budget=allocation.daily_loss_budget,
        )
        print("\nAdditional settings for the EA")
        magic_number = read_positive_integer(
            "Enter a Magic Number unique to this EA/chart: "
        )
        if magic_number > 2147483647:
            raise ValueError("Magic Number must not exceed 2147483647.")

        print("Take Profit Type:")
        print("  1 - enum_fixed_pips")
        print("  2 - Enum_percentage_pips")
        while True:
            take_profit_choice = input("Choose 1 or 2: ").strip()
            if take_profit_choice in {"1", "2"}:
                break
            print("Choose 1 or 2.")
        take_profit_value = parse_decimal("Take Profit Value for the EA: ")
        if take_profit_value <= ZERO:
            raise ValueError("Take Profit Value must be greater than zero.")
        take_profit_type = (
            "enum_fixed_pips"
            if take_profit_choice == "1"
            else "Enum_percentage_pips"
        )

        robot_name = allocation.allocation.robot.lower()
        if "dca" in robot_name:
            robot_type = "DCA"
        elif "rsi" in robot_name:
            robot_type = "RSI"
        else:
            print("Robot type:")
            print("  1 - DCA")
            print("  2 - RSI")
            while True:
                robot_choice = input("Choose 1 or 2: ").strip()
                if robot_choice in {"1", "2"}:
                    robot_type = "DCA" if robot_choice == "1" else "RSI"
                    break
                print("Choose 1 or 2.")

        print(
            "\nSuggested EA configuration for the selected stress scenario"
        )
        print(f"Robot: {robot_type}")
        print(f"Magic Number: {magic_number}")
        print(f"Max Trades: {selected_trades}")
        print(f"Step Type: {step_type_name}")
        print(f"Step Value: {step_value}")
        print(f"Take Profit Type: {take_profit_type}")
        print(f"Take Profit Value: {take_profit_value}")
        print("Risk Type: Fixed lots")
        print(
            f"Risk: <= {selected.recommended_max_lot:f} "
            "(round down to broker volume step)"
        )
        print("Multiplier Factor: 1.0")
        if robot_type == "DCA":
            print("Entry on price break: false")
            print("InpPriceBreakType: break Below (ignored while false)")
            print("Reference Price: 0 (ignored while price break is false)")
            print("Trade on new candle: true")
            print("Show Invested Money: true")
        else:
            print("Close When Overbought: true")
            print("RSI oversold: 30 (backtest starting value)")
            print("RSI Overbought: 70 (backtest starting value)")
            print("RSI Period: 14 (backtest starting value)")
            print("Show Invested Money: true")

        ceiling_stress = calculate_grid_stress(
            initial_lot=selected.recommended_max_lot,
            point_value_per_lot=point_value,
            step_points=step_points,
            multiplier=ONE,
            max_trades=selected_trades,
            stress_points=stress_points,
            daily_budget=allocation.daily_loss_budget,
        )
        print(
            f"\nModeled loss at the lot ceiling (before broker rounding): "
            f"{money(ceiling_stress.estimated_loss)} {currency} at "
            f"{stress_points} points adverse."
        )
    else:
        initial_lot = parse_decimal("Initial lot size: ")
        multiplier = parse_decimal("Multiplier factor: ")
        max_trades = read_positive_integer("Configured Max Trades: ")
        result = calculate_grid_stress(
            initial_lot=initial_lot,
            point_value_per_lot=point_value,
            step_points=step_points,
            multiplier=multiplier,
            max_trades=max_trades,
            stress_points=stress_points,
            daily_budget=allocation.daily_loss_budget,
        )
        print(
            f"Estimated open loss at {stress_points} points: "
            f"{money(result.estimated_loss)} {currency}"
        )
        if result.estimated_loss == ZERO:
            print(
                "Initial lot ceiling: not determined by this zero-loss scenario. "
                "Use a positive adverse move; execution costs are not modeled."
            )
        else:
            print(
                f"Initial lot ceiling for these settings: "
                f"{result.recommended_max_lot:f} (round down to broker volume step)"
            )
        print(
            f"Maximum trades within the 80% allowance at this lot: "
            f"{result.max_trades_within_budget} of {max_trades}"
        )
        if result.estimated_loss > result.loss_budget:
            print(
                "Warning: these settings exceed the modeled allowance. "
                "Reduce the initial lot, multiplier, or Max Trades, then "
                "recalculate."
            )
        else:
            print(
                "These settings fit this modeled move only; they are not "
                "guaranteed safe beyond that move."
            )

    print(
        "The estimate excludes commission, spread, swaps, slippage and gaps. "
        "After all allowed entries are open, additional adverse movement can "
        "increase the loss without a limit. RSI signals do not guarantee the "
        "modeled spacing or direction."
    )
    print(
        "Conservative starting guidance: use Multiplier Factor 1.0 (no "
        "martingale) where the EA permits it, and do not treat the EA's "
        "Risk/Cash input as a daily stop unless its documentation explicitly "
        "confirms that."
    )
    print(
        "Take Profit and RSI entry levels do not cap the modeled loss; use a "
        "separate daily equity stop in the EA or account manager."
    )
    print(
        "Step and Take Profit values are copied from your input; the drawdown "
        "budget alone cannot determine profitable signal settings."
    )
    if "rsi" in allocation.allocation.robot.lower():
        print(
            "RSI-only backtest starting reference (not a safety guarantee): "
            "Period 14, Oversold 30, Overbought 70. These signal settings do "
            "not cap losses."
        )


def run_cli() -> None:
    print("MT5 portfolio risk budget calculator")
    account_capital = parse_decimal("Total account capital: ")
    currency = input("Account currency (e.g. USD): ").strip() or "account currency"

    while True:
        print("Daily loss limit input:")
        print("  1 - percentage of total account capital")
        print("  2 - cash amount")
        mode = input("Choose 1 or 2: ").strip()
        if mode in {"1", "2"}:
            break
        print("Choose 1 or 2.")

    if mode == "1":
        daily_pct = parse_decimal("Maximum daily drawdown percentage: ")
        if not ZERO < daily_pct <= ONE_HUNDRED:
            raise ValueError("Daily drawdown percentage must be above 0 and at most 100.")
        daily_loss_limit = account_capital * daily_pct / ONE_HUNDRED
    else:
        daily_loss_limit = parse_decimal("Maximum daily loss in cash: ")

    count = read_positive_integer("Number of index/robot allocations: ")
    allocations = []
    for number in range(1, count + 1):
        print(f"\nAllocation {number}")
        index = input("  Index/symbol (e.g. US100): ").strip()
        robot = input("  Robot name (e.g. DCA or RSI): ").strip()
        capital = parse_decimal("  Capital assigned to this robot: ")
        allocations.append(Allocation(index=index, robot=robot, capital=capital))

    result = calculate_portfolio(account_capital, daily_loss_limit, allocations)
    print("\nPortfolio risk budgets")
    print(f"Total account:              {money(result.account_capital)} {currency}")
    print(f"Daily account loss limit:   {money(result.daily_loss_limit)} {currency}")
    print(f"Capital allocated:          {money(result.allocated_capital)} {currency}")
    print(f"Capital kept in reserve:    {money(result.reserved_capital)} {currency}")
    print()
    print(f"{'Index':<16} {'Robot':<16} {'Capital':>14} {'Account %':>12} {'Daily cap':>14}")
    print("-" * 76)
    for row in result.allocations:
        item = row.allocation
        print(
            f"{item.index:<16.16} {item.robot:<16.16} "
            f"{money(item.capital):>14} "
            f"{row.account_share_pct.quantize(CENT):>11}% "
            f"{money(row.daily_loss_budget):>14}"
        )
    print("-" * 76)
    print(
        f"Unassigned daily limit reserve: "
        f"{money(result.reserved_daily_budget)} {currency}"
    )
    print(
        "\nThese are cash budgets, not guaranteed maximum losses. "
        "Gaps/slippage can exceed a limit; a robot needs its own equity "
        "monitor and entry/close rules to enforce it."
    )

    if input("\nFind or check settings for one allocation? (y/n): ").strip().lower() in {
        "y",
        "yes",
        "da",
    }:
        for number, row in enumerate(result.allocations, start=1):
            print(
                f"  {number} - {row.allocation.index} / "
                f"{row.allocation.robot}"
            )
        allocation_number = read_positive_integer("Choose allocation number: ")
        if allocation_number > len(result.allocations):
            raise ValueError("Allocation number does not exist.")
        run_stress_check(result.allocations[allocation_number - 1], currency)


if __name__ == "__main__":
    try:
        run_cli()
    except (ValueError, KeyboardInterrupt) as error:
        if isinstance(error, KeyboardInterrupt):
            print("\nCancelled.")
        else:
            print(f"\nInput error: {error}")
    finally:
        if sys.stdin.isatty():
            input("\nApasă Enter pentru a închide fereastra...")
