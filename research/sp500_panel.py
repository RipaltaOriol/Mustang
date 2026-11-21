# %% [markdown]
# # S&P 500 Panel
#
# Builds the Panel and the Corporate Events step by step. Each cell shows the frame it made.
#
# When you use the Panel:
# - Rows cover each Ever-member's full history. Filter on `in_sp500` to form the universe, or the
#   analysis has look-ahead bias.
# - Rows with zero volume stay in the Panel. Treat their prices as untradable.
# - `close_split_adjusted` pairs with `share_count`, `close_with_dividends` gives total returns, and
#   `close_unadjusted` is the price actually traded.

# %%
import pandas as pd

from src.panel import (
    PANEL_START,
    PROCESSED_DIR,
    SECONDARY_TO_PRIMARY,
    check_panel,
    company_periods,
    corporate_events,
    daily_valuations,
    data_as_of,
    finish_panel,
    load_inputs,
    member_actions,
    member_filings,
    member_prices,
    member_securities,
    prices_in_window,
    share_counts,
    with_company_fields,
    with_constituent_flag,
    with_exits,
    with_share_counts,
    with_valuations,
    write_outputs,
)
from src.providers import SharadarProvider

# %%
START = PANEL_START
JUMP_THRESHOLD = 0.25
SAVE = False

# %% [markdown]
# ## Inputs
#
# Loading reads the local snapshots and needs `SHARADAR_API_KEY`. Run this cell once per session.

# %%
provider = SharadarProvider.from_env()
inputs = load_inputs(provider, START)
inputs.sp500

# %% [markdown]
# ## Ever-members

# %%
periods = company_periods(inputs.sp500)
ever_members = set(periods["ticker"])
periods

# %%
securities = member_securities(inputs.securities, ever_members)
securities

# %% [markdown]
# ## Prices and valuations

# %%
valuations = daily_valuations(inputs.daily)
valuations

# %%
prices = member_prices(inputs.prices, ever_members)
window = prices_in_window(prices, valuations, ever_members, START)
window

# %% [markdown]
# ## Share Counts
#
# Effective Dates come from the full price history, because a filing can land before `START`.

# %%
filings = member_filings(inputs.filings, ever_members)
counts = share_counts(filings, prices["date"])
counts

# %% [markdown]
# ## The Panel

# %%
joined = with_share_counts(window, counts)
joined = with_valuations(joined, valuations)
joined = with_company_fields(joined, securities)
joined = with_constituent_flag(joined, periods)
joined

# %%
actions = member_actions(inputs.actions, ever_members)
panel = finish_panel(with_exits(joined, securities, actions))
check_panel(panel)
panel

# %%
panel[panel["exit_date"].notna()][["date", "ticker", "name", "exit_date", "exit_reason"]]

# %% [markdown]
# ## Corporate Events

# %%
events = corporate_events(actions, securities)
events

# %% [markdown]
# ## Review tables

# %%
pd.Series(
    {
        "rows": len(panel),
        "companies": panel["permaticker"].nunique(),
        "first_date": panel["date"].min().date(),
        "last_date": panel["date"].max().date(),
        "constituent_rows": int(panel["in_sp500"].sum()),
        "exits": int(panel["exit_date"].notna().sum()),
    },
    name="value",
)

# %% [markdown]
# ### Removed Secondary Classes
#
# `snapshots_without_primary` counts the dated lists holding the Secondary Class but not its
# Primary Class.

# %%
snapshots = inputs.sp500[inputs.sp500["action"].isin(("historical", "current"))]
latest_filing = filings.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
classes = []
for secondary, primary in sorted(SECONDARY_TO_PRIMARY.items()):
    held = set(snapshots.loc[snapshots["ticker"] == secondary, "date"])
    if held:
        primary_held = set(snapshots.loc[snapshots["ticker"] == primary, "date"])
        classes.append(
            {
                "removed_class": secondary,
                "primary_class": primary,
                "latest_share_count": latest_filing["sharesbas"].get(primary),
                "share_factor": latest_filing["sharefactor"].get(primary),
                "snapshots_without_primary": len(held - primary_held),
            }
        )
pd.DataFrame(classes)

# %% [markdown]
# ### Share factors other than 1

# %%
filings[filings["sharefactor"] != 1].groupby("ticker")["sharefactor"].agg(
    ["min", "max", "count"]
).reset_index()

# %% [markdown]
# ### Share Count jumps between filings

# %%
ordered = filings.sort_values(["ticker", "date", "reportperiod"])
change = ordered.groupby("ticker")["sharesbas"].pct_change()
ordered.assign(change=change)[change.abs() > JUMP_THRESHOLD][
    ["ticker", "date", "reportperiod", "sharesbas", "change"]
].sort_values("change", key=abs, ascending=False)

# %% [markdown]
# ### Rows with zero volume

# %%
panel[panel["volume"] == 0].groupby("ticker").size().rename("zero_volume_rows").sort_values(
    ascending=False
).reset_index()

# %% [markdown]
# ### Rows with no Share Count

# %%
panel[panel["share_count"].isna()].groupby("ticker").size().rename("rows").sort_values(
    ascending=False
).reset_index()

# %% [markdown]
# ## Save
#
# Set `SAVE = True` and run `.venv/bin/python research/sp500_panel.py`. Outputs for a date that
# already has them are never overwritten.

# %%
if SAVE:
    print(write_outputs(panel, events, PROCESSED_DIR, data_as_of(provider)))
