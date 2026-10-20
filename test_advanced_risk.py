from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import unittest

from advanced_risk import (
    EquitySample, ModeledExposure, check_exposures, default_exposure,
    default_profile, evaluate_equity_curve, parse_equity_csv, remaining_rooms,
    validate_exposure, validate_profile,
)


def configured_profile():
    profile = default_profile()
    profile.update(
        enabled=True, current_equity="9900", daily_start_equity="10000",
        daily_start_balance="10000", total_limit_pct="10",
        daily_session_date=datetime.now(timezone.utc).date().isoformat(),
        high_water_equity="10500", free_margin="9900", existing_margin="0",
        stopout_pct="50", idea_limit_pct="2", holding_days="3",
    )
    return profile


def sample(time, equity, balance="10000"):
    return EquitySample(
        datetime.fromisoformat(time.replace("Z", "+00:00")),
        Decimal(balance), Decimal(equity),
    )


class AdvancedRiskTests(unittest.TestCase):
    def test_legacy_defaults_disabled_but_valid(self):
        self.assertFalse(validate_profile(default_profile())["enabled"])
        self.assertEqual(validate_exposure(default_exposure()), default_exposure())

    def test_invalid_profile_types_numbers_time_and_choices_are_rejected(self):
        cases = {
            "enabled": "yes", "current_equity": "NaN", "free_margin": "-1",
            "idea_limit_pct": "101", "total_limit_pct": "0", "reset_time": "24:00",
            "utc_offset_minutes": "841", "holding_days": "2.5",
            "daily_baseline": "guessed", "overall_rule": "unrecognized",
        }
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_profile({**configured_profile(), key: value})
        with self.assertRaises(ValueError):
            validate_profile({})

    def test_swap_is_explicit_nonnegative_cash_debit(self):
        for value in ("NaN", "Infinity", "-1", "not cash"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_exposure({**default_exposure(), "swap_long_debit": value})
        self.assertEqual(
            validate_exposure({**default_exposure(), "swap_long_debit": "0"})["swap_long_debit"],
            "0",
        )

    def test_static_and_continuous_trailing_rooms_are_distinct(self):
        profile = configured_profile()
        self.assertEqual(remaining_rooms(profile, Decimal("10000"), Decimal("500")),
                         (Decimal("400"), Decimal("900")))
        profile["overall_rule"] = "Trailing equity"
        self.assertEqual(remaining_rooms(profile, Decimal("10000"), Decimal("500")),
                         (Decimal("400"), Decimal("400")))

    def test_daily_baseline_can_be_equity_balance_or_higher(self):
        profile = configured_profile()
        profile.update(daily_start_balance="10100", daily_start_equity="9800")
        for rule, expected in (("Equity", "600"), ("Balance", "300"),
                               ("Higher of balance/equity", "300")):
            profile["daily_baseline"] = rule
            self.assertEqual(
                remaining_rooms(profile, Decimal("10000"), Decimal("500"))[0],
                Decimal(expected),
            )

    def test_exhausted_room_is_zero_and_invalid_highwater_is_rejected(self):
        profile = configured_profile()
        profile["current_equity"] = "9000"
        self.assertEqual(remaining_rooms(profile, Decimal("10000"), Decimal("500")),
                         (Decimal("0"), Decimal("0")))
        profile.update(overall_rule="Trailing equity", high_water_equity="9999")
        with self.assertRaisesRegex(ValueError, "High-water"):
            remaining_rooms(profile, Decimal("10000"), Decimal("500"))

    def test_current_room_requires_current_reset_session_date(self):
        profile = configured_profile()
        profile.update(reset_time="01:00", utc_offset_minutes="120",
                       daily_session_date="2026-10-19")
        now = datetime(2026, 10, 19, 23, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "missing/stale"):
            remaining_rooms(profile, Decimal("10000"), Decimal("500"), now)
        profile["daily_session_date"] = "2026-10-20"
        self.assertEqual(
            remaining_rooms(profile, Decimal("10000"), Decimal("500"), now)[0],
            Decimal("400"),
        )

    def test_grouped_robots_share_one_cap_case_insensitively(self):
        profile = configured_profile()
        inputs = {**default_exposure(), "margin_per_lot": "100",
                  "idea_group": "US INDEX"}
        exposures = (
            ModeledExposure("DCA", Decimal(".1"), 3, Decimal("110"), inputs),
            ModeledExposure("RSI", Decimal(".2"), 4, Decimal("90"),
                            {**inputs, "idea_group": "us index"}),
        )
        result = check_exposures(profile, Decimal("10000"), exposures)
        self.assertEqual(result.missing, ())
        self.assertEqual(len(result.breaches), 1)
        self.assertIn("Idea us index", result.breaches[0])
        self.assertIn("Combined grid margin 110.0", " ".join(result.lines))

    def test_margin_and_loss_exhaustion_rejected_even_with_missing_group(self):
        profile = configured_profile()
        inputs = {**default_exposure(), "margin_per_lot": "10000"}
        exposure = ModeledExposure("DCA", Decimal("1"), 1, Decimal("100"), inputs)
        result = check_exposures(profile, Decimal("10000"), (exposure,))
        self.assertTrue(result.missing)
        self.assertTrue(any("free margin" in line for line in result.breaches))

    def test_stopout_and_reconciliation(self):
        profile = configured_profile()
        profile.update(current_equity="1000", free_margin="100", existing_margin="900",
                       stopout_pct="120")
        inputs = {**default_exposure(), "margin_per_lot": "100", "idea_group": "one"}
        exposure = ModeledExposure("EA", Decimal(".1"), 1, Decimal("5"), inputs)
        self.assertTrue(any(
            "stop-out" in line
            for line in check_exposures(profile, Decimal("10000"), (exposure,)).breaches
        ))
        profile["free_margin"] = "200"
        with self.assertRaisesRegex(ValueError, "reconcile"):
            check_exposures(profile, Decimal("10000"), (exposure,))

    def test_csv_requires_offset_positive_balance_complete_rows_and_order(self):
        header = "timestamp,balance,equity\n"
        valid = header + "2026-10-19T00:00:00Z,10000,10000\n2026-10-19T01:00:00Z,10000,9900\n"
        self.assertEqual(len(parse_equity_csv(valid)), 2)
        for invalid in (
            valid.replace("Z", ""), valid.replace("9900", "NaN"),
            valid.replace(",9900", ""), valid.replace(",9900", ",9900,extra"),
            valid.replace("01:00:00", "00:00:00"),
            valid.replace("timestamp,balance,equity", "timestamp,equity,balance"),
            valid.replace(",10000,10000", ",0,10000"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_equity_csv(invalid)

    def test_daily_reset_is_separate_from_overall_loss(self):
        samples = (
            sample("2026-10-18T00:00:00Z", "10000"),
            sample("2026-10-18T23:00:00Z", "9600", "9600"),
            sample("2026-10-19T00:00:00Z", "9600", "9600"),
            sample("2026-10-19T23:00:00Z", "9200", "9200"),
        )
        profile = configured_profile()
        result = evaluate_equity_curve(samples, profile, Decimal("10000"), Decimal("500"))
        self.assertEqual(result.breaches, ())
        self.assertEqual(result.missing, ())
        self.assertIn("daily loss: 400", " ".join(result.lines))
        self.assertIn("drawdown: 800", " ".join(result.lines))

    def test_trailing_floor_tracks_new_peak_not_initial_balance(self):
        profile = configured_profile()
        profile["high_water_equity"] = "10000"
        samples = (
            sample("2026-10-19T00:00:00Z", "10000"),
            sample("2026-10-19T01:00:00Z", "11000"),
            sample("2026-10-19T02:00:00Z", "10000"),
        )
        static = evaluate_equity_curve(samples, profile, Decimal("10000"), Decimal("2000"))
        self.assertEqual(static.breaches, ())
        profile["overall_rule"] = "Trailing equity"
        trailing = evaluate_equity_curve(samples, profile, Decimal("10000"), Decimal("2000"))
        self.assertEqual(len(trailing.breaches), 1)
        self.assertIn("overall", trailing.breaches[0])

    def test_fixed_offset_reset_boundary_and_missing_reset_sample(self):
        profile = configured_profile()
        profile.update(reset_time="01:00", utc_offset_minutes="120")
        samples = (
            sample("2026-10-18T23:00:00Z", "10000"),
            sample("2026-10-19T00:00:00Z", "9500"),
        )
        result = evaluate_equity_curve(samples, profile, Decimal("10000"), Decimal("500"))
        self.assertFalse(result.missing)
        self.assertIn("daily", result.breaches[0])
        approximate = evaluate_equity_curve(
            (replace(samples[0], time=datetime(2026, 10, 18, 23, 1, tzinfo=timezone.utc)),
             samples[1]), profile, Decimal("10000"), Decimal("500"),
        )
        self.assertTrue(approximate.missing)
        self.assertFalse(approximate.breaches)


if __name__ == "__main__":
    unittest.main()
