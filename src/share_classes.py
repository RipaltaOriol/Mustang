"""
Rules that make Share Counts comparable across Companies with several Share Classes.

See: docs/adr/0002-signals-count-shares-in-primary-class-units.md
"""

from collections.abc import Mapping

import numpy as np
import pandas as pd

ALL_CLASSES = "all classes"
UNMATCHED = "unmatched"
SCOPE_TOLERANCE = 0.005

# Filings whose Share Count covers different Share Classes from the filing before; found by
# research/share_class_check.py.
SCOPE_BREAKS: Mapping[str, tuple[pd.Timestamp, ...]] = {
    "ARES": (pd.Timestamp("2020-05-08"), pd.Timestamp("2026-02-25")),
    "KKR": (pd.Timestamp("2018-11-02"), pd.Timestamp("2020-08-07")),
    "PCG": (pd.Timestamp("2026-07-23"),),
}


def company_share_count(counts: pd.DataFrame) -> pd.Series:
    """
    Return the Company Share Count: `share_count` times `share_factor`.

    See: docs/adr/0002-signals-count-shares-in-primary-class-units.md
    """
    return counts["share_count"] * counts["share_factor"]


def crosses_scope_break(
    changes: pd.DataFrame, breaks: Mapping[str, tuple[pd.Timestamp, ...]] = SCOPE_BREAKS
) -> pd.Series:
    """
    Flag the changes between two filings, `earlier_filed` to `later_filed`, over which the
    Share Count's Share Classes change, so the change reads as issuance or a buyback.

    See: docs/adr/0002-signals-count-shares-in-primary-class-units.md
    """
    crosses = pd.Series(False, index=changes.index)
    for ticker, dates in breaks.items():
        own = changes["ticker"] == ticker
        for day in dates:
            crosses |= own & (changes["earlier_filed"] < day) & (changes["later_filed"] >= day)
    return crosses


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
