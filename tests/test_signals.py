import logging

import pandas as pd
import pytest

from src.signals import (
    SIGNAL_COLUMNS,
    SignalCheckError,
    check_signal,
    constituents_on,
    filing_history,
    pct_shares_issued,
    rebalance_dates,
    write_signal,
)

REBALANCE = "2020-12-31"
EVENT_COLUMNS = ["date", "permaticker", "ticker", "action", "value", "contra_ticker", "contra_name"]


def filing(ticker, period_end, shares, filed=None, factor=1.0):
    filed = pd.Timestamp(filed or pd.Timestamp(period_end) + pd.Timedelta(days=30))
    return {
        "ticker": ticker,
        "filed_date": filed,
        "effective_date": filed + pd.Timedelta(days=1),
        "period_end": pd.Timestamp(period_end),
        "share_count": float(shares),
        "share_factor": factor,
    }


def yearly(ticker, earlier, later, factor=1.0):
    return [
        filing(ticker, "2019-09-30", earlier, factor=factor),
        filing(ticker, "2020-09-30", later, factor=factor),
    ]


def members(*tickers, on=REBALANCE):
    return pd.DataFrame(
        {
            "date": pd.Timestamp(on),
            "permaticker": range(1, len(tickers) + 1),
            "ticker": list(tickers),
        }
    )


def event(ticker, day, action):
    return {
        "date": pd.Timestamp(day),
        "permaticker": 1,
        "ticker": ticker,
        "action": action,
        "value": 1.0,
        "contra_ticker": None,
        "contra_name": None,
    }


def events_of(rows=()):
    return pd.DataFrame(list(rows), columns=EVENT_COLUMNS)


def signal(constituents, filings, events=(), **parameters):
    return pct_shares_issued(constituents, pd.DataFrame(filings), events_of(events), **parameters)


def row(table, ticker):
    return table.set_index("ticker").loc[ticker]


def test_rebalance_dates_are_the_last_trading_day_of_each_completed_quarter():
    trading_days = pd.Series(
        pd.to_datetime(["2020-03-30", "2020-03-31", "2020-06-29", "2020-06-30", "2020-07-01", "2020-08-14"])
    )

    assert rebalance_dates(trading_days).strftime("%Y-%m-%d").tolist() == ["2020-03-31", "2020-06-30"]


def test_rebalance_dates_follow_the_frequency_asked_for():
    trading_days = pd.Series(pd.to_datetime(["2020-01-30", "2020-01-31", "2020-02-27", "2020-02-28", "2020-03-02"]))

    assert rebalance_dates(trading_days, frequency="M").strftime("%Y-%m-%d").tolist() == [
        "2020-01-31",
        "2020-02-28",
    ]


def test_a_quarter_whose_last_calendar_day_has_passed_is_complete():
    trading_days = pd.Series(pd.to_datetime(["2020-09-29", "2020-09-30"]))

    assert rebalance_dates(trading_days).strftime("%Y-%m-%d").tolist() == ["2020-09-30"]


def test_constituents_are_the_index_members_on_each_rebalance_date():
    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-03-31", "2020-03-31", "2020-04-01", "2020-06-30"]),
            "permaticker": [1, 2, 1, 1],
            "ticker": ["AAA", "BBB", "AAA", "AAA"],
            "in_sp500": [True, False, True, True],
        }
    )

    picked = constituents_on(panel, pd.DatetimeIndex(["2020-03-31", "2020-06-30"]))

    assert list(zip(picked["date"].dt.strftime("%Y-%m-%d"), picked["ticker"])) == [
        ("2020-03-31", "AAA"),
        ("2020-06-30", "AAA"),
    ]


def test_the_filing_history_holds_each_filing_once():
    panel = pd.DataFrame(
        [
            {"date": pd.Timestamp("2020-01-02"), **filing("AAA", "2019-09-30", 100, filed="2019-11-01")},
            {"date": pd.Timestamp("2020-01-03"), **filing("AAA", "2019-09-30", 100, filed="2019-11-01")},
            {"date": pd.Timestamp("2020-01-03"), **filing("BBB", "2019-09-30", 50, filed="2019-11-01")},
            {"date": pd.Timestamp("2020-01-03"), "ticker": "CCC"},
        ]
    )

    history = filing_history(panel)

    assert history["ticker"].tolist() == ["AAA", "BBB"]


