import pandas as pd
import pytest

from src.panel import (
    PANEL_COLUMNS,
    PanelCheckError,
    check_panel,
    company_periods,
    corporate_events,
    daily_valuations,
    finish_panel,
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
from src.providers.base import SECURITY_COLUMNS

START = "2020-01-01"
TRADING_DAYS = ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08"]
ACTION_COLUMNS = ["ticker", "date", "action", "value", "contraticker", "contraname"]


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


def prices_of(ticker="AAA", on=TRADING_DAYS):
    return member_prices(pd.DataFrame([price(ticker, day) for day in on]), {ticker})


def actions_of(rows=()):
    return member_actions(pd.DataFrame(list(rows), columns=ACTION_COLUMNS), {"AAA"})


def counted(filings, prices=None, keep_refilings=False):
    prices = prices_of() if prices is None else prices
    counts = share_counts(
        member_filings(pd.DataFrame(filings), {"AAA"}), prices["date"], keep_refilings=keep_refilings
    )
    return with_share_counts(prices, counts).sort_values("date")


def finished_panel():
    rows = pd.DataFrame({column: None for column in PANEL_COLUMNS}, index=range(len(TRADING_DAYS)))
    rows["date"] = pd.to_datetime(TRADING_DAYS)
    rows["permaticker"] = 1
    rows["filed_date"] = pd.Timestamp("2019-11-01")
    rows["effective_date"] = pd.Timestamp("2019-11-04")
    return rows


def days(series):
    return series.dt.strftime("%Y-%m-%d").tolist()


def test_an_ever_member_keeps_rows_outside_its_membership_with_the_flag_off():
    periods = company_periods(
        member_rows(
            first=("AAA", "OUT"),
            last=("AAA", "NEW"),
            events=[("2020-01-06", "removed", "OUT"), ("2020-01-06", "added", "NEW")],
        )
    )

    assert with_constituent_flag(prices_of("OUT"), periods)["in_sp500"].tolist() == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert with_constituent_flag(prices_of("NEW"), periods)["in_sp500"].tolist() == [
        False,
        False,
        True,
        True,
        True,
    ]


def test_a_company_that_never_joined_inside_the_window_is_not_an_ever_member():
    periods = company_periods(
        pd.concat([member_rows(), member_rows(events=[("2019-06-03", "removed", "GONE")])])
    )

    assert set(periods["ticker"]) == {"AAA"}


def test_membership_that_does_not_replay_to_a_snapshot_fails():
    with pytest.raises(PanelCheckError, match="NEW"):
        company_periods(member_rows(first=("AAA",), last=("AAA", "NEW")))


def test_a_secondary_class_folds_into_its_primary_class_company():
    periods = company_periods(
        member_rows(
            first=("GOOG",), last=("GOOGL", "GOOG"), events=[("2020-01-06", "added", "GOOGL")]
        )
    )

    assert set(periods["ticker"]) == {"GOOGL"}
    assert with_constituent_flag(prices_of("GOOGL"), periods)["in_sp500"].all()


def test_a_symbol_with_no_company_mapping_fails():
    with pytest.raises(PanelCheckError, match="XXX"):
        member_securities(pd.DataFrame([security("AAA", 1)]), {"AAA", "XXX"})


def test_a_share_count_is_used_from_the_first_trading_day_after_its_filing_date():
    rows = counted(
        [filing("AAA", "2019-11-01", shares=100), filing("AAA", "2020-01-03", shares=200)]
    )

    assert rows["share_count"].tolist() == [100, 100, 200, 200, 200]
    assert days(rows["effective_date"])[2] == "2020-01-06"
    assert days(rows["filed_date"])[2] == "2020-01-03"


def test_filings_landing_on_one_effective_date_resolve_to_the_latest():
    rows = counted(
        [
            filing("AAA", "2020-01-03", shares=100, period_end="2019-06-30"),
            filing("AAA", "2020-01-04", shares=200, period_end="2019-09-30"),
        ]
    )

    assert rows["share_count"].tolist()[2:] == [200, 200, 200]


REFILED_QUARTER = [
    filing("AAA", "2019-11-01", shares=100, period_end="2019-09-30"),
    filing("AAA", "2020-01-03", shares=500, period_end="2019-09-30"),
]


def test_a_refiled_quarter_keeps_the_first_share_count_by_default():
    rows = counted(REFILED_QUARTER)

    assert rows["share_count"].tolist() == [100] * len(TRADING_DAYS)
    assert set(days(rows["filed_date"])) == {"2019-11-01"}


def test_a_refiled_quarter_replaces_the_first_share_count_when_asked():
    rows = counted(REFILED_QUARTER, keep_refilings=True)

    assert rows["share_count"].tolist() == [100, 100, 500, 500, 500]
    assert days(rows["effective_date"])[2] == "2020-01-06"


def test_dropping_a_refiled_quarter_keeps_a_later_quarter_in_force():
    rows = counted(
        [
            filing("AAA", "2019-08-01", shares=100, period_end="2019-06-30"),
            filing("AAA", "2019-11-01", shares=200, period_end="2019-09-30"),
            filing("AAA", "2020-01-03", shares=900, period_end="2019-06-30"),
        ]
    )

    assert rows["share_count"].tolist() == [200] * len(TRADING_DAYS)


def test_rows_before_a_companys_first_filing_have_no_share_count():
    rows = counted([filing("AAA", "2020-01-06")])

    assert rows["share_count"].isna().tolist() == [True, True, True, False, False]


def test_rows_before_the_start_are_dropped_but_older_filings_carry_forward():
    prices = prices_of(on=["2019-12-31", *TRADING_DAYS])
    valuations = daily_valuations(pd.DataFrame([valuation("AAA", day) for day in TRADING_DAYS]))

    window = prices_in_window(prices, valuations, {"AAA"}, START)
    rows = counted([filing("AAA", "2019-11-01")], window)

    assert days(rows["date"]) == TRADING_DAYS
    assert rows["share_count"].notna().all()


def test_a_filing_before_the_start_gets_its_real_effective_date():
    prices = prices_of(on=["2019-12-30", "2019-12-31", *TRADING_DAYS])
    valuations = daily_valuations(pd.DataFrame([valuation("AAA", day) for day in TRADING_DAYS]))
    counts = share_counts(
        member_filings(pd.DataFrame([filing("AAA", "2019-12-30")]), {"AAA"}), prices["date"]
    )

    rows = with_share_counts(prices_in_window(prices, valuations, {"AAA"}, START), counts)

    assert days(rows["effective_date"])[0] == "2019-12-31"


def test_the_panel_ends_on_the_last_date_with_valuations():
    valuations = daily_valuations(
        pd.DataFrame([valuation("AAA", day) for day in TRADING_DAYS[:-1]])
    )

    window = prices_in_window(prices_of(), valuations, {"AAA"}, START)
    rows = with_valuations(window, valuations)

    assert days(rows["date"]) == TRADING_DAYS[:-1]
    assert rows["market_cap_usd"].notna().all()


def test_valuations_are_in_usd():
    row = daily_valuations(pd.DataFrame([valuation("AAA", TRADING_DAYS[0])])).iloc[0]

    assert row["market_cap_usd"] == 2_500_000.0
    assert row["ev_usd"] == 3_500_000.0


def test_company_fields_name_the_permaticker():
    rows = with_company_fields(prices_of(), pd.DataFrame([security("AAA", 1)]))

    assert rows["permaticker"].tolist() == [1] * len(TRADING_DAYS)
    assert rows["figi"].iloc[0] == "BBGAAA"


def test_a_finished_panel_names_the_split_adjusted_close_and_orders_its_rows():
    rows = finished_panel().drop(columns="close_split_adjusted")
    rows["close"] = 10.0
    rows["ticker"] = "AAA"

    panel = finish_panel(rows.iloc[::-1])

    assert tuple(panel.columns) == PANEL_COLUMNS
    assert panel["close_split_adjusted"].tolist() == [10.0] * len(TRADING_DAYS)
    assert days(panel["date"]) == TRADING_DAYS
    assert panel.index.tolist() == list(range(len(TRADING_DAYS)))


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
    rows = with_exits(
        prices_of(on=TRADING_DAYS[:3]),
        pd.DataFrame([security("AAA", 1, delisted=True, last_price="2020-01-06")]),
        actions_of(action("AAA", day, kind) for day, kind in actions),
    ).sort_values("date")

    assert rows["exit_reason"].isna().tolist() == [True, True, False]
    assert rows["exit_reason"].iloc[-1] == reason
    assert days(rows["exit_date"].iloc[[-1]]) == ["2020-01-06"]


def test_a_company_still_listed_has_no_exit():
    rows = with_exits(prices_of(), pd.DataFrame([security("AAA", 1)]), actions_of())

    assert rows["exit_date"].isna().all()
    assert rows["exit_reason"].isna().all()


def test_zero_volume_rows_stay_in_the_panel():
    prices = member_prices(
        pd.DataFrame([price("AAA", day, volume=0.0) for day in TRADING_DAYS]), {"AAA"}
    )
    valuations = daily_valuations(pd.DataFrame([valuation("AAA", day) for day in TRADING_DAYS]))

    assert len(prices_in_window(prices, valuations, {"AAA"}, START)) == len(TRADING_DAYS)


def test_the_events_table_holds_only_corporate_events_for_ever_members():
    actions = actions_of(
        [
            action("AAA", "2020-01-03", "split", 2.0),
            action("AAA", "2020-01-03", "acquisitionof"),
            action("AAA", "2020-01-03", "spinoff"),
            action("AAA", "2020-01-03", "dividend"),
            action("ZZZ", "2020-01-03", "split"),
        ]
    )

    events = corporate_events(actions, pd.DataFrame([security("AAA", 1)]))

    assert sorted(events["action"]) == ["acquisitionof", "spinoff", "split"]
    assert set(events["permaticker"]) == {1}


def test_an_ever_member_without_prices_in_the_window_fails():
    valuations = daily_valuations(pd.DataFrame([valuation("AAA", day) for day in TRADING_DAYS]))
    prices = pd.concat([prices_of(), prices_of("BBB", on=["2019-12-31"])])

    with pytest.raises(PanelCheckError, match="no prices.*BBB"):
        prices_in_window(prices, valuations, {"AAA", "BBB"}, START)


def test_an_ever_member_without_filings_fails():
    with pytest.raises(PanelCheckError, match="no filings.*AAA"):
        member_filings(pd.DataFrame([filing("ZZZ", "2019-11-01")]), {"AAA"})


def test_a_correct_panel_passes_the_check():
    check_panel(finished_panel())


def test_two_rows_for_one_company_on_one_date_fail_the_check():
    panel = finished_panel()

    with pytest.raises(PanelCheckError, match="two rows"):
        check_panel(pd.concat([panel, panel.iloc[[0]]]))


def test_a_share_count_before_its_effective_date_fails_the_check():
    panel = finished_panel()
    panel["effective_date"] = pd.Timestamp("2020-01-03")

    with pytest.raises(PanelCheckError, match="before its Effective Date"):
        check_panel(panel)


def test_a_share_count_effective_by_its_filing_date_fails_the_check():
    panel = finished_panel()
    panel["effective_date"] = panel["filed_date"]

    with pytest.raises(PanelCheckError, match="before its Effective Date"):
        check_panel(panel)


def test_a_panel_missing_a_column_fails_the_check():
    with pytest.raises(PanelCheckError, match="in_sp500"):
        check_panel(finished_panel().drop(columns="in_sp500"))


def test_outputs_are_never_overwritten(tmp_path):
    panel = finished_panel()
    events = pd.DataFrame({"action": ["split"]})

    paths = write_outputs(panel, events, tmp_path, "2026-11-06")
    assert sorted(path.name for path in paths) == [
        "sp500_events_2026-11-06.parquet",
        "sp500_panel_2026-11-06.parquet",
    ]

    before = paths[0].read_bytes()
    with pytest.raises(FileExistsError):
        write_outputs(panel, events, tmp_path, "2026-11-06")
    assert paths[0].read_bytes() == before
