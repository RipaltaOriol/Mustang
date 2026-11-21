# %% [markdown]
# # Share Counts of Companies with several Share Classes
#
# Checks each Share Count against the per-class shares outstanding on the cover of the same SEC
# filing, to find whether it covers all Share Classes or one. See GitHub issue #2 and
# docs/adr/0002-signals-count-shares-in-primary-class-units.md.
#
# Needs `SHARADAR_API_KEY` and `SEC_USER_AGENT` (a name and contact email, as SEC requires) in
# the environment or `.env`. SEC downloads are cached in `data/sec/`; a first run takes about an
# hour.

# %%
import os

import pandas as pd
from dotenv import dotenv_values

from src.panel import PANEL_START, PROCESSED_DIR, SECONDARY_TO_PRIMARY, company_periods
from src.providers import DataProviderError, SecProvider, SharadarProvider
from src.share_classes import (
    ALL_CLASSES,
    SCOPE_BREAKS,
    SCOPE_TOLERANCE,
    UNMATCHED,
    company_share_count,
    share_count_scope,
    split_multiplier,
)

# %%
START = PANEL_START
ALWAYS_CHECK = sorted({*SECONDARY_TO_PRIMARY.values(), "BRK.B", "V", "BF.B"})
FILING_MATCH_DAYS = 3
SCREEN_UNMATCHED_SHARE = 0.1
BREAK_GAP = 0.05
BRK_A_IN_B_SHARES = 1_500

# %% [markdown]
# ## Inputs

# %%
sharadar = SharadarProvider.from_env()
user_agent = os.environ.get("SEC_USER_AGENT") or dotenv_values(".env").get("SEC_USER_AGENT")
sec = SecProvider(user_agent or "", PROCESSED_DIR.parent / "sec")

ever_members = set(company_periods(sharadar.fetch_table("sp500"))["ticker"])
records = sharadar.fetch_table(
    "tickers", fields=["ticker", "name", "secfilings"], filters={"table": "fundamentals"}
)
records = records[records["ticker"].isin(ever_members)].assign(
    cik=lambda frame: frame["secfilings"].str.extract(r"CIK=(\d+)")[0].astype(int)
)
records

# %%
filings = sharadar.fetch_snapshot(
    "fundamentals",
    tickers=sorted(ever_members),
    fields=("reportperiod", "sharesbas", "sharefactor"),
    filters={"dimension": "ARQ"},
).rename(columns={"date": "filed_date", "sharesbas": "share_count", "sharefactor": "share_factor"})
filings["filed_date"] = pd.to_datetime(filings["filed_date"]).astype("datetime64[ns]")
filings = filings[filings["filed_date"] >= pd.Timestamp(START) - pd.DateOffset(months=6)]
filings

# %%
splits = sharadar.fetch_snapshot("actions", fields=("action", "value"), filters={"action": "split"})
splits["date"] = pd.to_datetime(splits["date"]).astype("datetime64[ns]")
splits

# %% [markdown]
# ## Screen
#
# A Company whose cover reports one count without a Share Class has a same-day SEC count to
# match. Companies that report only per class, or whose count disagrees, go to the full check.

# %%
screen = []
for record in records.itertuples():
    own = filings[filings["ticker"] == record.ticker]
    undimensioned = sec.undimensioned_cover_counts(record.cik)
    matched = own.merge(undimensioned, on="filed_date", how="left")
    multiplier = [split_multiplier(splits, record.ticker, day) for day in matched["filed_date"]]
    ratio = matched["share_count"] / (matched["shares_outstanding"] * multiplier)
    screen.append(
        {
            "ticker": record.ticker,
            "filings": len(own),
            "unmatched": int(ratio.isna().sum()),
            "disagreeing": int(((ratio - 1).abs() >= SCOPE_TOLERANCE).sum()),
        }
    )
screen = pd.DataFrame(screen)
flagged = screen[
    (screen["unmatched"] >= SCREEN_UNMATCHED_SHARE * screen["filings"]) | (screen["disagreeing"] > 0)
]
flagged.sort_values("unmatched", ascending=False)

# %% [markdown]
# ## Check against the cover
#
# Every filing of a flagged Company is compared with the sum of its cover's per-class shares
# outstanding, after the splits since filing.

# %%
cik_of = dict(zip(records["ticker"], records["cik"]))
checks = []
for ticker in sorted(set(flagged["ticker"]) | (set(ALWAYS_CHECK) & ever_members)):
    reports = sec.periodic_reports(cik_of[ticker])
    for filing in filings[filings["ticker"] == ticker].sort_values("filed_date").itertuples():
        gap = (reports["filed_date"] - filing.filed_date).abs()
        if gap.empty or gap.min() > pd.Timedelta(days=FILING_MATCH_DAYS):
            checks.append({"ticker": ticker, "filed_date": filing.filed_date, "scope": "no SEC filing"})
            continue
        accession = reports.loc[gap.idxmin(), "accession"]
        try:
            cover = sec.cover(cik_of[ticker], accession)
        except DataProviderError:
            cover = {}
        multiplier = split_multiplier(splits, ticker, filing.filed_date)
        cover = {share_class: count * multiplier for share_class, count in cover.items()}
        checks.append(
            {
                "ticker": ticker,
                "filed_date": filing.filed_date,
                "accession": accession,
                "share_count": filing.share_count,
                "share_factor": filing.share_factor,
                "cover": cover,
                "classes": sum("StatementClassOfStockAxis" in key for key in cover),
                "scope": share_count_scope(filing.share_count, cover),
            }
        )
