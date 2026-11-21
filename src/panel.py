"""
The steps that build the Panel of S&P 500 Ever-members and its Corporate Events.

See: research/sp500_panel.py
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.providers import SharadarProvider

PANEL_START = "2016-12-31"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

# Verified against Sharadar's tickers table; these classes carry no filing data of their own.
SECONDARY_TO_PRIMARY: Mapping[str, str] = {
    "DISCK": "WBD",
    "FOX": "FOXA",
    "GOOG": "GOOGL",
    "NWS": "NWSA",
    "TFCFA": "TFCF",
    "UA": "UAA",
}

_DAILY_FIELDS = ("marketcap", "ev", "pb", "pe", "ps", "evebitda")
_FILING_FIELDS = (
    "reportperiod",
    "sharesbas",
    "sharefactor",
    "revenue",
    "netinc",
    "fcf",
    "debt",
    "equity",
    "divyield",
    "ncfcommon",
    "sbcomp",
)
_PRICE_FIELDS: Mapping[str, str] = {
    "close": "close",
    "closeunadj": "close_unadjusted",
    "closeadj": "close_with_dividends",
    "volume": "volume",
}
_SNAPSHOT_TABLES = ("sp500", "stocks", "daily", "fundamentals", "actions")
_USD_PER_MILLION = 1_000_000
_EXIT_ACTION_WINDOW = pd.Timedelta(days=5)
_EVENT_ACTIONS = frozenset({"split", "spinoff", "spinoffdividend", "spunofffrom", "mergerfrom", "mergerto"})
_EVENT_ACTION_PREFIX = "acquisition"

PANEL_COLUMNS = (
    "date",
    "permaticker",
    "ticker",
    "name",
    "figi",
    "exchange",
    "sector",
    "industry",
    "fama_industry",
    "in_sp500",
    "close_split_adjusted",
    "close_unadjusted",
    "close_with_dividends",
    "volume",
    "market_cap_usd",
    "ev_usd",
    "pb",
    "pe",
    "ps",
    "evebitda",
    "filed_date",
    "effective_date",
    "period_end",
    "share_count",
    "share_factor",
    "revenue",
    "netinc",
    "fcf",
    "debt",
    "equity",
    "divyield",
    "ncfcommon",
    "sbcomp",
    "exit_date",
    "exit_reason",
)


class PanelCheckError(Exception):
    """
    The Panel broke a rule that makes it wrong rather than merely worth reviewing.
    """


@dataclass(frozen=True)
class PanelInputs:
    sp500: pd.DataFrame
    securities: pd.DataFrame
    prices: pd.DataFrame
    daily: pd.DataFrame
    filings: pd.DataFrame
    actions: pd.DataFrame


def load_inputs(provider: SharadarProvider, start: str = PANEL_START) -> PanelInputs:
    """
    Fetch everything the Panel needs for the Ever-members of the S&P 500.
    """
    sp500 = provider.fetch_table("sp500")
    tickers = sorted(set(company_periods(sp500)["ticker"]))
    return PanelInputs(
        sp500=sp500,
        securities=provider.securities(),
        prices=provider.fetch_snapshot(
            "stocks", tickers=tickers, fields=tuple(_PRICE_FIELDS)
        ).rename(columns=_PRICE_FIELDS),
        daily=provider.fetch_table("daily", start=start, tickers=tickers, fields=_DAILY_FIELDS),
        filings=provider.fetch_snapshot(
            "fundamentals", tickers=tickers, fields=_FILING_FIELDS, filters={"dimension": "ARQ"}
        ),
        actions=provider.fetch_table(
            "actions",
            start=start,
            tickers=tickers,
            fields=("action", "value", "contraticker", "contraname"),
        ),
    )


def data_as_of(provider: SharadarProvider) -> date:
    """
    Return the date of the oldest snapshot, which names the outputs built from those snapshots.
    """
    return min(taken for table in _SNAPSHOT_TABLES if (taken := provider.snapshot_date(table)))


def company_periods(sp500: pd.DataFrame) -> pd.DataFrame:
    """
    Return each Company's periods as a Constituent, with Secondary Classes folded into the Primary Class.

    Raises:
        PanelCheckError: the additions and removals do not replay to a dated list of Constituents.
    """
    periods = _membership_periods(sp500)
    periods["ticker"] = periods["ticker"].replace(SECONDARY_TO_PRIMARY)
    return periods


def member_securities(securities: pd.DataFrame, ever_members: set[str]) -> pd.DataFrame:
    """
    Return the company records of the Ever-members.

    Raises:
        PanelCheckError: an Ever-member has no company record.
    """
    members = securities[securities["ticker"].isin(ever_members)]
    _require_all(ever_members, set(members["ticker"]), "no company record")
    return members


def member_prices(prices: pd.DataFrame, ever_members: set[str]) -> pd.DataFrame:
    dated = _with_dates(prices, "date")
    return dated[dated["ticker"].isin(ever_members)]


def prices_in_window(
    prices: pd.DataFrame, valuations: pd.DataFrame, ever_members: set[str], start: str = PANEL_START
) -> pd.DataFrame:
    """
    Return the prices from the start through the last date with valuations.

    Raises:
        PanelCheckError: an Ever-member has no prices in the window.
    """
    # Stocks and daily update at different hours, so prices can run past the last valuations.
    inside = (prices["date"] >= pd.Timestamp(start)) & (prices["date"] <= valuations["date"].max())
    window = prices[inside]
    _require_all(ever_members, set(window["ticker"]), "no prices")
    return window


def member_filings(filings: pd.DataFrame, ever_members: set[str]) -> pd.DataFrame:
    """
    Return the filings of the Ever-members.

    Raises:
        PanelCheckError: an Ever-member has no filings.
    """
    dated = _with_dates(filings, "date", "reportperiod")
    members = dated[dated["ticker"].isin(ever_members)]
    _require_all(ever_members, set(members["ticker"]), "no filings")
    return members


def member_actions(actions: pd.DataFrame, ever_members: set[str]) -> pd.DataFrame:
    dated = _with_dates(actions, "date")
    return dated[dated["ticker"].isin(ever_members)]


def with_share_counts(prices: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    return pd.merge_asof(
        prices.sort_values("date"),
        counts,
        left_on="date",
        right_on="effective_date",
        by="ticker",
    )


def with_valuations(panel: pd.DataFrame, valuations: pd.DataFrame) -> pd.DataFrame:
    return panel.merge(valuations, on=["ticker", "date"], how="left")


def with_company_fields(panel: pd.DataFrame, securities: pd.DataFrame) -> pd.DataFrame:
    return panel.merge(
        securities.rename(columns={"security_id": "permaticker"})[
            ["ticker", "permaticker", "name", "figi", "exchange", "sector", "industry", "fama_industry"]
        ],
        on="ticker",
    )


def with_constituent_flag(panel: pd.DataFrame, periods: pd.DataFrame) -> pd.DataFrame:
    return panel.assign(in_sp500=_in_sp500(panel, periods))


def finish_panel(panel: pd.DataFrame) -> pd.DataFrame:
    named = panel.rename(columns={"close": "close_split_adjusted"})
    return named.sort_values(["date", "ticker"]).reset_index(drop=True)[list(PANEL_COLUMNS)]


def check_panel(panel: pd.DataFrame) -> None:
    """
    Enforce the row rules on an assembled Panel.

    Raises:
        PanelCheckError: the columns differ from PANEL_COLUMNS, a Company has two rows on one date,
            or a Share Count precedes its Effective Date.
    """
    if tuple(panel.columns) != PANEL_COLUMNS:
        difference = sorted(set(panel.columns) ^ set(PANEL_COLUMNS))
        raise PanelCheckError(f"The columns differ from PANEL_COLUMNS: {difference}.")
    duplicated = panel.duplicated(["permaticker", "date"])
    if duplicated.any():
        raise PanelCheckError(f"{duplicated.sum()} rows are two rows for one Company on one date.")
    early = panel["effective_date"] > panel["date"]
    not_after_filing = panel["effective_date"] <= panel["filed_date"]
    if early.any() or not_after_filing.any():
        raise PanelCheckError(
            f"{early.sum() + not_after_filing.sum()} Share Counts are used before its Effective Date."
        )


def write_outputs(
    panel: pd.DataFrame, events: pd.DataFrame, directory: Path | str, as_of: date | str
) -> list[Path]:
    """
    Write the Panel and Corporate Events, each named for the date of the data they came from.

    Raises:
        FileExistsError: an output for this date exists, and outputs are never overwritten.
    """
    root = Path(directory)
    panel_path = root / f"sp500_panel_{as_of}.parquet"
    events_path = root / f"sp500_events_{as_of}.parquet"
    paths = [panel_path, events_path]
    existing = [path.name for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite {existing}.")

    root.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_path, index=False)
    events.to_parquet(events_path, index=False)
    return paths


def _membership_periods(sp500: pd.DataFrame) -> pd.DataFrame:
    rows = _with_dates(sp500, "date")
    snapshots = rows[rows["action"].isin(("historical", "current"))]
    first = snapshots["date"].min()
    expected = {day: set(group["ticker"]) for day, group in snapshots.groupby("date")}
    changes = rows[rows["action"].isin(("added", "removed")) & (rows["date"] > first)]
    changes_by_day = {day: group for day, group in changes.groupby("date", sort=False)}

    open_since = {ticker: first for ticker in expected[first]}
    closed = []
    for day in sorted(set(expected) | set(changes_by_day)):
        for change in changes_by_day.get(day, changes.iloc[0:0]).itertuples():
            if change.action == "added":
                open_since.setdefault(change.ticker, day)
            elif change.ticker in open_since:
                closed.append((change.ticker, open_since.pop(change.ticker), day))
        if day in expected and set(open_since) != expected[day]:
            difference = sorted(set(open_since) ^ expected[day])
            raise PanelCheckError(f"Membership does not replay to the {day.date()} list: {difference}.")

    closed += [(ticker, since, pd.Timestamp.max) for ticker, since in open_since.items()]
    return pd.DataFrame(closed, columns=["ticker", "start", "end"])


def _in_sp500(panel: pd.DataFrame, periods: pd.DataFrame) -> pd.Series:
    keys = panel[["ticker", "date"]].reset_index()
    joined = keys.merge(periods, on="ticker")
    inside = joined[(joined["date"] >= joined["start"]) & (joined["date"] < joined["end"])]
    flag = pd.Series(False, index=panel.index)
    flag.loc[inside["index"].unique()] = True
    return flag


def share_counts(
    filings: pd.DataFrame, trading_days: pd.Series, keep_refilings: bool = False
) -> pd.DataFrame:
    """
    Return each Share Count with its Effective Date, dropping Re-filings unless keep_refilings is set.

    See: docs/adr/0001-a-refiled-quarter-keeps-the-first-share-count.md
    """
    if not keep_refilings:
        filings = filings.sort_values(["ticker", "date"], kind="stable").drop_duplicates(
            ["ticker", "reportperiod"], keep="first"
        )
    calendar = np.sort(trading_days.unique())
    positions = np.searchsorted(calendar, filings["date"].to_numpy(), side="right")
    reachable = positions < len(calendar)

    counts = filings[reachable].assign(effective_date=calendar[positions[reachable]])
    counts = counts.sort_values(["ticker", "date", "reportperiod"])
    counts = counts.drop_duplicates(["ticker", "effective_date"], keep="last")
    counts = counts.rename(
        columns={
            "date": "filed_date",
            "reportperiod": "period_end",
            "sharesbas": "share_count",
            "sharefactor": "share_factor",
        }
    )
    return counts.drop(columns="dimension", errors="ignore").sort_values("effective_date")


def daily_valuations(daily: pd.DataFrame) -> pd.DataFrame:
    frame = _with_dates(daily, "date")
    frame["market_cap_usd"] = frame["marketcap"] * _USD_PER_MILLION
    frame["ev_usd"] = frame["ev"] * _USD_PER_MILLION
    return frame[["ticker", "date", "market_cap_usd", "ev_usd", "pb", "pe", "ps", "evebitda"]]


def with_exits(
    panel: pd.DataFrame, securities: pd.DataFrame, actions: pd.DataFrame
) -> pd.DataFrame:
    delisted = securities.loc[securities["is_delisted"], "ticker"]
    last_rows = panel.sort_values("date").groupby("ticker").tail(1)
    last_rows = last_rows[last_rows["ticker"].isin(delisted)]

    # Exit fields sit on the last row only, so earlier rows cannot leak the Company's fate.
    panel = panel.assign(exit_date=pd.NaT, exit_reason=None)
    panel["exit_date"] = panel["exit_date"].astype("datetime64[ns]")
    panel["exit_reason"] = panel["exit_reason"].astype(object)
    for row in last_rows[["ticker", "date"]].itertuples():
        exit_date, reason = _exit_of(row.ticker, row.date, actions)
        panel.loc[(panel["ticker"] == row.ticker) & (panel["date"] == row.date), ["exit_date", "exit_reason"]] = [
            exit_date,
            reason,
        ]
    return panel


def _exit_of(ticker: str, last_price: pd.Timestamp, actions: pd.DataFrame) -> tuple[pd.Timestamp, str]:
    own = actions[actions["ticker"] == ticker]
    delistings = own.loc[own["action"] == "delisted", "date"]
    exit_date = delistings.max() if not delistings.empty else last_price
    nearby = own[(own["date"] - exit_date).abs() <= _EXIT_ACTION_WINDOW]["action"]
    if (nearby == "bankruptcyliquidation").any():
        return exit_date, "bankrupt"
    if nearby.isin(("acquisitionby", "mergerto")).any():
        return exit_date, "acquired"
    return exit_date, "other"


def corporate_events(actions: pd.DataFrame, securities: pd.DataFrame) -> pd.DataFrame:
    wanted = actions["action"].isin(_EVENT_ACTIONS) | actions["action"].str.startswith(
        _EVENT_ACTION_PREFIX
    )
    identifiers = securities.rename(columns={"security_id": "permaticker"})[["ticker", "permaticker"]]
    events = actions[wanted].merge(identifiers, on="ticker")
    events = events.rename(columns={"contraticker": "contra_ticker", "contraname": "contra_name"})
    columns = ["date", "permaticker", "ticker", "action", "value", "contra_ticker", "contra_name"]
    return events.sort_values(["date", "ticker"]).reset_index(drop=True)[columns]


def _with_dates(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    converted = {
        column: pd.to_datetime(frame[column]).astype("datetime64[ns]") for column in columns
    }
    return frame.assign(**converted)


def _require_all(required: set[str], present: set[str], problem: str) -> None:
    missing = sorted(required - present)
    if missing:
        raise PanelCheckError(f"Ever-members with {problem}: {missing}.")
