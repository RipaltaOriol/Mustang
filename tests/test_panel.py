import re

import pandas as pd
import pytest

from src.panel import PanelCheckError, PanelInputs, build_panel, check_panel, write_outputs
from src.providers.base import SECURITY_COLUMNS

START = "2020-01-01"
TRADING_DAYS = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]


def security(ticker, permaticker, delisted=False, last_price="2020-01-08"):
    values = {
        "security_id": permaticker,
        "ticker": ticker,
        "name": f"{ticker} INC",
        "exchange": "NYSE",
        "is_delisted": delisted,
        "category": "Domestic Common Stock",
        "figi": f"BBG{ticker}",
        "fama_industry": "Software",
        "sector": "Technology",
        "industry": "Software",
        "currency": "USD",
        "first_price_date": "2010-01-04",
        "last_price_date": last_price,
    }
    return {column: values[column] for column in SECURITY_COLUMNS}


def price(ticker, day, close=10.0, volume=100.0):
    return {
        "ticker": ticker,
        "date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "close_unadjusted": close * 2,
        "close_with_dividends": close * 0.9,
        "volume": volume,
    }


def filing(ticker, filed, shares=1_000, period_end=None, factor=1.0):
    return {
        "ticker": ticker,
        "date": filed,
        "reportperiod": period_end or filed,
        "sharesbas": shares,
        "sharefactor": factor,
        "revenue": 5.0,
        "netinc": 1.0,
        "fcf": 2.0,
        "debt": 3.0,
        "equity": 4.0,
        "divyield": 0.01,
        "ncfcommon": -7.0,
        "sbcomp": 6.0,
    }


def valuation(ticker, day, marketcap=2.5, ev=3.5):
    return {
        "ticker": ticker,
        "date": day,
        "marketcap": marketcap,
        "ev": ev,
        "pb": 1.0,
        "pe": 2.0,
        "ps": 3.0,
        "evebitda": 4.0,
    }


def member_rows(first=("AAA",), last=("AAA",), events=()):
    rows = [{"date": START, "action": "historical", "ticker": ticker} for ticker in first]
    rows += [{"date": "2020-01-08", "action": "current", "ticker": ticker} for ticker in last]
    rows += [{"date": day, "action": action, "ticker": ticker} for day, action, ticker in events]
    return pd.DataFrame(rows)


def action(ticker, day, kind, value=1.0):
    return {
        "ticker": ticker,
        "date": day,
        "action": kind,
        "value": value,
        "contraticker": "N/A",
        "contraname": "N/A",
    }


def make_inputs(sp500=None, securities=None, prices=None, daily=None, filings=None, actions=None):
    def frame(rows, columns):
        return pd.DataFrame(rows, columns=columns)

    action_columns = ["ticker", "date", "action", "value", "contraticker", "contraname"]
    return PanelInputs(
        sp500=member_rows() if sp500 is None else sp500,
        securities=pd.DataFrame(securities or [security("AAA", 1)]),
        prices=pd.DataFrame(prices or [price("AAA", day) for day in TRADING_DAYS]),
        daily=pd.DataFrame(daily or [valuation("AAA", day) for day in TRADING_DAYS]),
        filings=pd.DataFrame(filings or [filing("AAA", "2019-11-01")]),
        actions=frame(actions or [], action_columns),
    )


def rows_for(panel, ticker):
    return panel[panel["ticker"] == ticker].sort_values("date")


def days(series):
    return series.dt.strftime("%Y-%m-%d").tolist()


def test_an_ever_member_keeps_rows_outside_its_membership_with_the_flag_off():
    inputs = make_inputs(
        sp500=member_rows(
            first=("AAA", "OUT"),
            last=("AAA", "NEW"),
            events=[("2020-01-06", "removed", "OUT"), ("2020-01-06", "added", "NEW")],
        ),
        securities=[security("AAA", 1), security("OUT", 2), security("NEW", 3)],
        prices=[price(ticker, day) for ticker in ("AAA", "OUT", "NEW") for day in TRADING_DAYS],
        filings=[filing(ticker, "2019-11-01") for ticker in ("AAA", "OUT", "NEW")],
    )

    panel = build_panel(inputs, start=START).panel

    assert rows_for(panel, "OUT")["in_sp500"].tolist() == [True, True, False, False, False]
    assert rows_for(panel, "NEW")["in_sp500"].tolist() == [False, False, True, True, True]


def test_a_company_that_never_joined_inside_the_window_is_not_an_ever_member():
    inputs = make_inputs(
        sp500=pd.concat([member_rows(), member_rows(events=[("2019-06-03", "removed", "GONE")])]),
        securities=[security("AAA", 1), security("GONE", 2)],
        prices=[price("AAA", day) for day in TRADING_DAYS],
    )

    panel = build_panel(inputs, start=START).panel

    assert set(panel["ticker"]) == {"AAA"}


