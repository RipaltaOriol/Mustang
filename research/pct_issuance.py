# %% [markdown]
# # Percentage Shares Issued
#
# Ranks the Constituents on each Rebalance Date by Percentage Shares Issued, the change in the
# Company Share Count over the Lookback as a fraction of the earlier Company Share Count. Built
# from a saved Panel and its Corporate Events.
#
# When you use the table:
# - A rank of 0 is the biggest net buyback and 1 the biggest net issuer, among the Constituents
#   with a value on that date.
# - Constituents with no value stay in the table with a `missing_reason`, and hold no position.
# - `corporate_event_in_lookback` marks changes driven by a merger, acquisition or spin-off. Join
#   to the events table on `ticker` and dates for the details.

# %%
import logging

import pandas as pd

from src.panel import PROCESSED_DIR
from src.signals import (
    check_signal,
    constituents_on,
    filing_history,
    pct_shares_issued,
    rebalance_dates,
    write_signal,
)

logging.basicConfig(format="%(levelname)s %(name)s: %(message)s")

# %%
PANEL_AS_OF = "2026-11-06"
FREQUENCY = "Q"
LOOKBACK_MONTHS = 12
TOLERANCE_DAYS = 40
MAX_FILING_AGE_DAYS = 200
EXCLUDE_STALE = True
SAVE = False

# %% [markdown]
# ## Inputs

# %%
panel = pd.read_parquet(PROCESSED_DIR / f"sp500_panel_{PANEL_AS_OF}.parquet")
events = pd.read_parquet(PROCESSED_DIR / f"sp500_events_{PANEL_AS_OF}.parquet")
panel[["date", "ticker", "in_sp500", "filed_date", "period_end", "share_count", "share_factor"]]

# %% [markdown]
# ## Rebalance Dates and Constituents

# %%
dates = rebalance_dates(panel["date"], FREQUENCY)
constituents = constituents_on(panel, dates)
constituents.groupby("date").size().rename("constituents").reset_index()

# %% [markdown]
# ## Filing history
#
# Each filing the Panel carries, once. The data's earliest Filing Date is 2016-09-30, so a 12-month
# Lookback first finds a comparison filing in late 2017.

# %%
filings = filing_history(panel)
filings

# %% [markdown]
# ## Percentage Shares Issued

# %%
signal = pct_shares_issued(
    constituents,
    filings,
    events,
    lookback_months=LOOKBACK_MONTHS,
    tolerance_days=TOLERANCE_DAYS,
    max_filing_age_days=MAX_FILING_AGE_DAYS,
    exclude_stale=EXCLUDE_STALE,
)
check_signal(signal)
signal

# %% [markdown]
# ## Review tables
#
# ### Ranked Constituents per Rebalance Date

# %%
signal.groupby("date").agg(
    constituents=("ticker", "size"),
    ranked=("pct_shares_issued_rank", "count"),
    median=("pct_shares_issued", "median"),
    with_event=("corporate_event_in_lookback", "sum"),
).reset_index()

# %% [markdown]
# ### Constituents with no comparison filing
#
# The rows the warnings above name. Through 2017-09-29 the data holds no filing one Lookback back
# for nearly every Constituent. After that, they are mostly spin-offs and newly formed Companies in
# their first year, and late filers.

# %%
signal[signal["missing_reason"] == "no_comparison"].groupby("date")["ticker"].agg(
    count="size", tickers=lambda tickers: ", ".join(sorted(tickers))
).reset_index()

# %% [markdown]
# ### Constituents with no value

# %%
signal[signal["missing_reason"].notna()][
    ["date", "ticker", "missing_reason", "filing_age_days"]
].sort_values(["missing_reason", "date", "ticker"])

# %% [markdown]
# ### Biggest buybacks and issuers on the last Rebalance Date

# %%
last = signal[signal["date"] == signal["date"].max()].dropna(subset=["pct_shares_issued"])
ordered = last.sort_values("pct_shares_issued_rank")
pd.concat([ordered.head(10), ordered.tail(10)])

# %% [markdown]
# ### Ranks as a Rebalance Date × Company matrix

# %%
signal.pivot(index="date", columns="ticker", values="pct_shares_issued_rank")

# %% [markdown]
# ## Save
#
# Set `SAVE = True` and run `.venv/bin/python research/pct_issuance.py`. Outputs for a date that
# already has them are never overwritten.

# %%
if SAVE:
    print(write_signal(signal, PROCESSED_DIR, PANEL_AS_OF))
