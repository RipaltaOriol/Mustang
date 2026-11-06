import io
import os
import re
import time
import zipfile
from datetime import date, timedelta

import pandas as pd
import pytest
import requests

from src.providers import InsufficientHistoryError, NotEntitledError, SharadarProvider
from src.providers import base, sharadar
from src.providers.base import DataProviderError

API_KEY = "secret-key"
SIGNED_URL = "https://bulk.example/file.zip?signature=abc"
SCHEMAS = {
    "fundamentals": {
        "ticker": "text",
        "dimension": "text",
        "date": "date",
        "reportperiod": "date",
        "sharesbas": "bigint",
        "sharefactor": "double precision",
    },
    "daily": {"ticker": "text", "date": "date", "marketcap": "double precision"},
    "stocks": {
        "ticker": "text",
        "date": "date",
        "open": "double precision",
        "high": "double precision",
        "low": "double precision",
        "close": "double precision",
        "closeunadj": "double precision",
        "closeadj": "double precision",
        "volume": "double precision",
    },
    "tickers": {
        "table": "text",
        "permaticker": "bigint",
        "ticker": "text",
        "name": "text",
        "exchange": "text",
        "isdelisted": "text",
        "category": "text",
        "figi": "text",
        "famaindustry": "text",
        "sector": "text",
        "industry": "text",
        "currency": "text",
        "firstpricedate": "date",
        "lastpricedate": "date",
    },
}


class FakeResponse:
    def __init__(self, status_code=200, text="", headers=None, content=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = text.encode() if content is None else content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, chunk_size):
        yield self.content