def test_the_change_compares_the_latest_filing_with_the_one_a_lookback_earlier():
    table = signal(members("AAA"), [filing("AAA", "2020-06-30", 104), *yearly("AAA", 100, 90)])

    assert row(table, "AAA")["net_shares_issued"] == -10
    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(-0.10)


def test_the_change_uses_the_company_share_count():
    filings = [filing("AAA", "2019-09-30", 100, factor=1.0), filing("AAA", "2020-09-30", 100, factor=1.5)]

    table = signal(members("AAA"), filings)

    assert row(table, "AAA")["net_shares_issued"] == 50
    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.5)


def test_the_lookback_can_be_a_quarter():
    filings = [filing("AAA", "2020-06-30", 80), *yearly("AAA", 100, 88)]

    table = signal(members("AAA"), filings, lookback_months=3)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)


def test_a_period_end_a_few_days_off_still_matches():
    filings = [filing("AAA", "2019-09-28", 100), filing("AAA", "2020-10-03", 110)]

    table = signal(members("AAA"), filings)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)


def test_a_period_end_outside_the_tolerance_has_no_comparison(caplog):
    filings = [filing("AAA", "2019-08-01", 100), filing("AAA", "2020-09-30", 110)]

    with caplog.at_level(logging.WARNING):
        table = signal(members("AAA"), filings, tolerance_days=40)

    assert pd.isna(row(table, "AAA")["pct_shares_issued"])
    assert row(table, "AAA")["missing_reason"] == "no_comparison"
    assert "2020-12-31" in caplog.text and "AAA" in caplog.text


def test_the_tolerance_can_be_widened():
    filings = [filing("AAA", "2019-08-01", 100), filing("AAA", "2020-09-30", 110)]

    table = signal(members("AAA"), filings, tolerance_days=70)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)


def test_a_refiled_comparison_quarter_keeps_the_first_share_count():
    filings = [
        filing("AAA", "2019-09-30", 100, filed="2019-11-01"),
        filing("AAA", "2019-09-30", 500, filed="2019-12-01"),
        filing("AAA", "2020-09-30", 110, filed="2020-11-01"),
    ]

    table = signal(members("AAA"), filings)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)


def test_a_filing_not_yet_effective_on_the_rebalance_date_is_not_used():
    filings = [*yearly("AAA", 100, 110), filing("AAA", "2019-12-31", 50, filed="2021-01-15"), filing("AAA", "2020-12-31", 200, filed="2021-01-15")]

    table = signal(members("AAA"), filings)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)


def test_the_filing_age_counts_days_from_the_latest_period_end():
    table = signal(members("AAA"), yearly("AAA", 100, 110))

    assert row(table, "AAA")["filing_age_days"] == 92


def test_a_stale_filing_leaves_the_company_unranked():
    filings = [filing("AAA", "2019-03-31", 100), filing("AAA", "2020-03-31", 110)]

    table = signal(members("AAA"), filings, max_filing_age_days=200)

    assert pd.isna(row(table, "AAA")["pct_shares_issued"])
    assert pd.isna(row(table, "AAA")["pct_shares_issued_rank"])
    assert row(table, "AAA")["missing_reason"] == "stale"
    assert row(table, "AAA")["filing_age_days"] == 275


def test_a_stale_filing_is_ranked_when_stale_filings_are_kept():
    filings = [filing("AAA", "2019-03-31", 100), filing("AAA", "2020-03-31", 110)]

    table = signal(members("AAA"), filings, exclude_stale=False)

    assert row(table, "AAA")["pct_shares_issued"] == pytest.approx(0.10)
    assert pd.isna(row(table, "AAA")["missing_reason"])


def test_a_constituent_with_no_share_count_is_kept_unranked():
    table = signal(members("AAA", "BBB"), yearly("AAA", 100, 110))

    assert row(table, "BBB")["missing_reason"] == "no_share_count"
    assert pd.isna(row(table, "BBB")["pct_shares_issued_rank"])
    assert pd.isna(row(table, "BBB")["filing_age_days"])


