"""Named-heuristic calculations fed into the AI interpretation prompt.

Computed here rather than left for the model to infer.
"""


def sahm_rule_value(readings: list[dict]) -> float | None:
    """3-month average unemployment rate minus its 12-month low.

    `readings` is a chronologically ordered list of {"date", "value"}
    entries (monthly unemployment rate). A result >= 0.5 is the widely-used
    recession-signal threshold. Returns None if fewer than 12 readings are
    available to compute a reliable 12-month low.
    """
    if len(readings) < 12:
        return None

    values = [r["value"] for r in readings]
    last_3_avg = sum(values[-3:]) / 3
    twelve_month_low = min(values[-12:])
    return round(last_3_avg - twelve_month_low, 2)


def yield_curve_inversion_streak(readings: list[dict]) -> int:
    """Count consecutive negative (inverted) readings ending at the latest entry.

    `readings` is a chronologically ordered list of {"date", "value"}
    entries (10yr-2yr spread). Returns 0 if the most recent reading isn't
    negative, regardless of any earlier inverted stretch.
    """
    streak = 0
    for r in reversed(readings):
        if r["value"] < 0:
            streak += 1
        else:
            break
    return streak
