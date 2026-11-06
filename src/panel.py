"""
Build the Panel of S&P 500 Ever-members, with its corporate events and build report.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.providers import SharadarProvider

logger = logging.getLogger(__name__)

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
_SNAPSHOT_TABLES = ("sp500", "stocks", "daily", "fundamentals", "actions")
_USD_PER_MILLION = 1_000_000
_EXIT_ACTION_WINDOW = pd.Timedelta(days=5)
_JUMP_THRESHOLD = 0.25
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


@dataclass(frozen=True)
class PanelBuild:
    panel: pd.DataFrame
    events: pd.DataFrame
    report: str


def load_inputs(provider: SharadarProvider, start: str = PANEL_START) -> PanelInputs:
    """
    Fetch everything the Panel needs for the Ever-members of the S&P 500.
    """
    sp500 = provider.fetch_table("sp500")
    tickers = sorted(set(_company_periods(sp500)["ticker"]))
    return PanelInputs(
        sp500=sp500,
        securities=provider.securities(),
        prices=provider.prices(start=start, tickers=tickers),
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


def build_panel(inputs: PanelInputs, start: str = PANEL_START) -> PanelBuild:
    """
    Assemble and check the Panel, the events table and the report from the raw inputs.

    Raises:
        PanelCheckError: membership, coverage or row rules failed.
    """
    periods = _company_periods(inputs.sp500)
    members = set(periods["ticker"])
    securities = inputs.securities[inputs.securities["ticker"].isin(members)]
    _require_all(members, set(securities["ticker"]), "no company record")

    begin = pd.Timestamp(start)
    prices = _with_dates(inputs.prices, "date")
    prices = prices[prices["ticker"].isin(members) & (prices["date"] >= begin)]
    _require_all(members, set(prices["ticker"]), "no prices")

    filings = _with_dates(inputs.filings, "date", "reportperiod")
    filings = filings[filings["ticker"].isin(members)]
    _require_all(members, set(filings["ticker"]), "no filings")

    actions = _with_dates(inputs.actions, "date")
    actions = actions[actions["ticker"].isin(members)]

    counts = _share_counts(filings, prices["date"])
    panel = pd.merge_asof(
        prices.sort_values("date"),
        counts,
        left_on="date",
        right_on="effective_date",
        by="ticker",
    )
    panel = panel.merge(_valuations(inputs.daily), on=["ticker", "date"], how="left")
    panel = panel.merge(
        securities.rename(columns={"security_id": "permaticker"})[
            ["ticker", "permaticker", "name", "figi", "exchange", "sector", "industry", "fama_industry"]
        ],
        on="ticker",
    )
    panel["in_sp500"] = _in_sp500(panel, periods)
    panel = panel.rename(columns={"close": "close_split_adjusted"})
    panel = _with_exits(panel, securities, actions)
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)[list(PANEL_COLUMNS)]

    check_panel(panel)
    return PanelBuild(
        panel=panel,
        events=_events(actions, securities),
        report=_report(panel, filings, _removed_classes(inputs.sp500)),
    )


def check_panel(panel: pd.DataFrame) -> None:
    """
    Enforce the row rules on an assembled Panel.

    Raises:
        PanelCheckError: a Company has two rows on one date, or a Share Count precedes its Effective Date.
    """
    duplicated = panel.duplicated(["permaticker", "date"])
    if duplicated.any():
        raise PanelCheckError(f"{duplicated.sum()} rows are two rows for one Company on one date.")
    early = panel["effective_date"] > panel["date"]
    same_day = panel["effective_date"] <= panel["filed_date"]
    if early.any() or same_day.any():
        raise PanelCheckError(
            f"{early.sum() + same_day.sum()} Share Counts are used before its Effective Date."
        )


def write_outputs(build: PanelBuild, directory: Path | str, as_of: date | str) -> list[Path]:
    """
    Write the Panel, events and report, each named for the date of the data they came from.

    Raises:
        FileExistsError: an output for this date exists, and outputs are never overwritten.
    """
    root = Path(directory)
    panel_path = root / f"sp500_panel_{as_of}.parquet"
    events_path = root / f"sp500_events_{as_of}.parquet"
    report_path = root / f"sp500_report_{as_of}.md"
    paths = [panel_path, events_path, report_path]
    existing = [path.name for path in paths if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to overwrite {existing}.")

    root.mkdir(parents=True, exist_ok=True)
    build.panel.to_parquet(panel_path, index=False)
    build.events.to_parquet(events_path, index=False)
    report_path.write_text(build.report)
    return paths


def _company_periods(sp500: pd.DataFrame) -> pd.DataFrame:
    periods = _membership_periods(sp500)
    periods["ticker"] = periods["ticker"].replace(SECONDARY_TO_PRIMARY)
    return periods


def _removed_classes(sp500: pd.DataFrame) -> dict[str, str]:
    held = set(_membership_periods(sp500)["ticker"])
    return {
        secondary: primary
        for secondary, primary in SECONDARY_TO_PRIMARY.items()
        if secondary in held
    }


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


def _share_counts(filings: pd.DataFrame, trading_days: pd.Series) -> pd.DataFrame:
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


def _valuations(daily: pd.DataFrame) -> pd.DataFrame:
    frame = _with_dates(daily, "date")
    frame["market_cap_usd"] = frame["marketcap"] * _USD_PER_MILLION
    frame["ev_usd"] = frame["ev"] * _USD_PER_MILLION
    return frame[["ticker", "date", "market_cap_usd", "ev_usd", "pb", "pe", "ps", "evebitda"]]


def _with_exits(
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
    if (nearby == "acquisitionby").any():
        return exit_date, "acquired"
    return exit_date, "other"


def _events(actions: pd.DataFrame, securities: pd.DataFrame) -> pd.DataFrame:
    wanted = actions["action"].isin(_EVENT_ACTIONS) | actions["action"].str.startswith(
        _EVENT_ACTION_PREFIX
    )
    identifiers = securities.rename(columns={"security_id": "permaticker"})[["ticker", "permaticker"]]
    events = actions[wanted].merge(identifiers, on="ticker")
    events = events.rename(columns={"contraticker": "contra_ticker", "contraname": "contra_name"})
    columns = ["date", "permaticker", "ticker", "action", "value", "contra_ticker", "contra_name"]
    return events.sort_values(["date", "ticker"]).reset_index(drop=True)[columns]


def _report(panel: pd.DataFrame, filings: pd.DataFrame, removed: Mapping[str, str]) -> str:
    latest = filings.sort_values("date").groupby("ticker").tail(1).set_index("ticker")
    classes = pd.DataFrame(
        [
            {
                "removed_class": secondary,
                "primary_class": primary,
                "latest_share_count": latest["sharesbas"].get(primary),
                "share_factor": latest["sharefactor"].get(primary),
            }
            for secondary, primary in sorted(removed.items())
        ],
        columns=["removed_class", "primary_class", "latest_share_count", "share_factor"],
    )

    factors = filings[filings["sharefactor"] != 1]
    factor_summary = factors.groupby("ticker")["sharefactor"].agg(["min", "max", "count"]).reset_index()

    ordered = filings.sort_values(["ticker", "date", "reportperiod"])
    change = ordered.groupby("ticker")["sharesbas"].pct_change()
    jumps = ordered.assign(change=change)[change.abs() > _JUMP_THRESHOLD]
    jumps = jumps[["ticker", "date", "reportperiod", "sharesbas", "change"]].sort_values(
        "change", key=abs, ascending=False
    )

    stale = panel[panel["volume"] == 0].groupby("ticker").size().rename("zero_volume_rows")
    stale = stale.sort_values(ascending=False).reset_index()

    uncounted = panel[panel["share_count"].isna()].groupby("ticker").size().rename("rows")
    uncounted = uncounted.sort_values(ascending=False).reset_index()

    summary = pd.DataFrame(
        {
            "value": {
                "rows": len(panel),
                "companies": panel["permaticker"].nunique(),
                "first_date": panel["date"].min().date(),
                "last_date": panel["date"].max().date(),
                "constituent_rows": int(panel["in_sp500"].sum()),
                "exits": int(panel["exit_date"].notna().sum()),
            }
        }
    )
    sections = [
        ("Summary", summary.reset_index(names="item")),
        ("Removed Secondary Classes", classes),
        ("Share factors other than 1", factor_summary),
        (f"Share Count jumps above {_JUMP_THRESHOLD:.0%} between filings", jumps),
        ("Stale prices (zero volume rows)", stale),
        ("Rows with no Share Count", uncounted),
    ]
    return "# S&P 500 Panel build report\n\n" + "\n\n".join(
        f"## {title}\n\n```\n{frame.to_string(index=False)}\n```" for title, frame in sections
    ) + "\n"


def _with_dates(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    converted = {
        column: pd.to_datetime(frame[column]).astype("datetime64[ns]") for column in columns
    }
    return frame.assign(**converted)


def _require_all(required: set[str], present: set[str], problem: str) -> None:
    missing = sorted(required - present)
    if missing:
        raise PanelCheckError(f"Ever-members with {problem}: {missing}.")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    provider = SharadarProvider.from_env()
    inputs = load_inputs(provider)
    as_of = min(taken for table in _SNAPSHOT_TABLES if (taken := provider.snapshot_date(table)))
    for path in write_outputs(build_panel(inputs), PROCESSED_DIR, as_of):
        logger.info("Wrote %s", path)


if __name__ == "__main__":
    main()