def test_a_change_across_a_scope_break_is_dropped():
    filings = [filing("AAA", "2019-09-30", 100, filed="2019-11-01"), filing("AAA", "2020-09-30", 200, filed="2020-11-01")]

    table = signal(members("AAA"), filings, scope_breaks={"AAA": (pd.Timestamp("2020-05-08"),)})

    assert pd.isna(row(table, "AAA")["pct_shares_issued"])
    assert row(table, "AAA")["missing_reason"] == "scope_break"


@pytest.mark.parametrize(
    ("day", "action", "flagged"),
    [
        ("2020-07-01", "mergerfrom", True),
        ("2020-07-01", "acquisitionby", True),
        ("2020-07-01", "spinoff", True),
        ("2020-07-01", "split", False),
        ("2019-10-15", "mergerfrom", False),
        ("2020-11-15", "mergerfrom", False),
    ],
)
def test_a_corporate_event_between_the_two_filing_dates_is_flagged(day, action, flagged):
    table = signal(members("AAA"), yearly("AAA", 100, 300), events=[event("AAA", day, action)])

    assert row(table, "AAA")["corporate_event_in_lookback"] == flagged


def test_another_companys_event_is_not_flagged():
    table = signal(members("AAA"), yearly("AAA", 100, 110), events=[event("BBB", "2020-07-01", "mergerfrom")])

    assert not row(table, "AAA")["corporate_event_in_lookback"]


def test_ranks_run_from_the_biggest_buyback_to_the_biggest_issuer():
    filings = [*yearly("AAA", 100, 90), *yearly("BBB", 100, 100), *yearly("CCC", 100, 120)]

    table = signal(members("AAA", "BBB", "CCC", "DDD"), filings)

    assert table.set_index("ticker")["pct_shares_issued_rank"].dropna().to_dict() == {
        "AAA": 0.0,
        "BBB": 0.5,
        "CCC": 1.0,
    }


def test_tied_companies_share_their_average_rank():
    filings = [*yearly("AAA", 100, 90), *yearly("BBB", 100, 110), *yearly("CCC", 100, 110)]

    table = signal(members("AAA", "BBB", "CCC"), filings)

    assert table.set_index("ticker")["pct_shares_issued_rank"].to_dict() == {"AAA": 0.0, "BBB": 0.75, "CCC": 0.75}


def test_each_rebalance_date_is_ranked_on_its_own():
    filings = [*yearly("AAA", 100, 90), *yearly("BBB", 100, 120)]
    constituents = pd.concat([members("AAA", "BBB"), members("BBB", on="2021-01-29")], ignore_index=True)

    table = signal(constituents, filings)

    assert table["pct_shares_issued_rank"].tolist() == [0.0, 1.0, 0.5]


def test_the_signal_table_passes_its_check():
    table = signal(members("AAA", "BBB"), yearly("AAA", 100, 110))

    assert tuple(table.columns) == SIGNAL_COLUMNS
    check_signal(table)


def test_two_rows_for_one_company_on_one_date_fail_the_check():
    table = signal(members("AAA"), yearly("AAA", 100, 110))

    with pytest.raises(SignalCheckError):
        check_signal(pd.concat([table, table], ignore_index=True))


def test_a_value_with_a_missing_reason_fails_the_check():
    table = signal(members("AAA"), yearly("AAA", 100, 110))
    table["missing_reason"] = "stale"

    with pytest.raises(SignalCheckError):
        check_signal(table)


def test_a_rank_outside_zero_to_one_fails_the_check():
    table = signal(members("AAA"), yearly("AAA", 100, 110))
    table["pct_shares_issued_rank"] = 1.5

    with pytest.raises(SignalCheckError):
        check_signal(table)


def test_the_signal_is_never_overwritten(tmp_path):
    table = signal(members("AAA"), yearly("AAA", 100, 110))

    path = write_signal(table, tmp_path, "2020-12-31")

    assert path.name == "sp500_pct_issuance_2020-12-31.parquet"
    with pytest.raises(FileExistsError):
        write_signal(table, tmp_path, "2020-12-31")