def test_membership_that_does_not_replay_to_a_snapshot_fails_the_build():
    inputs = make_inputs(sp500=member_rows(first=("AAA",), last=("AAA", "NEW")))

    with pytest.raises(PanelCheckError, match="NEW"):
        build_panel(inputs, start=START)


def test_a_secondary_class_folds_into_its_primary_class_company():
    inputs = make_inputs(
        sp500=member_rows(first=("GOOG",), last=("GOOGL", "GOOG"),
                          events=[("2020-01-06", "added", "GOOGL")]),
        securities=[security("GOOGL", 1)],
        prices=[price("GOOGL", day) for day in TRADING_DAYS],
        filings=[filing("GOOGL", "2019-11-01")],
        daily=[valuation("GOOGL", day) for day in TRADING_DAYS],
    )

    panel = build_panel(inputs, start=START).panel

    assert set(panel["ticker"]) == {"GOOGL"}
    assert panel["in_sp500"].all()


def test_a_symbol_with_no_company_mapping_fails_the_build():
    inputs = make_inputs(sp500=member_rows(first=("AAA", "XXX"), last=("AAA", "XXX")))

    with pytest.raises(PanelCheckError, match="XXX"):
        build_panel(inputs, start=START)


def test_a_share_count_is_used_from_the_first_trading_day_after_its_filing_date():
    inputs = make_inputs(
        filings=[filing("AAA", "2019-11-01", shares=100), filing("AAA", "2020-01-03", shares=200)]
    )

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert rows["share_count"].tolist() == [100, 100, 200, 200, 200]
    assert days(rows["effective_date"])[2] == "2020-01-06"
    assert days(rows["filed_date"])[2] == "2020-01-03"


def test_filings_landing_on_one_effective_date_resolve_to_the_latest():
    inputs = make_inputs(
        filings=[
            filing("AAA", "2020-01-03", shares=100, period_end="2019-06-30"),
            filing("AAA", "2020-01-04", shares=200, period_end="2019-09-30"),
        ]
    )

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert rows["share_count"].tolist()[2:] == [200, 200, 200]


def test_rows_before_a_companys_first_filing_have_no_share_count():
    inputs = make_inputs(filings=[filing("AAA", "2020-01-06")])

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert rows["share_count"].isna().tolist() == [True, True, True, False, False]


def test_rows_before_the_start_are_dropped_but_older_filings_carry_forward():
    inputs = make_inputs(
        prices=[price("AAA", "2019-12-31")] + [price("AAA", day) for day in TRADING_DAYS]
    )

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert days(rows["date"]) == TRADING_DAYS
    assert rows["share_count"].notna().all()


def test_a_filing_before_the_start_gets_its_real_effective_date():
    inputs = make_inputs(
        prices=[price("AAA", "2019-12-30"), price("AAA", "2019-12-31")]
        + [price("AAA", day) for day in TRADING_DAYS],
        filings=[filing("AAA", "2019-12-30")],
    )

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert days(rows["effective_date"])[0] == "2019-12-31"


def test_the_panel_ends_on_the_last_date_with_valuations():
    inputs = make_inputs(daily=[valuation("AAA", day) for day in TRADING_DAYS[:-1]])

    panel = build_panel(inputs, start=START).panel

    assert days(panel["date"]) == TRADING_DAYS[:-1]
    assert panel["market_cap_usd"].notna().all()


def test_the_report_counts_snapshots_where_a_secondary_class_lacked_its_primary_class():
    inputs = make_inputs(
        sp500=member_rows(
            first=("GOOG",), last=("GOOGL", "GOOG"), events=[("2020-01-06", "added", "GOOGL")]
        ),
        securities=[security("GOOGL", 1)],
        prices=[price("GOOGL", day) for day in TRADING_DAYS],
        daily=[valuation("GOOGL", day) for day in TRADING_DAYS],
        filings=[filing("GOOGL", "2019-11-01")],
    )

    report = build_panel(inputs, start=START).report

    assert "snapshots_without_primary" in report
    assert re.search(r"GOOG\s+GOOGL\s+1000\s+1\.0\s+1\n", report)


def test_panel_prices_name_the_split_adjusted_close_and_valuations_are_in_usd():
    panel = build_panel(make_inputs(), start=START).panel
    row = panel.iloc[0]

    assert "close" not in panel.columns
    assert row["close_split_adjusted"] == 10.0
    assert row["close_unadjusted"] == 20.0
    assert row["close_with_dividends"] == 9.0
    assert row["market_cap_usd"] == 2_500_000.0
    assert row["ev_usd"] == 3_500_000.0
    assert row["permaticker"] == 1
    assert row["figi"] == "BBGAAA"


