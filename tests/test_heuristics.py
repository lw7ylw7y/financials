import os
import sys
import unittest

_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
for _p in (
    _SRC,
    os.path.join(_SRC, "fred"),
    os.path.join(_SRC, "storage"),
    os.path.join(_SRC, "digest"),
    os.path.join(_SRC, "mailer"),
):
    sys.path.insert(0, _p)

from heuristics import sahm_rule_value, yield_curve_inversion_streak


def readings(values):
    return [{"date": f"2026-{i + 1:02d}-01", "value": v} for i, v in enumerate(values)]


class TestSahmRuleValue(unittest.TestCase):
    def test_computes_against_known_sample_series(self):
        # 12 months, low of 3.5 in months 1-9, then a rise to 4.0/4.2/4.4.
        values = [3.5] * 9 + [4.0, 4.2, 4.4]
        result = sahm_rule_value(readings(values))

        # last-3 avg = (4.0+4.2+4.4)/3 = 4.2; 12-month low = 3.5
        self.assertEqual(result, round(4.2 - 3.5, 2))

    def test_returns_none_with_fewer_than_12_readings(self):
        result = sahm_rule_value(readings([3.5] * 11))
        self.assertIsNone(result)

    def test_zero_when_no_rise_above_low(self):
        result = sahm_rule_value(readings([3.5] * 12))
        self.assertEqual(result, 0.0)


class TestYieldCurveInversionStreak(unittest.TestCase):
    def test_counts_consecutive_negative_readings(self):
        values = [0.2, -0.1, -0.2, -0.3]
        self.assertEqual(yield_curve_inversion_streak(readings(values)), 3)

    def test_resets_on_positive_reading(self):
        values = [-0.5, -0.4, 0.1, -0.2]
        self.assertEqual(yield_curve_inversion_streak(readings(values)), 1)

    def test_zero_when_latest_reading_is_not_negative(self):
        values = [-0.5, -0.4, 0.1]
        self.assertEqual(yield_curve_inversion_streak(readings(values)), 0)

    def test_zero_on_empty_history(self):
        self.assertEqual(yield_curve_inversion_streak([]), 0)


if __name__ == "__main__":
    unittest.main()