class FakeSharadar:
    """
    An in-memory stand-in for the Sharadar HTTP surface, including its row limit and tiers.
    """

    def __init__(self, tables, tiers=None):
        self.tables = {name: pd.DataFrame(rows) for name, rows in tables.items()}
        self.tiers = tiers if tiers is not None else {name: "10" for name in tables}
        self.calls = []
        self.scripted = []

    def get(self, url, params=None, headers=None, **_):
        self.calls.append({"url": url, "params": dict(params or {}), "headers": headers or {}})
        if url == SIGNED_URL:
            return FakeResponse(content=self._bulk_zip())
        if self.scripted:
            return self.scripted.pop(0)

        kind, table = re.search(r"/(data|schema)/(\w+)$", url).groups()
        if kind == "schema":
            return FakeResponse(text=self._schema_text(table))
        if "years" in params:
            return self._bulk_redirect(table, params["years"])
        ticker_param = params.get("ticker", "")
        if len(ticker_param) > 200 or len(ticker_param.split(",")) > 30:
            return FakeResponse(400, text='{"error":"Too many tickers"}')
        return FakeResponse(text=self._query(table, params).to_csv(index=False))

    def data_calls(self, table=None):
        return [
            call
            for call in self.calls
            if "/data/" in call["url"]
            and "years" not in call["params"]
            and (table is None or call["url"].endswith(f"/{table}"))
        ]

    def download_calls(self):
        return [call for call in self.calls if call["url"] == SIGNED_URL]

    def _bulk_redirect(self, table, years):
        order = ["5", "10", "full"]
        held = self.tiers.get(table)
        if held is not None and order.index(years) <= order.index(held):
            self.bulk_table = table
            return FakeResponse(302, headers={"Location": SIGNED_URL})
        return FakeResponse(403, text='{"error":"Forbidden"}')

    def _bulk_zip(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("data.csv", self.tables[self.bulk_table].to_csv(index=False))
        return buffer.getvalue()

    def _query(self, table, params):
        rows = self.tables[table]
        if "ticker" in params:
            rows = rows[rows["ticker"].isin(params["ticker"].split(","))]
        for column in rows.columns:
            if column in params and column != "ticker":
                rows = rows[rows[column] == params[column]]
        if "from" in params:
            rows = rows[(rows["date"] >= params["from"]) & (rows["date"] <= params["to"])]
        rows = rows.sort_values(params["sort"].split(".")[0], kind="stable").head(params["limit"])
        return rows[params["fields"].split(",")] if "fields" in params else rows

    @staticmethod
    def _schema_text(table):
        lines = ",\n".join(f'  "{name}" {kind}' for name, kind in SCHEMAS[table].items())
        return f"-- comment\nCREATE TABLE {table} (\n{lines},\n  PRIMARY KEY (ticker)\n);\n"


def recent(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


def filing(ticker, filed, shares=100, dimension="ARQ"):
    return {
        "ticker": ticker,
        "dimension": dimension,
        "date": filed,
        "reportperiod": filed,
        "sharesbas": shares,
        "sharefactor": 1.0,
    }


def make_provider(tmp_path, tables, tiers=None):
    fake = FakeSharadar(tables, tiers)
    return SharadarProvider(API_KEY, tmp_path, session=fake), fake


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(sharadar.time, "sleep", lambda _: None)


def test_paging_by_date_returns_every_row_once_when_a_date_straddles_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(sharadar, "_PAGE_LIMIT", 3)
    rows = [filing(f"T{i}", recent(30)) for i in range(2)]
    rows += [filing(f"U{i}", recent(20)) for i in range(2)]
    rows += [filing(f"V{i}", recent(10)) for i in range(2)]
    provider, fake = make_provider(tmp_path, {"fundamentals": rows})

    result = provider.shares_outstanding(start=recent(40), end=recent(0))

    assert sorted(result["ticker"]) == ["T0", "T1", "U0", "U1", "V0", "V1"]
    assert all("skip" not in call["params"] for call in fake.data_calls())
    assert len(fake.data_calls()) > 1


def test_a_full_page_on_one_date_fails_instead_of_truncating(tmp_path, monkeypatch):
    monkeypatch.setattr(sharadar, "_PAGE_LIMIT", 2)
    rows = [filing(f"T{i}", recent(5)) for i in range(3)]
    provider, _ = make_provider(tmp_path, {"fundamentals": rows})

    with pytest.raises(DataProviderError, match="narrow the request"):
        provider.shares_outstanding(start=recent(10), end=recent(0))


@pytest.mark.parametrize("ticker_format", ["T{:02d}", "LONGNAME{:03d}"])
def test_ticker_lists_are_batched_under_both_request_caps(tmp_path, ticker_format):
    tickers = [ticker_format.format(i) for i in range(70)]
    rows = [filing(ticker, recent(5)) for ticker in tickers]
    provider, fake = make_provider(tmp_path, {"fundamentals": rows})

    result = provider.shares_outstanding(start=recent(3000), tickers=tickers)

    assert sorted(result["ticker"]) == sorted(tickers)
    assert len(fake.data_calls()) > 1


def test_the_real_ticker_na_is_not_read_as_missing(tmp_path):
    provider, _ = make_provider(tmp_path, {"fundamentals": [filing("NA", recent(5))]})

    result = provider.shares_outstanding(start=recent(10), tickers=["NA"])

    assert result["ticker"].tolist() == ["NA"]


def test_a_start_before_the_subscription_history_is_rejected(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})

    with pytest.raises(InsufficientHistoryError, match="available from"):
        provider.shares_outstanding(start=recent(365 * 25), tickers=["AAA"])

    assert fake.data_calls() == []


def test_no_start_requests_all_history_the_tier_allows(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})

    provider.shares_outstanding(tickers=["AAA"])

    expected = (pd.Timestamp(date.today()) - pd.DateOffset(years=10)).date()
    assert fake.data_calls()[0]["params"]["from"] == expected.isoformat()
    assert provider.earliest_date("shares_outstanding") == expected


def test_a_full_history_tier_reaches_beyond_ten_years(tmp_path):
    provider, _ = make_provider(
        tmp_path,
        {"fundamentals": [filing("AAA", "2001-05-01")]},
        tiers={"fundamentals": "full"},
    )

    result = provider.shares_outstanding(start="2001-01-01", tickers=["AAA"])

    assert len(result) == 1


