"""
Percentage Shares Issued for each Constituent on each Rebalance Date, ranked across Constituents.

See: research/pct_issuance.py
"""

import logging
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.share_classes import SCOPE_BREAKS, company_share_count, crosses_scope_break

logger = logging.getLogger(__name__)

SIGNAL_COLUMNS = (
    "date",
    "permaticker",
    "ticker",
    "net_shares_issued",
    "pct_shares_issued",
    "pct_shares_issued_rank",
    "filing_age_days",
    "missing_reason",
    "corporate_event_in_lookback",
)
FILING_COLUMNS = ("ticker", "filed_date", "effective_date", "period_end", "share_count", "share_factor")

NO_SHARE_COUNT = "no_share_count"
STALE = "stale"
NO_COMPARISON = "no_comparison"
SCOPE_BREAK = "scope_break"
# Highest priority first: a Constituent with several reasons records the first.
MISSING_REASONS = (NO_SHARE_COUNT, STALE, NO_COMPARISON, SCOPE_BREAK)

LOOKBACK_EVENT_ACTIONS = frozenset({"spinoff", "spinoffdividend", "spunofffrom", "mergerfrom", "mergerto"})
LOOKBACK_EVENT_PREFIX = "acquisition"


class SignalCheckError(Exception):
    """
    The Signal table broke a rule that makes it wrong rather than merely worth reviewing.
    """


def rebalance_dates(trading_days: pd.Series, frequency: str = "Q") -> pd.DatetimeIndex:
    """
    Return the last trading day of each completed calendar period, quarters by default.
    """
    days = pd.Series(pd.to_datetime(trading_days).unique()).sort_values()
    periods = days.dt.to_period(frequency)
    last_days = days.groupby(periods).max()
    complete = last_days.index.end_time.normalize() <= days.max()
    return pd.DatetimeIndex(last_days[complete].to_numpy())