@pytest.mark.parametrize(
    "actions, reason",
    [
        ([("2020-01-06", "delisted"), ("2020-01-07", "acquisitionby")], "acquired"),
        ([("2020-01-06", "delisted"), ("2020-01-06", "bankruptcyliquidation")], "bankrupt"),
        ([("2020-01-06", "delisted")], "other"),
        ([("2020-01-06", "delisted"), ("2020-01-02", "acquisitionby")], "acquired"),
        ([("2020-01-06", "delisted"), ("2020-02-20", "acquisitionby")], "other"),
        ([("2020-01-06", "delisted"), ("2020-01-06", "mergerto")], "acquired"),
    ],
)
def test_the_exit_is_recorded_only_on_the_last_row(actions, reason):
    inputs = make_inputs(
        securities=[security("AAA", 1, delisted=True, last_price="2020-01-06")],
        prices=[price("AAA", day) for day in TRADING_DAYS[:3]],
        actions=[action("AAA", day, kind) for day, kind in actions],
    )

    rows = rows_for(build_panel(inputs, start=START).panel, "AAA")

    assert rows["exit_reason"].isna().tolist() == [True, True, False]
    assert rows["exit_reason"].iloc[-1] == reason
    assert days(rows["exit_date"].iloc[[-1]]) == ["2020-01-06"]


def test_a_company_still_listed_has_no_exit():
    panel = build_panel(make_inputs(), start=START).panel

    assert panel["exit_date"].isna().all()
    assert panel["exit_reason"].isna().all()


def test_zero_volume_rows_stay_in_the_panel_and_are_reported():
    inputs = make_inputs(prices=[price("AAA", day, volume=0.0) for day in TRADING_DAYS])

    build = build_panel(inputs, start=START)

    assert len(build.panel) == len(TRADING_DAYS)
    assert "AAA" in build.report.split("## Stale prices")[1]


def test_the_events_table_holds_only_corporate_events_for_ever_members():
    inputs = make_inputs(
        actions=[
            action("AAA", "2020-01-03", "split", 2.0),
            action("AAA", "2020-01-03", "acquisitionof"),
            action("AAA", "2020-01-03", "spinoff"),
            action("AAA", "2020-01-03", "dividend"),
            action("ZZZ", "2020-01-03", "split"),
        ]
    )

    events = build_panel(inputs, start=START).events

    assert sorted(events["action"]) == ["acquisitionof", "spinoff", "split"]
    assert set(events["permaticker"]) == {1}


def test_an_ever_member_without_prices_fails_the_build():
    inputs = make_inputs(
        sp500=member_rows(first=("AAA", "BBB"), last=("AAA", "BBB")),
        securities=[security("AAA", 1), security("BBB", 2)],
    )

    with pytest.raises(PanelCheckError, match="no prices.*BBB"):
        build_panel(inputs, start=START)


def test_an_ever_member_without_filings_fails_the_build():
    inputs = make_inputs(filings=[filing("ZZZ", "2019-11-01")])

    with pytest.raises(PanelCheckError, match="no filings.*AAA"):
        build_panel(inputs, start=START)


def test_two_rows_for_one_company_on_one_date_fail_the_check():
    panel = build_panel(make_inputs(), start=START).panel

    with pytest.raises(PanelCheckError, match="two rows"):
        check_panel(pd.concat([panel, panel.iloc[[0]]]))


def test_a_share_count_before_its_effective_date_fails_the_check():
    panel = build_panel(make_inputs(), start=START).panel.copy()
    panel["effective_date"] = pd.Timestamp("2020-01-03")

    with pytest.raises(PanelCheckError, match="before its Effective Date"):
        check_panel(panel)


def test_the_report_surfaces_share_factors_jumps_and_removed_classes_without_changing_rows():
    inputs = make_inputs(
        sp500=member_rows(first=("GOOGL", "GOOG"), last=("GOOGL", "GOOG")),
        securities=[security("GOOGL", 1)],
        prices=[price("GOOGL", day) for day in TRADING_DAYS],
        daily=[valuation("GOOGL", day) for day in TRADING_DAYS],
        filings=[
            filing("GOOGL", "2019-08-01", shares=100, factor=1.5),
            filing("GOOGL", "2019-11-01", shares=300, factor=1.5),
        ],
    )

    build = build_panel(inputs, start=START)

    assert "GOOG" in build.report.split("## Removed Secondary Classes")[1]
    assert "1.5" in build.report.split("## Share factors other than 1")[1]
    assert "GOOGL" in build.report.split("## Share Count jumps")[1]
    assert build.panel["share_count"].unique().tolist() == [300]


def test_outputs_are_never_overwritten(tmp_path):
    build = build_panel(make_inputs(), start=START)

    paths = write_outputs(build, tmp_path, "2026-11-06")
    assert sorted(path.name for path in paths) == [
        "sp500_events_2026-11-06.parquet",
        "sp500_panel_2026-11-06.parquet",
        "sp500_report_2026-11-06.md",
    ]

    before = paths[0].read_bytes()
    with pytest.raises(FileExistsError):
        write_outputs(build, tmp_path, "2026-11-06")
    assert paths[0].read_bytes() == before
