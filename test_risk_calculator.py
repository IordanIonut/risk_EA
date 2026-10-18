import unittest
from datetime import date, timedelta
from decimal import Decimal

from risk_calculator import (
    DailyBar,
    calculate_historical_stress,
    effective_portfolio_risk_cap,
    suggest_safe_grid_settings,
)


class HistoricalStressTests(unittest.TestCase):
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


class SafeGridSuggestionTests(unittest.TestCase):
    def test_rounds_lot_down_to_volume_step_and_fits_allowance(self) -> None:
        result = suggest_safe_grid_settings(
            stress_points=Decimal("1000"),
            step_points=Decimal("100"),
            point_value_per_lot=Decimal("1"),
            daily_budget=Decimal("100"),
            lot_step=Decimal("0.01"),
            minimum_lot=Decimal("0.01"),
        )

        self.assertEqual(result.max_trades, 10)
        self.assertEqual(result.initial_lot, Decimal("0.01"))
        self.assertLessEqual(result.estimated_loss, result.loss_budget)

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