checks = pd.DataFrame(checks)
checks

# %% [markdown]
# ## Scope by Company
#
# Only covers that list several Share Classes. A row with every check under `all classes` is a
# Company whose Share Count is its total across classes.

# %%
several = checks[checks["classes"] > 1]
scope_table = several.groupby(["ticker", "scope"]).size().unstack(fill_value=0)
scope_table

# %%
scope_table[scope_table.drop(columns=ALL_CLASSES, errors="ignore").sum(axis=1) > 0]

# %% [markdown]
# A class named in the table above is either a co-registrant subsidiary, whose count belongs
# to another entity, or a Share Class the Share Count leaves out. Read the cover to tell.

# %%
for row in several[several["scope"] != ALL_CLASSES].itertuples():
    print(row.ticker, row.filed_date.date(), f"{row.share_count:,.0f}", row.scope)
    for share_class, count in row.cover.items():
        print(f"    {share_class or '(no class)'}: {count:,.0f}")

# %% [markdown]
# ## Scope breaks
#
# A candidate is a filing whose Share Count moves more than `BREAK_GAP` away from the move in
# its cover's Company total, where the cover lists several classes or the scope changes.
# Subsidiaries and preferred stock are left out of the total.
#
# Only ARES, KKR and PCG change which classes their count covers. ARES and KKR count their
# voting-only Class C, paired with operating units, for a while and then stop. PCG starts
# counting the shares its subsidiary ShareCo holds. ARES's 2020-05-08 break is not a candidate,
# because its cover moves too: Class C was issued then for units that already existed. These
# filings make up `SCOPE_BREAKS`.
#
# The other candidates are covers that list fully diluted counts or extra classes, that
# mis-scale a number, or that are dated after a merger the Share Count already includes. RIG's
# 2026-02-23 Share Count is a one-filing error in Sharadar, not a change of classes.

# %%
read = checks[checks["scope"] != "no SEC filing"].sort_values(["ticker", "filed_date"]).copy()
read["cover_total"] = read["cover"].map(
    lambda cover: sum(
        count
        for share_class, count in cover.items()
        if "LegalEntityAxis" not in share_class and "Preferred" not in share_class
    )
)
read["share_count_change"] = read.groupby("ticker")["share_count"].pct_change()
read["cover_change"] = read.groupby("ticker")["cover_total"].pct_change()
moved_apart = (read["share_count_change"] - read["cover_change"]).abs() > BREAK_GAP
several_classes = (read["classes"] > 1) | (read.groupby("ticker")["classes"].shift() > 1)
scope_changed = read["scope"] != read.groupby("ticker")["scope"].shift()
break_candidates = read[moved_apart & (several_classes | scope_changed)]
break_candidates[["ticker", "filed_date", "share_count_change", "cover_change", "scope"]]

# %%
pd.DataFrame(
    [(ticker, day) for ticker, days in SCOPE_BREAKS.items() for day in days],
    columns=["ticker", "filed_date"],
).merge(read, on=["ticker", "filed_date"])[
    ["ticker", "filed_date", "share_count_change", "cover_change", "scope"]
]

# %% [markdown]
# ## BRK.B: the share factor converts to Primary Class units
#
# One Class A share is worth `BRK_A_IN_B_SHARES` Class B shares. The raw Share Count adds them
# one for one, so a conversion from A to B reads as issuance.

# %%
brk = checks[(checks["ticker"] == "BRK.B") & (checks["classes"] > 1)].copy()
class_a = brk["cover"].map(lambda cover: cover.get("StatementClassOfStockAxis=CommonClassAMember"))
class_b = brk["cover"].map(lambda cover: cover.get("StatementClassOfStockAxis=CommonClassBMember"))
brk["b_equivalents"] = class_b + BRK_A_IN_B_SHARES * class_a
brk["company_share_count"] = company_share_count(brk)
brk["error"] = brk["company_share_count"] / brk["b_equivalents"] - 1
brk[["filed_date", "share_count", "share_factor", "b_equivalents", "company_share_count", "error"]]

# %% [markdown]
# ## Summary

# %%
pd.Series(
    {
        "companies_screened": len(screen),
        "companies_checked": checks["ticker"].nunique(),
        "companies_with_several_classes": several["ticker"].nunique(),
        "filings_checked": int((checks["scope"] != "no SEC filing").sum()),
        "all_class_filings": int((several["scope"] == ALL_CLASSES).sum()),
        "unmatched_filings": int((several["scope"] == UNMATCHED).sum()),
        "brk_filings": len(brk),
        "brk_max_abs_error": brk["error"].abs().max(),
    },
    name="value",
)