def test_an_unentitled_table_fails_before_any_free_tier_data_is_returned(tmp_path):
    prices = [{"ticker": "MSFT", "date": recent(5), "close": 1.0}]
    provider, fake = make_provider(tmp_path, {"stocks": prices}, tiers={})

    with pytest.raises(NotEntitledError, match="does not include stocks"):
        provider.prices(tickers=["MSFT"])

    assert fake.data_calls() == []


def test_narrow_requests_use_rest_and_never_download(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})

    provider.shares_outstanding(tickers=["AAA"])
    provider.shares_outstanding(start=recent(30), end=recent(0))

    assert fake.download_calls() == []


def test_broad_requests_download_one_snapshot_and_reuse_it(tmp_path):
    rows = [
        filing("AAA", recent(800), shares=1),
        filing("BBB", recent(400), shares=2),
        filing("BBB", recent(400), shares=99, dimension="MRQ"),
        filing("CCC", recent(5000), shares=3),
    ]
    provider, fake = make_provider(tmp_path, {"fundamentals": rows})

    first = provider.shares_outstanding(start=recent(1000), end=recent(0))
    second = provider.shares_outstanding(start=recent(500), end=recent(0))

    assert first["shares_outstanding"].tolist() == [1, 2]
    assert second["shares_outstanding"].tolist() == [2]
    assert len(fake.download_calls()) == 1
    assert fake.data_calls("fundamentals") == []


def test_the_api_key_goes_only_in_the_header_and_never_to_the_bulk_host(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(800))]})

    provider.shares_outstanding(end=recent(0))

    download = fake.download_calls()[0]
    assert API_KEY not in str(download["headers"])
    api_calls = [call for call in fake.calls if call["url"] != SIGNED_URL]
    assert all(call["headers"]["x-api-key"] == API_KEY for call in api_calls)
    assert all(API_KEY not in str(call["params"]) for call in fake.calls)


def test_a_failed_refresh_keeps_the_existing_snapshot_and_hides_the_signed_url(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(800))]})
    path = provider.refresh_snapshot("fundamentals")
    before = path.read_bytes()

    original_get = fake.get

    def failing_get(url, **kwargs):
        if url == SIGNED_URL:
            raise requests.ConnectionError(f"could not reach {SIGNED_URL}")
        return original_get(url, **kwargs)

    fake.get = failing_get
    with pytest.raises(DataProviderError) as error:
        provider.refresh_snapshot("fundamentals")

    assert "signature" not in str(error.value)
    assert path.read_bytes() == before


def test_a_stale_snapshot_warns_when_newer_data_is_requested(tmp_path):
    provider, _ = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(800))]})
    path = provider.refresh_snapshot("fundamentals")
    old = time.time() - timedelta(days=30).total_seconds()
    os.utime(path, (old, old))

    with pytest.warns(UserWarning, match="refresh_snapshot"):
        provider.shares_outstanding(end=recent(0))


def test_a_rate_limited_request_waits_for_retry_after_then_succeeds(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(sharadar.time, "sleep", slept.append)
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})
    provider.earliest_date("shares_outstanding")
    fake.scripted = [FakeResponse(429, headers={"Retry-After": "7"})]

    result = provider.shares_outstanding(tickers=["AAA"])

    assert slept == [7.0]
    assert len(result) == 1


def test_persistent_server_errors_raise_after_the_attempt_limit(tmp_path):
    provider, fake = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})
    provider.earliest_date("shares_outstanding")
    provider._schema("fundamentals")
    fake.scripted = [FakeResponse(500, text="boom")] * 10

    with pytest.raises(DataProviderError, match="HTTP 500"):
        provider.shares_outstanding(tickers=["AAA"])

    assert len(fake.scripted) == 10 - sharadar._MAX_ATTEMPTS


