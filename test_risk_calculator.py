import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
import io
from unittest.mock import patch

from risk_calculator import (
    Allocation,
    DailyBar,
    backtest_historical_grid_campaign,
    calculate_historical_stress,
    calculate_grid_stress,
    calculate_portfolio,
    effective_portfolio_risk_cap,
    replay_historical_grid,
    run_stress_check,
    suggest_safe_grid_settings,
    suggest_safe_grid_settings_from_history,
)


class TerminalStressReportTests(unittest.TestCase):
    def _run_answers(self, answers: list[str], output: io.StringIO) -> None:
        allocation = calculate_portfolio(
            Decimal("100"), Decimal("1"),
            [Allocation("US500", "DCA", Decimal("100"))],
        ).allocations[0]
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            run_stress_check(allocation, "USD")

    def test_negative_step_and_negative_pip_conversion_cannot_cancel_out(self) -> None:
        for mode in ("1", "2"):
            with self.subTest(mode=mode):
                output = io.StringIO()
                answers = [mode, "1", "1", "-10", "-1", "3"]
                answers += ["1", "1", "10001", "1", "10"] if mode == "1" else ["0.1", "1", "1"]
                with self.assertRaisesRegex(ValueError, "Step Value"):
                    self._run_answers(answers, output)
                self.assertNotIn("Suggested EA configuration", output.getvalue())

    def test_nonpositive_step_is_rejected_for_both_step_types(self) -> None:
        for step_type in ("1", "2"):
            for step in ("0", "-1"):
                with self.subTest(step_type=step_type, step=step):
                    with self.assertRaisesRegex(ValueError, "Step Value"):
                        self._run_answers(["1", "1", step_type, step], io.StringIO())

    def test_nonpositive_points_per_pip_is_rejected_before_conversion(self) -> None:
        for conversion in ("0", "-1"):
            with self.subTest(conversion=conversion):
                with self.assertRaisesRegex(ValueError, "Points per EA pip"):
                    self._run_answers(["1", "1", "1", "10", conversion], io.StringIO())

    def test_nonpositive_take_profit_is_not_printed_as_a_recommendation(self) -> None:
        for tp_type in ("1", "2"):
            for tp in ("0", "-10"):
                with self.subTest(tp_type=tp_type, tp=tp):
                    output = io.StringIO()
                    answers = ["1", "1", "1", "10", "1", "3",
                               "1", "1", "10001", tp_type, tp]
                    with self.assertRaisesRegex(ValueError, "Take Profit Value"):
                        self._run_answers(answers, output)
                    self.assertNotIn("Suggested EA configuration", output.getvalue())

    def test_valid_percentage_step_and_take_profit_are_preserved(self) -> None:
        output = io.StringIO()
        self._run_answers(
            ["1", "1", "2", "0.5", "100", "0.01", "3",
             "1", "1", "10001", "2", "0.25"],
            output,
        )
        text = output.getvalue()
        self.assertIn("Step Type: Enum_percentage_pips", text)
        self.assertIn("Step Value: 0.5", text)
        self.assertIn("Take Profit Type: Enum_percentage_pips", text)
        self.assertIn("Take Profit Value: 0.25", text)

    def _report(self, mode: str, stress: str = "3") -> str:
        allocation = calculate_portfolio(
            Decimal("100"), Decimal("1"),
            [Allocation("US500", "DCA", Decimal("100"))],
        ).allocations[0]
        answers = [mode, "1", "1", "10", "1", stress]
        if mode == "1":
            answers += ["1", "1", "10001", "1", "10"]
        else:
            answers += ["0.1", "1", "1"]
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            run_stress_check(allocation, "USD")
        return output.getvalue()

    def test_candidate_and_selected_ceilings_do_not_round_up(self) -> None:
        output = self._report("1")
        ceiling = Decimal("0.8") / Decimal("3")
        self.assertIn(format(ceiling, "f"), output)
        line = next(line for line in output.splitlines() if line.startswith("Risk:"))
        displayed = Decimal(line.split()[2])
        self.assertLessEqual(displayed, ceiling)
        self.assertNotIn("0.2667", output)

    def test_selected_report_uses_ceiling_lot_not_one_lot_loss(self) -> None:
        output = self._report("1")
        self.assertIn("Modeled loss at the lot ceiling", output)
        self.assertIn("0.80 USD at 3 points adverse", output)
        self.assertNotIn("3.00 USD at 3 points adverse", output)

    def test_existing_settings_report_preserves_exact_ceiling(self) -> None:
        output = self._report("2")
        self.assertIn(
            "Initial lot ceiling for these settings: "
            + format(Decimal("0.8") / Decimal("3"), "f"),
            output,
        )
        self.assertIn("Estimated open loss at 3 points: 0.30 USD", output)

    def test_tiny_nonzero_ceiling_is_not_displayed_as_zero(self) -> None:
        output = self._report("2", stress="100000")
        self.assertIn("Initial lot ceiling for these settings: 0.000008", output)

    def test_candidate_mode_rejects_zero_stress_without_execution_costs(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive adverse move"):
            self._report("1", stress="0")

    def test_zero_loss_check_does_not_claim_a_zero_lot_ceiling(self) -> None:
        output = self._report("2", stress="0")
        self.assertIn("not determined by this zero-loss scenario", output)
        self.assertNotIn("Initial lot ceiling for these settings: 0", output)


class PortfolioInputValidationTests(unittest.TestCase):
    def test_nonfinite_account_or_limit_is_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            for field in ("account", "limit"):
                with self.subTest(value=value, field=field):
                    with self.assertRaisesRegex(ValueError, "finite"):
                        calculate_portfolio(
                            Decimal(value) if field == "account" else Decimal("100"),
                            Decimal(value) if field == "limit" else Decimal("10"),
                            [Allocation("US500", "DCA", Decimal("50"))],
                        )

    def test_nonfinite_allocation_is_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    calculate_portfolio(
                        Decimal("100"), Decimal("10"),
                        [Allocation("US500", "DCA", Decimal(value))],
                    )

    def test_valid_portfolio_keeps_proportional_budgets_and_reserve(self) -> None:
        result = calculate_portfolio(
            Decimal("1000"), Decimal("90"),
            [Allocation("US500", "DCA", Decimal("250")),
             Allocation("US100", "RSI", Decimal("500"))],
        )
        self.assertEqual(result.allocations[0].daily_loss_budget, Decimal("30"))
        self.assertEqual(result.allocations[1].daily_loss_budget, Decimal("60"))
        self.assertEqual(result.allocated_daily_budget, Decimal("90"))
        self.assertEqual(result.reserved_daily_budget, Decimal("0"))
        self.assertEqual(result.reserved_capital, Decimal("250"))


class HistoricalStressTests(unittest.TestCase):
    def test_minimum_history_length_must_be_a_positive_integer(self) -> None:
        bars = [
            DailyBar("2026-01-01", Decimal("101"), Decimal("99"), Decimal("100"))
        ]
        for count in (True, False, 1.5, 0, -1):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    calculate_historical_stress(bars, minimum_bars=count)

    def test_finds_largest_adverse_daily_ranges_in_both_directions(self) -> None:
        start = date(2026, 1, 1)
        bars = [
            DailyBar(
                date=(start + timedelta(days=index)).isoformat(),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            )
            for index in range(20)
        ]
        bars[9] = DailyBar(
            date=bars[9].date,
            high=Decimal("102"),
            low=Decimal("80"),
            close=Decimal("90"),
        )
        bars[11] = DailyBar(
            date=bars[11].date,
            high=Decimal("130"),
            low=Decimal("128"),
            close=Decimal("129"),
        )

        result = calculate_historical_stress(bars)

        self.assertEqual(result.long_adverse_pct, Decimal("3000") / Decimal("129"))
        self.assertEqual(result.long_observed_date, bars[12].date)
        self.assertEqual(result.short_adverse_pct, Decimal("30"))
        self.assertEqual(result.short_observed_date, bars[11].date)
        self.assertEqual(result.bar_count, 20)

    def test_finds_peak_to_trough_drawdown_across_multiple_sessions(self) -> None:
        start = date(2026, 1, 1)
        bars = [
            DailyBar(
                date=(start + timedelta(days=index)).isoformat(),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
            )
            for index in range(20)
        ]
        bars[5] = DailyBar(
            bars[5].date, Decimal("120"), Decimal("118"), Decimal("119")
        )
        bars[6] = DailyBar(
            bars[6].date, Decimal("119"), Decimal("90"), Decimal("95")
        )

        result = calculate_historical_stress(bars)

        self.assertEqual(result.long_drawdown_pct, Decimal("25"))
        self.assertEqual(result.long_drawdown_peak_date, bars[5].date)
        self.assertEqual(result.long_drawdown_trough_date, bars[6].date)

    def test_requires_enough_valid_daily_bars(self) -> None:
        bars = [
            DailyBar("2026-01-01", Decimal("101"), Decimal("99"), Decimal("100"))
        ]

        with self.assertRaisesRegex(ValueError, "At least 20"):
            calculate_historical_stress(bars)

    def test_rejects_unsorted_history(self) -> None:
        bars = [
            DailyBar("2026-01-02", Decimal("101"), Decimal("99"), Decimal("100")),
            DailyBar("2026-01-01", Decimal("101"), Decimal("99"), Decimal("100")),
        ] * 10

        with self.assertRaisesRegex(ValueError, "ascending dates"):
            calculate_historical_stress(bars)

    def test_rejects_non_integer_or_negative_spread_sample_count(self) -> None:
        for sample_count in (-1, 1.5, True):
            bars = [
                DailyBar(
                    (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                    Decimal("101"),
                    Decimal("99"),
                    Decimal("100"),
                    spread_sample_count=sample_count,
                )
                for index in range(20)
            ]
            with self.subTest(sample_count=sample_count):
                with self.assertRaisesRegex(ValueError, "invalid spread sample count"):
                    calculate_historical_stress(bars)

    def test_rejects_close_or_open_outside_bar_range(self) -> None:
        for close, opening in (("102", None), ("98", None), ("100", "102"),
                               ("100", "98"), ("100", "NaN")):
            with self.subTest(close=close, opening=opening):
                bars = [
                    DailyBar(
                        (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                        Decimal("101"), Decimal("99"), Decimal(close),
                        open=Decimal(opening) if opening is not None else None,
                    )
                    for index in range(20)
                ]
                with self.assertRaisesRegex(ValueError, "invalid prices"):
                    calculate_historical_stress(bars)


class SafeGridSuggestionTests(unittest.TestCase):
    def test_maximum_trades_requires_a_positive_integer(self) -> None:
        for count in (True, False, 1.5, 0, -1):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    calculate_grid_stress(
                        initial_lot=Decimal("1"), point_value_per_lot=Decimal("1"),
                        step_points=Decimal("10"), multiplier=Decimal("1"),
                        max_trades=count, stress_points=Decimal("20"),
                        daily_budget=Decimal("100"),
                    )

    def test_candidate_limit_requires_a_positive_integer(self) -> None:
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"), Decimal("99"), Decimal("100"),
            ) for index in range(20)
        ]
        for count in (True, False, 1.5, 0, -1):
            for historical in (False, True):
                with self.subTest(count=count, historical=historical):
                    common = dict(
                        point_value_per_lot=Decimal("1"), daily_budget=Decimal("100"),
                        lot_step=Decimal("0.01"), minimum_lot=Decimal("0.01"),
                        max_trades_limit=count,
                    )
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        if historical:
                            suggest_safe_grid_settings_from_history(
                                bars=bars, point_size=Decimal("1"),
                                step_value=Decimal("10"), step_is_percentage=False,
                                **common,
                            )
                        else:
                            suggest_safe_grid_settings(
                                stress_points=Decimal("20"), step_points=Decimal("10"),
                                **common,
                            )

    def test_historical_replays_require_integer_trade_counts(self) -> None:
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("101"), Decimal("99"), Decimal("100"),
            ) for index in range(20)
        ]
        for count in (True, False, 1.5, 0, -1):
            for campaign in (False, True):
                with self.subTest(count=count, campaign=campaign):
                    common = dict(
                        bars=bars, point_size=Decimal("1"),
                        point_value_per_lot=Decimal("1"),
                        initial_lot=Decimal("1"), max_trades=count,
                    )
                    with self.assertRaisesRegex(ValueError, "positive integer"):
                        if campaign:
                            backtest_historical_grid_campaign(
                                initial_equity=Decimal("1000"),
                                step_points=Decimal("10"),
                                take_profit_points=Decimal("5"), **common,
                            )
                        else:
                            replay_historical_grid(
                                step_value=Decimal("10"), step_is_percentage=False,
                                multiplier=Decimal("1"), daily_budget=Decimal("100"),
                                **common,
                            )

    def test_endpoint_entry_costs_can_reduce_the_suggested_trade_count(self) -> None:
        result = suggest_safe_grid_settings(
            stress_points=Decimal("10"),
            step_points=Decimal("10"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("16"),
            lot_step=Decimal("1"),
            minimum_lot=Decimal("1"),
            max_trades_limit=2,
            spread_points=Decimal("2"),
        )
        self.assertEqual(result.max_trades, 1)
        self.assertEqual(result.initial_lot, Decimal("1"))
        self.assertEqual(result.estimated_loss, Decimal("12"))
        self.assertLessEqual(result.estimated_loss, result.loss_budget)

    def test_peak_to_trough_shock_sizes_lot_against_the_full_pullback(self) -> None:
        drawdown_suggestion = suggest_safe_grid_settings(
            stress_points=Decimal("2500"),
            step_points=Decimal("500"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
        )
        daily_shock_suggestion = suggest_safe_grid_settings(
            stress_points=Decimal("100"),
            step_points=Decimal("500"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
        )

        self.assertLess(
            drawdown_suggestion.initial_lot,
            daily_shock_suggestion.initial_lot,
        )
        self.assertLessEqual(
            drawdown_suggestion.estimated_loss,
            drawdown_suggestion.loss_budget,
        )

    def test_rounds_lot_down_to_volume_step_and_fits_allowance(self) -> None:
        result = suggest_safe_grid_settings(
            stress_points=Decimal("1000"),
            step_points=Decimal("100"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
        )

        self.assertEqual(result.max_trades, 11)
        self.assertEqual(result.initial_lot, Decimal("0.01"))
        self.assertLessEqual(result.estimated_loss, result.loss_budget)

    def test_caps_suggested_lot_at_broker_order_volume_max(self) -> None:
        result = suggest_safe_grid_settings(
            stress_points=Decimal("100"),
            step_points=Decimal("10"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("10000"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
            maximum_lot=Decimal("0.035"),
        )

        self.assertEqual(result.initial_lot, Decimal("0.03"))
        self.assertLessEqual(result.initial_lot, Decimal("0.035"))

    def test_reduces_max_trades_when_minimum_lot_would_exceed_allowance(self) -> None:
        result = suggest_safe_grid_settings(
            stress_points=Decimal("1000"),
            step_points=Decimal("100"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.02"),
        )

        self.assertEqual(result.max_trades, 5)
        self.assertEqual(result.initial_lot, Decimal("0.02"))
        self.assertEqual(result.estimated_loss, Decimal("80.00"))

    def test_reports_when_even_one_minimum_lot_is_too_risky(self) -> None:
        with self.assertRaisesRegex(ValueError, "No safe setting"):
            suggest_safe_grid_settings(
                stress_points=Decimal("1000"),
                step_points=Decimal("100"),
                point_value_per_lot=Decimal("1"),
                daily_budget=Decimal("100"),
                lot_step=Decimal("0.01"),
                minimum_lot=Decimal("0.1"),
            )


class GridStressAccumulationTests(unittest.TestCase):
    def test_zero_loss_keeps_existing_undetermined_ceiling_semantics(self) -> None:
        result = calculate_grid_stress(
            initial_lot=Decimal("1"), point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"), multiplier=Decimal("2"),
            max_trades=100, stress_points=Decimal("0"),
            daily_budget=Decimal("100"),
        )
        self.assertEqual(result.estimated_loss, Decimal("0"))
        self.assertEqual(result.recommended_max_lot, Decimal("0"))
        self.assertEqual(result.max_trades_within_budget, 100)

    def test_matches_independent_prefix_calculations(self) -> None:
        for multiplier in ("0.5", "1", "1.7"):
            for stress in ("0", "10", "25", "100"):
                for budget in ("0.01", "3", "1000"):
                    with self.subTest(multiplier=multiplier, stress=stress, budget=budget):
                        inputs = dict(
                            initial_lot=Decimal("0.13"),
                            point_value_per_lot=Decimal("1.23"),
                            step_points=Decimal("10"),
                            multiplier=Decimal(multiplier), max_trades=8,
                            stress_points=Decimal(stress), daily_budget=Decimal(budget),
                            spread_points=Decimal("2"), slippage_points=Decimal("0.7"),
                            commission_per_lot=Decimal("0.5"),
                        )
                        def loss(count: int, lot: Decimal) -> Decimal:
                            total = Decimal("0")
                            for index in range(count):
                                offset = inputs["step_points"] * index
                                if offset > inputs["stress_points"]:
                                    break
                                volume = lot * inputs["multiplier"] ** index
                                total += volume * (
                                    inputs["point_value_per_lot"] * (
                                        inputs["stress_points"] - offset
                                        + inputs["spread_points"] + inputs["slippage_points"]
                                    ) + inputs["commission_per_lot"]
                                )
                            return total
                        result = calculate_grid_stress(**inputs)
                        allowance = Decimal(budget) * Decimal("0.8")
                        feasible = 0
                        for count in range(1, 9):
                            if loss(count, inputs["initial_lot"]) > allowance:
                                break
                            feasible = count
                        self.assertEqual(result.estimated_loss, loss(8, inputs["initial_lot"]))
                        self.assertEqual(result.recommended_max_lot, allowance / loss(8, Decimal("1")))
                        self.assertEqual(result.max_trades_within_budget, feasible)

    def test_unused_entry_capacity_does_not_increase_loss(self) -> None:
        result = calculate_grid_stress(
            initial_lot=Decimal("1"), point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"), multiplier=Decimal("1"),
            max_trades=1_000_000, stress_points=Decimal("1"),
            daily_budget=Decimal("100"),
        )
        self.assertEqual(result.estimated_loss, Decimal("1"))
        self.assertEqual(result.max_trades_within_budget, 1_000_000)

    def test_exact_allowance_and_next_entry_cost(self) -> None:
        result = calculate_grid_stress(
            initial_lot=Decimal("1"), point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"), multiplier=Decimal("1"),
            max_trades=100, stress_points=Decimal("10"),
            daily_budget=Decimal("15"), spread_points=Decimal("2"),
        )
        self.assertEqual(result.loss_budget, Decimal("12"))
        self.assertEqual(result.estimated_loss, Decimal("14"))
        self.assertEqual(result.max_trades_within_budget, 1)


class TransactionCostTests(unittest.TestCase):
    def test_charges_entry_costs_when_stress_exactly_reaches_next_level(self) -> None:
        result = calculate_grid_stress(
            initial_lot=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"),
            multiplier=Decimal("1"),
            max_trades=2,
            stress_points=Decimal("10"),
            daily_budget=Decimal("100"),
            spread_points=Decimal("2"),
        )
        self.assertEqual(result.estimated_loss, Decimal("14"))

    def test_spread_slippage_and_commission_are_added_per_open_trade(self) -> None:
        without_costs = calculate_grid_stress(
            initial_lot=Decimal("0.1"),
            point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"),
            multiplier=Decimal("1"),
            max_trades=2,
            stress_points=Decimal("15"),
            daily_budget=Decimal("100"),
        )
        with_costs = calculate_grid_stress(
            initial_lot=Decimal("0.1"),
            point_value_per_lot=Decimal("1"),
            step_points=Decimal("10"),
            multiplier=Decimal("1"),
            max_trades=2,
            stress_points=Decimal("15"),
            daily_budget=Decimal("100"),
            spread_points=Decimal("2"),
            slippage_points=Decimal("1"),
            commission_per_lot=Decimal("0.5"),
        )

        self.assertEqual(with_costs.estimated_loss - without_costs.estimated_loss,
                         Decimal("0.70"))

    def test_rejects_negative_transaction_costs(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-negative"):
            calculate_grid_stress(
                initial_lot=Decimal("0.1"),
                point_value_per_lot=Decimal("1"),
                step_points=Decimal("10"),
                multiplier=Decimal("1"),
                max_trades=2,
                stress_points=Decimal("15"),
                daily_budget=Decimal("100"),
                slippage_points=Decimal("-1"),
            )


class HistoricalGridReplayTests(unittest.TestCase):
    def test_replay_rejects_invalid_costs_before_applying_observed_spread(self) -> None:
        for observed in (None, Decimal("5")):
            for field in ("spread_points", "slippage_points", "commission_per_lot"):
                for value in ("-1", "NaN", "Infinity", "-Infinity"):
                    with self.subTest(observed=observed, field=field, value=value):
                        bars = [
                            replace(bar, spread_points=observed) for bar in self._bars()
                        ]
                        with self.assertRaisesRegex(ValueError, "finite and non-negative"):
                            replay_historical_grid(
                                bars=bars, point_size=Decimal("1"),
                                point_value_per_lot=Decimal("1"),
                                step_value=Decimal("5"), step_is_percentage=False,
                                initial_lot=Decimal("0.1"), max_trades=3,
                                multiplier=Decimal("1"), daily_budget=Decimal("100"),
                                **{field: Decimal(value)},
                            )

    def test_configured_spread_above_observed_spread_remains_the_floor(self) -> None:
        bars = [replace(bar, spread_points=Decimal("2")) for bar in self._bars()]
        result = replay_historical_grid(
            bars=bars, point_size=Decimal("1"), point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"), step_is_percentage=False,
            initial_lot=Decimal("0.1"), max_trades=3,
            multiplier=Decimal("1"), daily_budget=Decimal("100"),
            spread_points=Decimal("5"),
        )
        self.assertEqual(result.estimated_loss, Decimal("3.3"))

    def test_historical_suggestion_accounts_for_endpoint_entry_costs(self) -> None:
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("100"), Decimal("90"), Decimal("100"),
            )
            for index in range(20)
        ]
        result = suggest_safe_grid_settings_from_history(
            bars=bars,
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("10"),
            step_is_percentage=False,
            daily_budget=Decimal("16"),
            lot_step=Decimal("1"),
            minimum_lot=Decimal("1"),
            max_trades_limit=2,
            spread_points=Decimal("2"),
        )
        self.assertEqual(result.max_trades, 1)
        self.assertEqual(result.estimated_loss, Decimal("12"))
        self.assertLessEqual(result.estimated_loss, result.loss_budget)

    def test_entirely_flat_history_can_still_model_spread_loss(self) -> None:
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("100"), Decimal("100"), Decimal("100"), Decimal("10"),
            )
            for index in range(20)
        ]
        result = replay_historical_grid(
            bars=bars,
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            initial_lot=Decimal("1"),
            max_trades=3,
            multiplier=Decimal("1"),
            daily_budget=Decimal("100"),
        )
        self.assertEqual(result.estimated_loss, Decimal("10"))
        self.assertEqual(result.recommended_max_lot, Decimal("8"))

    def test_flat_history_without_costs_cannot_determine_a_lot_ceiling(self) -> None:
        bars = [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal("100"), Decimal("100"), Decimal("100"),
            )
            for index in range(20)
        ]
        with self.assertRaisesRegex(ValueError, "No modeled price or transaction-cost loss"):
            suggest_safe_grid_settings_from_history(
                bars=bars,
                point_size=Decimal("1"),
                point_value_per_lot=Decimal("1"),
                step_value=Decimal("5"),
                step_is_percentage=False,
                daily_budget=Decimal("100"),
                lot_step=Decimal("0.01"),
                minimum_lot=Decimal("0.01"),
            )

    def test_flat_bar_still_contributes_transaction_cost_risk(self) -> None:
        bars = self._bars()
        bars[8] = DailyBar(
            bars[8].date, Decimal("95"), Decimal("95"), Decimal("95"),
            Decimal("100"),
        )
        result = replay_historical_grid(
            bars=bars,
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            initial_lot=Decimal("1"),
            max_trades=3,
            multiplier=Decimal("1"),
            daily_budget=Decimal("1000"),
        )
        self.assertEqual(result.worst_date, bars[8].date)
        self.assertEqual(result.estimated_loss, Decimal("100"))

    def _bars(self) -> list[DailyBar]:
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
        bars[7] = DailyBar(
            bars[7].date, Decimal("101"), Decimal("90"), Decimal("95")
        )
        return bars

    def test_replay_identifies_worst_adverse_daily_bar(self) -> None:
        result = replay_historical_grid(
            bars=self._bars(),
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            initial_lot=Decimal("0.1"),
            max_trades=3,
            multiplier=Decimal("1"),
            daily_budget=Decimal("100"),
        )

        self.assertEqual(result.worst_date, "2026-01-08")
        self.assertEqual(result.stress_points, Decimal("11"))
        self.assertEqual(result.estimated_loss, Decimal("1.8"))

    def test_historical_suggestion_respects_minimum_lot_and_costs(self) -> None:
        result = suggest_safe_grid_settings_from_history(
            bars=self._bars(),
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
            spread_points=Decimal("1"),
            slippage_points=Decimal("1"),
            commission_per_lot=Decimal("0.5"),
        )

        self.assertEqual(result.worst_date, "2026-01-08")
        self.assertLessEqual(result.estimated_loss, result.loss_budget)
        self.assertGreaterEqual(result.initial_lot, Decimal("0.01"))

    def test_historical_suggestion_caps_lot_at_broker_order_volume_max(self) -> None:
        result = suggest_safe_grid_settings_from_history(
            bars=self._bars(),
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            daily_budget=Decimal("10000"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
            maximum_lot=Decimal("0.035"),
        )

        self.assertEqual(result.initial_lot, Decimal("0.03"))
        self.assertLessEqual(result.initial_lot, Decimal("0.035"))

    def test_replay_uses_observed_daily_spread_when_above_configured_floor(self) -> None:
        bars = self._bars()
        bars[7] = DailyBar(
            bars[7].date,
            bars[7].high,
            bars[7].low,
            bars[7].close,
            Decimal("5"),
        )

        result = replay_historical_grid(
            bars=bars,
            point_size=Decimal("1"),
            point_value_per_lot=Decimal("1"),
            step_value=Decimal("5"),
            step_is_percentage=False,
            initial_lot=Decimal("0.1"),
            max_trades=3,
            multiplier=Decimal("1"),
            daily_budget=Decimal("100"),
        )

        self.assertEqual(result.worst_date, "2026-01-08")
        self.assertEqual(result.estimated_loss, Decimal("3.3"))


class HistoricalGridCampaignBacktestTests(unittest.TestCase):
    def _price_path(self, prices: list[tuple[str, str, str, str]]) -> list[DailyBar]:
        last_close = prices[-1][3]
        prices = prices + [(last_close,) * 4] * (20 - len(prices))
        return [
            DailyBar(
                (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                Decimal(high), Decimal(low), Decimal(close), open=Decimal(opening),
            )
            for index, (opening, high, low, close) in enumerate(prices)
        ]

    def test_later_recovery_does_not_change_previous_drawdown_pct_or_dates(self) -> None:
        result = self._run(
            self._price_path([
                ("100", "100", "100", "100"),
                ("100", "100", "50", "90"),
                ("90", "200", "90", "190"),
            ]),
            initial_equity=Decimal("100"),
            initial_lot=Decimal("1"),
            max_trades=1,
            take_profit_points=Decimal("1000"),
        )
        self.assertEqual(result.max_drawdown_cash, Decimal("50"))
        self.assertEqual(result.max_drawdown_pct, Decimal("50"))
        self.assertEqual(result.drawdown_peak_date, "2026-01-01")
        self.assertEqual(result.drawdown_trough_date, "2026-01-02")

    def test_cash_and_percentage_drawdown_maxima_are_tracked_independently(self) -> None:
        result = self._run(
            self._price_path([
                ("100", "100", "100", "100"),
                ("100", "100", "50", "100"),
                ("100", "300", "100", "300"),
                ("300", "300", "240", "300"),
            ]),
            initial_equity=Decimal("100"),
            initial_lot=Decimal("1"),
            max_trades=1,
            take_profit_points=Decimal("1000"),
        )
        self.assertEqual(result.max_drawdown_cash, Decimal("60"))
        self.assertEqual(result.max_drawdown_pct, Decimal("50"))
        self.assertEqual(result.drawdown_peak_date, "2026-01-03")
        self.assertEqual(result.drawdown_trough_date, "2026-01-04")

    def test_adverse_gap_fills_at_open_then_reanchors_grid(self) -> None:
        for is_long, opening in ((True, "80"), (False, "120")):
            with self.subTest(is_long=is_long):
                result = self._run(
                    self._price_path([
                        ("100", "100", "100", "100"),
                        (opening, opening, opening, opening),
                    ]),
                    initial_lot=Decimal("1"),
                    take_profit_points=Decimal("100"),
                    is_long=is_long,
                )
                self.assertEqual(result.net_profit, Decimal("-20"))
                self.assertEqual(result.max_open_trades, 2)
                self.assertEqual(result.max_drawdown_cash, Decimal("20"))
                self.assertEqual(result.worst_daily_loss, Decimal("20"))

    def test_favorable_open_closes_basket_before_later_adverse_move(self) -> None:
        for is_long, prices in (
            (True, ("110", "111", "50", "100")),
            (False, ("90", "150", "89", "100")),
        ):
            with self.subTest(is_long=is_long):
                result = self._run(
                    self._price_path([
                        ("100", "100", "100", "100"), prices,
                    ]),
                    initial_lot=Decimal("1"),
                    is_long=is_long,
                )
                self.assertEqual(result.net_profit, Decimal("10"))
                self.assertEqual(result.max_open_trades, 1)
                self.assertEqual(result.take_profit_count, 1)
                self.assertEqual(result.max_drawdown_cash, Decimal("0"))

    def test_gap_loss_includes_costs_of_all_filled_orders(self) -> None:
        result = self._run(
            self._price_path([
                ("100", "100", "100", "100"),
                ("80", "80", "80", "80"),
            ]),
            initial_lot=Decimal("1"),
            take_profit_points=Decimal("100"),
            spread_points=Decimal("2"),
            slippage_points=Decimal("1"),
            commission_per_lot=Decimal("0.5"),
        )
        self.assertEqual(result.net_profit, Decimal("-27"))
        self.assertEqual(result.max_drawdown_cash, Decimal("27"))
        self.assertEqual(result.worst_daily_loss, Decimal("23.5"))

    def test_missing_open_fallback_stays_inside_bar_range(self) -> None:
        bars = [
            DailyBar(
                bar.date, bar.high, bar.low, bar.close,
            )
            for bar in self._price_path([
                ("100", "100", "100", "100"),
                ("80", "81", "79", "80"),
            ])
        ]
        result = self._run(
            bars, initial_lot=Decimal("1"), take_profit_points=Decimal("100"),
        )
        self.assertEqual(result.max_open_trades, 2)
        self.assertEqual(result.net_profit, Decimal("-21"))
        self.assertEqual(result.max_drawdown_cash, Decimal("23"))

    def test_equity_at_favorable_open_is_observed_before_adverse_extreme(self) -> None:
        result = self._run(
            self._price_path([
                ("100", "100", "100", "100"),
                ("120", "120", "80", "100"),
            ]),
            initial_equity=Decimal("100"),
            initial_lot=Decimal("1"),
            max_trades=1,
            take_profit_points=Decimal("1000"),
        )
        self.assertEqual(result.max_drawdown_cash, Decimal("40"))
        self.assertEqual(result.max_drawdown_pct, Decimal("4000") / Decimal("120"))
        self.assertEqual(result.drawdown_peak_date, "2026-01-02")
        self.assertEqual(result.drawdown_trough_date, "2026-01-02")

    def _bars(
        self,
        adverse_low: str = "90",
        recovery_high: str = "103",
        adverse_close: str = "100",
    ) -> list[DailyBar]:
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
        bars[2] = DailyBar(
            bars[2].date,
            Decimal(recovery_high),
            Decimal(adverse_low),
            Decimal(adverse_close),
        )
        return bars

    def _run(self, bars: list[DailyBar], **overrides: object):
        inputs = {
            "bars": bars,
            "initial_equity": Decimal("1000"),
            "point_size": Decimal("1"),
            "point_value_per_lot": Decimal("1"),
            "step_points": Decimal("5"),
            "take_profit_points": Decimal("5"),
            "initial_lot": Decimal("0.1"),
            "max_trades": 3,
        }
        inputs.update(overrides)
        return backtest_historical_grid_campaign(**inputs)

    def test_replays_entries_drawdown_and_basket_take_profit_chronologically(self) -> None:
        result = self._run(self._bars())

        self.assertEqual(result.max_open_trades, 3)
        self.assertEqual(result.take_profit_count, 1)
        self.assertEqual(result.max_drawdown_cash, Decimal("1.6"))
        self.assertEqual(result.worst_daily_loss, Decimal("1.5"))
        self.assertEqual(result.net_profit, Decimal("1.5"))
        self.assertFalse(result.grid_exhausted)

    def test_charges_transaction_costs_for_each_opened_order(self) -> None:
        result = self._run(
            self._bars(),
            spread_points=Decimal("2"),
            slippage_points=Decimal("1"),
            commission_per_lot=Decimal("0.5"),
        )

        self.assertEqual(result.net_profit, Decimal("0.45"))
        self.assertEqual(result.max_drawdown_cash, Decimal("2.55"))

    def test_reports_grid_exhaustion_and_liquidates_open_positions_at_end(self) -> None:
        result = self._run(
            self._price_path([
                ("100", "100", "100", "100"),
                ("100", "100", "80", "80"),
                ("80", "101", "80", "100"),
            ]),
            max_trades=2,
        )

        self.assertTrue(result.grid_exhausted)
        self.assertEqual(result.max_open_trades, 2)
        self.assertEqual(result.take_profit_count, 0)
        self.assertEqual(result.net_profit, Decimal("0.5"))

    def test_short_campaign_adds_on_rallies_and_takes_profit_on_fall(self) -> None:
        result = self._run(
            self._bars(adverse_low="95", recovery_high="110"),
            is_long=False,
        )

        self.assertEqual(result.max_open_trades, 3)
        self.assertEqual(result.take_profit_count, 1)
        self.assertEqual(result.net_profit, Decimal("1.5"))

    def test_rejects_invalid_campaign_parameters(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be positive and finite"):
            self._run(self._bars(), step_points=Decimal("0"))
        with self.assertRaisesRegex(ValueError, "Maximum trades"):
            self._run(self._bars(), max_trades=0)


class PortfolioRiskCapTests(unittest.TestCase):
    def test_uses_daily_cap_when_total_loss_room_is_not_configured(self) -> None:
        self.assertEqual(
            effective_portfolio_risk_cap(Decimal("450")),
            Decimal("450"),
        )

    def test_uses_the_tighter_prop_or_daily_cap(self) -> None:
        self.assertEqual(
            effective_portfolio_risk_cap(
                Decimal("450"), remaining_total_loss_room=Decimal("300")
            ),
            Decimal("300"),
        )
        self.assertEqual(
            effective_portfolio_risk_cap(
                Decimal("450"), remaining_total_loss_room=Decimal("600")
            ),
            Decimal("450"),
        )

    def test_uses_remaining_daily_room_when_it_is_the_tightest_limit(self) -> None:
        self.assertEqual(
            effective_portfolio_risk_cap(
                Decimal("450"),
                remaining_daily_loss_room=Decimal("100"),
                remaining_total_loss_room=Decimal("300"),
            ),
            Decimal("100"),
        )

    def test_rejects_zero_remaining_prop_loss_room(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite positive"):
            effective_portfolio_risk_cap(
                Decimal("450"), remaining_total_loss_room=Decimal("0")
            )


if __name__ == "__main__":
    unittest.main()
