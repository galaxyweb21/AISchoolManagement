"""Small, deterministic helpers for measuring intervention score movement."""
from decimal import Decimal


def compare_terminal_scores(baseline_score, followup_score):
    """Compare two authoritative terminal scores without inventing missing data."""
    if baseline_score is None or followup_score is None:
        return {'change': None, 'trend': 'PENDING'}

    change = Decimal(str(followup_score)) - Decimal(str(baseline_score))
    if change > 0:
        trend = 'IMPROVED'
    elif change < 0:
        trend = 'DECLINED'
    else:
        trend = 'UNCHANGED'
    return {'change': change, 'trend': trend}
