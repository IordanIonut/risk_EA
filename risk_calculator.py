"""Portfolio risk calculations and a terminal fallback.

For the desktop interface, open risk_calculator_app.pyw.
Terminal fallback: python risk_calculator.py

This calculates cash risk budgets only. It does not convert a budget into lots;
that requires symbol-specific tick value, contract size, and stop/stress distance.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
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


@dataclass(frozen=True)
class HistoricalStress:
    long_adverse_pct: Decimal
    long_observed_date: str
    short_adverse_pct: Decimal
    short_observed_date: str
    bar_count: int
    start_date: str
    end_date: str


@dataclass(frozen=True)
class GridSettingsSuggestion:
    max_trades: int
    initial_lot: Decimal
    estimated_loss: Decimal
    loss_budget: Decimal
    stress_points: Decimal
    step_points: Decimal


def calculate_portfolio(
    account_capital: Decimal,
    daily_loss_limit: Decimal,
    allocations: Sequence[Allocation],
) -> PortfolioResult:
    """Distribute the account's daily cash limit in proportion to allocated capital."""
    if account_capital <= ZERO:
        raise ValueError("Account capital must be greater than zero.")
    if daily_loss_limit <= ZERO:
        raise ValueError("Daily loss limit must be greater than zero.")
    if daily_loss_limit > account_capital:
        raise ValueError("Daily loss limit cannot exceed account capital.")
    if not allocations:
        raise ValueError("Add at least one index/robot allocation.")

    for item in allocations:
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
    """Find the worst daily adverse range from each prior close over the history."""
    if len(bars) < minimum_bars:
        raise ValueError(
            f"At least {minimum_bars} valid daily bars are required; received {len(bars)}."
        )
    if minimum_bars <= 0:
        raise ValueError("Minimum history length must be greater than zero.")

    long_move = ZERO
    short_move = ZERO
    long_date = ""
    short_date = ""
    previous_close: Decimal | None = None
    previous_date = ""

    for bar in bars:
        if not bar.date or (previous_date and bar.date <= previous_date):
            raise ValueError("Historical bars must have unique, ascending dates.")
        if (
            not all(value.is_finite() for value in (bar.high, bar.low, bar.close))
            or min(bar.high, bar.low, bar.close) <= ZERO
            or bar.high < bar.low
        ):
            raise ValueError(f"Historical bar {bar.date} contains invalid prices.")

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
) -> StressResult:
    """Estimate open-position loss after an adverse move through a grid."""
    if initial_lot <= ZERO:
        raise ValueError("Initial lot must be greater than zero.")
    if point_value_per_lot <= ZERO:
        raise ValueError("Point value must be greater than zero.")
    if step_points <= ZERO:
        raise ValueError("Step in points must be greater than zero.")
    if multiplier <= ZERO:
        raise ValueError("Multiplier must be greater than zero.")
    if max_trades <= 0:
        raise ValueError("Maximum trades must be greater than zero.")
    if stress_points <= ZERO:
        raise ValueError("Stress move in points must be greater than zero.")
    if daily_budget <= ZERO:
        raise ValueError("Daily budget must be greater than zero.")
    if not ZERO < budget_fraction <= ONE:
        raise ValueError("Budget fraction must be greater than 0 and at most 1.")

    risk_budget = daily_budget * budget_fraction

    def loss_for(trade_count: int, lot: Decimal) -> Decimal:
        loss = ZERO
        for trade_index in range(trade_count):
            entry_offset = step_points * trade_index
            if entry_offset >= stress_points:
                break
            trade_lot = lot * (multiplier ** trade_index)
            loss += trade_lot * point_value_per_lot * (stress_points - entry_offset)
        return loss

    estimated_loss = loss_for(max_trades, initial_lot)
    unit_lot_loss = loss_for(max_trades, Decimal("1"))
    recommended_max_lot = risk_budget / unit_lot_loss if unit_lot_loss > ZERO else ZERO

    feasible_trades = 0
    for trade_count in range(1, max_trades + 1):
        if loss_for(trade_count, initial_lot) > risk_budget:
            break
        feasible_trades = trade_count

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
) -> GridSettingsSuggestion:
    """Suggest fixed-lot settings that fit a modeled move and broker volume rules."""
    if stress_points <= ZERO or step_points <= ZERO:
        raise ValueError("Stress distance and Step must be greater than zero.")
    if point_value_per_lot <= ZERO or daily_budget <= ZERO:
        raise ValueError("Point value and daily budget must be greater than zero.")
    if lot_step <= ZERO or minimum_lot <= ZERO:
        raise ValueError("Broker lot step and minimum lot must be greater than zero.")
    if max_trades_limit <= 0:
        raise ValueError("Max Trades limit must be greater than zero.")
    if not ZERO < budget_fraction <= ONE:
        raise ValueError("Budget fraction must be greater than 0 and at most 1.")

    entries_in_stress = int(
        (stress_points / step_points).to_integral_value(rounding=ROUND_CEILING)
    )
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
        )
        initial_lot = (
            (unit_lot_result.recommended_max_lot / lot_step)
            .to_integral_value(rounding=ROUND_FLOOR)
            * lot_step
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
    ).estimated_loss
    raise ValueError(
        "No safe setting fits the broker's minimum lot, even with Max Trades = 1: "
        f"modeled loss {minimum_loss} exceeds the risk allowance {risk_budget}."
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
    if step_type_choice == "1":
        points_per_pip = parse_decimal(
            "How many MT5 points equal 1 EA pip for this symbol? "
        )
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
                f"{candidate.recommended_max_lot:>18.4f}"
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
            f"Risk: <= {selected.recommended_max_lot:.4f} "
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

        print(
            f"\nEstimated modeled loss for this setting: "
            f"{money(selected.estimated_loss)} {currency} at "
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
        print(
            f"Initial lot ceiling for these settings: "
            f"{result.recommended_max_lot:.4f}"
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