def constituents_on(panel: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = panel[panel["date"].isin(dates) & panel["in_sp500"]]
    return rows[["date", "permaticker", "ticker"]].sort_values(["date", "ticker"]).reset_index(drop=True)


def filing_history(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Return each filing the Panel carries once, with the Share Count and Effective Date it was used with.
    """
    filings = panel.dropna(subset=["filed_date"])[list(FILING_COLUMNS)]
    return filings.drop_duplicates(["ticker", "filed_date", "period_end"]).reset_index(drop=True)


def pct_shares_issued(
    constituents: pd.DataFrame,
    filings: pd.DataFrame,
    events: pd.DataFrame,
    lookback_months: int = 12,
    tolerance_days: int = 40,
    max_filing_age_days: int = 200,
    exclude_stale: bool = True,
    scope_breaks: Mapping[str, tuple[pd.Timestamp, ...]] = SCOPE_BREAKS,
) -> pd.DataFrame:
    """
    Return Net Shares Issued, Percentage Shares Issued and its rank for each Constituent on each
    Rebalance Date, with the reason a Constituent has no value.

    See: docs/adr/0003-a-constituent-with-no-share-count-is-not-ranked.md
    """
    filings = filings.assign(company_share_count=company_share_count(filings))
    table = _with_latest_filing(constituents, filings)
    table = _with_comparison_filing(table, filings, lookback_months, tolerance_days)

    table["net_shares_issued"] = table["company_share_count"] - table["earlier_count"]
    table["pct_shares_issued"] = table["net_shares_issued"] / table["earlier_count"]
    table["filing_age_days"] = (table["date"] - table["period_end"]).dt.days.astype("Int64")

    has_comparison = table["earlier_count"].notna() & (table["earlier_count"] > 0)
    breaks = has_comparison & crosses_scope_break(
        table.rename(columns={"filed_date": "later_filed"}), scope_breaks
    )
    stale = exclude_stale & (table["filing_age_days"].fillna(0) > max_filing_age_days)
    applies = {
        NO_SHARE_COUNT: table["company_share_count"].isna(),
        STALE: stale,
        NO_COMPARISON: ~has_comparison,
        SCOPE_BREAK: breaks,
    }
    reason = pd.Series(None, index=table.index, dtype=object)
    for name in reversed(MISSING_REASONS):
        reason[applies[name]] = name
    table["missing_reason"] = reason
    _warn_no_comparison(table)

    unranked = table["missing_reason"].notna()
    table.loc[unranked, ["net_shares_issued", "pct_shares_issued"]] = np.nan
    table["pct_shares_issued_rank"] = _percentile_ranks(table)
    table["corporate_event_in_lookback"] = _event_in_lookback(table, events)
    return table.sort_values(["date", "ticker"]).reset_index(drop=True)[list(SIGNAL_COLUMNS)]


def check_signal(table: pd.DataFrame) -> None:
    """
    Enforce the row rules on a Percentage Shares Issued table.

    Raises:
        SignalCheckError: the columns differ from SIGNAL_COLUMNS, a Company has two rows on one date,
            a value and a missing reason disagree, or a rank falls outside 0 to 1.
    """
    if tuple(table.columns) != SIGNAL_COLUMNS:
        difference = sorted(set(table.columns) ^ set(SIGNAL_COLUMNS))
        raise SignalCheckError(f"The columns differ from SIGNAL_COLUMNS: {difference}.")
    duplicated = table.duplicated(["permaticker", "date"])
    if duplicated.any():
        raise SignalCheckError(f"{duplicated.sum()} rows are two rows for one Company on one date.")
    valued = table["pct_shares_issued"].notna()
    disagree = (valued == table["missing_reason"].notna()) | (valued != table["pct_shares_issued_rank"].notna())
    if disagree.any():
        raise SignalCheckError(f"{disagree.sum()} rows have a value, rank and missing reason that disagree.")
    ranks = table["pct_shares_issued_rank"].dropna()
    if ((ranks < 0) | (ranks > 1)).any():
        raise SignalCheckError("A rank falls outside 0 to 1.")


def write_signal(table: pd.DataFrame, directory: Path | str, as_of: date | str) -> Path:
    """
    Write the Percentage Shares Issued table, named for the date of the Panel it came from.

    Raises:
        FileExistsError: an output for this date exists, and outputs are never overwritten.
    """
    path = Path(directory) / f"sp500_pct_issuance_{as_of}.parquet"
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path.name}.")
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False)
    return path


def _with_latest_filing(constituents: pd.DataFrame, filings: pd.DataFrame) -> pd.DataFrame:
    return pd.merge_asof(
        constituents.astype({"date": "datetime64[ns]"}).sort_values("date"),
        filings.astype({"effective_date": "datetime64[ns]"}).sort_values("effective_date"),
        left_on="date",
        right_on="effective_date",
        by="ticker",
    )


def _with_comparison_filing(
    table: pd.DataFrame, filings: pd.DataFrame, lookback_months: int, tolerance_days: int
) -> pd.DataFrame:
    table = table.reset_index(drop=True)
    target = table["period_end"] - pd.DateOffset(months=lookback_months)
    keys = table[["ticker", "date"]].assign(target=target).reset_index()
    candidates = keys.merge(
        filings[["ticker", "filed_date", "effective_date", "period_end", "company_share_count"]], on="ticker"
    )
    candidates["distance"] = (candidates["period_end"] - candidates["target"]).abs()
    known = candidates["effective_date"] <= candidates["date"]
    near = candidates["distance"] <= pd.Timedelta(days=tolerance_days)
    # See docs/adr/0001-a-refiled-quarter-keeps-the-first-share-count.md
    matched = candidates[known & near].sort_values(["distance", "filed_date"])
    best = matched.drop_duplicates("index").set_index("index")
    table["earlier_filed"] = best["filed_date"]
    table["earlier_count"] = best["company_share_count"]
    return table


def _warn_no_comparison(table: pd.DataFrame) -> None:
    missing = table[table["missing_reason"] == NO_COMPARISON]
    for day, rows in missing.groupby("date"):
        logger.warning(
            "%s: %d Constituents have no filing one Lookback back, so they are not ranked: %s",
            day.date(),
            len(rows),
            ", ".join(sorted(rows["ticker"])),
        )


def _percentile_ranks(table: pd.DataFrame) -> pd.Series:
    values = table["pct_shares_issued"]
    ranks = values.groupby(table["date"]).rank(method="average")
    counts = values.groupby(table["date"]).transform("count")
    return ((ranks - 1) / (counts - 1)).where(counts > 1, 0.5).where(values.notna())


def _event_in_lookback(table: pd.DataFrame, events: pd.DataFrame) -> pd.Series:
    wanted = events["action"].isin(LOOKBACK_EVENT_ACTIONS) | events["action"].str.startswith(LOOKBACK_EVENT_PREFIX)
    windows = table[["ticker", "earlier_filed", "filed_date"]].reset_index()
    joined = windows.merge(events.loc[wanted, ["ticker", "date"]], on="ticker")
    inside = (joined["date"] > joined["earlier_filed"]) & (joined["date"] <= joined["filed_date"])
    flag = pd.Series(False, index=table.index)
    flag.loc[joined.loc[inside, "index"].unique()] = True
    return flag
