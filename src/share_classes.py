"""
Rules that make Share Counts comparable across Companies with several Share Classes.

See: docs/adr/0001-signals-count-shares-in-primary-class-units.md
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

ALL_CLASSES = "all classes"
UNMATCHED = "unmatched"
SCOPE_TOLERANCE = 0.005


def company_share_count(counts: pd.DataFrame) -> pd.Series:
    """
    Return the Company Share Count: `share_count` times `share_factor`.

    See: docs/adr/0001-signals-count-shares-in-primary-class-units.md
    """
    return counts["share_count"] * counts["share_factor"]


def share_count_scope(share_count: float, cover_counts: Mapping[str, float]) -> str:
    """
    Return which Share Classes a Share Count covers: ALL_CLASSES, the one matching class,
    or UNMATCHED, judged against the per-class counts on the same filing's cover page.
    """
    total = sum(cover_counts.values())
    if not total or np.isnan(total):
        return UNMATCHED
    if _matches(share_count, total):
        return ALL_CLASSES
    for share_class, count in cover_counts.items():
        if count and _matches(share_count, count):
            return share_class
    return UNMATCHED


def split_multiplier(splits: pd.DataFrame, ticker: str, filed: pd.Timestamp) -> float:
    """
    Return the factor that brings a count filed on `filed` to today's split-adjusted units.
    """
    later = splits[(splits["ticker"] == ticker) & (splits["date"] > filed)]
    return float(np.prod(later["value"])) if len(later) else 1.0


def _matches(value: float, target: float) -> bool:
    return abs(value / target - 1) < SCOPE_TOLERANCE