def test_market_caps_are_converted_from_millions_to_usd(tmp_path):
    rows = [{"ticker": "AAA", "date": recent(5), "marketcap": 2.5}]
    provider, _ = make_provider(tmp_path, {"daily": rows})

    result = provider.market_caps(tickers=["AAA"])

    assert tuple(result.columns) == base.MARKET_CAP_COLUMNS
    assert result["market_cap_usd"].tolist() == [2_500_000.0]


def test_shares_outstanding_ignore_restated_rows_and_use_the_shared_columns(tmp_path):
    rows = [filing("AAA", recent(5), shares=1), filing("AAA", recent(5), 9, dimension="MRQ")]
    provider, _ = make_provider(tmp_path, {"fundamentals": rows})

    result = provider.shares_outstanding(tickers=["AAA"])

    assert tuple(result.columns) == base.SHARES_OUTSTANDING_COLUMNS
    assert result["shares_outstanding"].tolist() == [1]


def test_prices_use_the_shared_columns(tmp_path):
    row = {
        "ticker": "AAA",
        "date": recent(5),
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "closeunadj": 3.0,
        "closeadj": 1.4,
        "volume": 10.0,
    }
    provider, _ = make_provider(tmp_path, {"stocks": [row]})

    result = provider.prices(tickers=["AAA"])

    assert tuple(result.columns) == base.PRICE_COLUMNS
    assert result["close_with_dividends"].tolist() == [1.4]


def test_securities_cover_delisted_names_in_the_fundamentals_universe(tmp_path):
    def security(table, permaticker, ticker, delisted):
        return {
            "table": table,
            "permaticker": permaticker,
            "ticker": ticker,
            "name": ticker,
            "exchange": "NYSE",
            "isdelisted": delisted,
            "category": "Domestic Common Stock",
            "figi": f"BBG{permaticker}",
            "famaindustry": "Software",
            "sector": "Tech",
            "industry": "Software",
            "currency": "USD",
            "firstpricedate": "2010-01-04",
            "lastpricedate": "2020-01-02",
        }

    rows = [
        security("fundamentals", 1, "NA", "N"),
        security("fundamentals", 2, "OLD", "Y"),
        security("stocks", 3, "ONLYPRICE", "N"),
    ]
    provider, _ = make_provider(tmp_path, {"tickers": rows})

    result = provider.securities()

    assert tuple(result.columns) == base.SECURITY_COLUMNS
    assert result["ticker"].tolist() == ["NA", "OLD"]
    assert result["is_delisted"].tolist() == [False, True]
    assert result["security_id"].tolist() == [1, 2]


def test_a_snapshot_read_returns_rows_older_than_the_subscription_floor(tmp_path):
    rows = [filing("OLD", recent(365 * 11)), filing("OLD", recent(5), dimension="MRQ")]
    provider, _ = make_provider(tmp_path, {"fundamentals": rows})

    result = provider.fetch_snapshot(
        "fundamentals", tickers=["OLD"], fields=["sharesbas"], filters={"dimension": "ARQ"}
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == [recent(365 * 11)]


def test_a_refresh_archives_the_previous_snapshot_instead_of_overwriting_it(tmp_path):
    provider, _ = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(800))]})
    path = provider.refresh_snapshot("fundamentals")
    before = path.read_bytes()

    provider.refresh_snapshot("fundamentals")

    archived = list((path.parent / "archive").iterdir())
    assert [file.read_bytes() for file in archived] == [before]
    assert path.exists()


def test_an_empty_ticker_list_is_rejected_rather_than_meaning_everything(tmp_path):
    provider, _ = make_provider(tmp_path, {"fundamentals": [filing("AAA", recent(5))]})

    with pytest.raises(ValueError, match="tickers is empty"):
        provider.shares_outstanding(tickers=[])


def test_from_env_requires_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("SHARADAR_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER=1\n")

    with pytest.raises(ValueError, match="SHARADAR_API_KEY"):
        SharadarProvider.from_env(env_file=env_file, data_dir=tmp_path)
