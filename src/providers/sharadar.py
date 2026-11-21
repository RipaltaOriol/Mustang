"""
Sharadar implementation of DataProvider, over its REST API and bulk snapshots.

See: notes/shares-outstanding-endpoints.md
"""

import logging
import os
import re
import tempfile
import time
import warnings
import zipfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv
import pyarrow.parquet as pq
import requests
from dotenv import dotenv_values

from .base import (
    MARKET_CAP_COLUMNS,
    PRICE_COLUMNS,
    SECURITY_COLUMNS,
    SHARES_OUTSTANDING_COLUMNS,
    DataProvider,
    DataProviderError,
    Dataset,
    DateLike,
    InsufficientHistoryError,
    NotEntitledError,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.sharadar.com/v1.0"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_API_KEY_VARIABLE = "SHARADAR_API_KEY"

_DATED_TABLES = frozenset({"fundamentals", "daily", "stocks", "actions", "events", "sp500"})
_UNDATED_TABLE = "tickers"
_DATASET_TABLES: Mapping[Dataset, str] = {
    "shares_outstanding": "fundamentals",
    "market_caps": "daily",
    "prices": "stocks",
}
_HISTORY_YEARS_BY_TIER: Mapping[str, int | None] = {"full": None, "10": 10, "5": 5}
_EARLIEST_POSSIBLE_DATE = date(1990, 1, 1)

_PAGE_LIMIT = 100_000
_MAX_TICKER_PARAM_LENGTH = 200
_MAX_TICKERS_PER_REQUEST = 30
_MAX_REST_TICKERS = 200
_MAX_REST_WINDOW = timedelta(days=92)
_SNAPSHOT_STALE_AFTER = timedelta(days=7)

_MAX_ATTEMPTS = 5
_TIMEOUT_SECONDS = 300
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

_MARKET_CAP_UNIT_USD = 1_000_000
_ARROW_TYPES = {
    "text": pa.string(),
    "date": pa.date32(),
    "bigint": pa.int64(),
    "double precision": pa.float64(),
}
_SCHEMA_COLUMN = re.compile(r'^\s+"?(\w+)"?\s+(text|date|bigint|double precision)\b', re.MULTILINE)


class SharadarProvider(DataProvider):
    """
    Fetch Sharadar data, using REST for narrow requests and a local snapshot for broad ones.

    See: notes/shares-outstanding-endpoints.md
    """

    def __init__(
        self,
        api_key: str,
        data_dir: Path | str = _PROJECT_ROOT / "data",
        session: requests.Session | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("A Sharadar API key is required.")
        self._api_key = api_key
        self._snapshot_dir = Path(data_dir) / "sharadar"
        self._session = session or requests.Session()
        self._tiers: dict[str, str | None] = {}
        self._schemas: dict[str, dict[str, pa.DataType]] = {}

    def __repr__(self) -> str:
        return f"SharadarProvider(snapshot_dir={str(self._snapshot_dir)!r})"

    @classmethod
    def from_env(
        cls,
        env_file: Path | str = _PROJECT_ROOT / ".env",
        data_dir: Path | str = _PROJECT_ROOT / "data",
    ) -> "SharadarProvider":
        """
        Build a provider from SHARADAR_API_KEY in the environment or the .env file.
        """
        api_key = os.environ.get(_API_KEY_VARIABLE) or dotenv_values(env_file).get(_API_KEY_VARIABLE)
        if not api_key:
            raise ValueError(f"{_API_KEY_VARIABLE} is not set in the environment or {env_file}.")
        return cls(api_key, data_dir)

    def earliest_date(self, dataset: Dataset) -> date:
        return self._earliest_table_date(_DATASET_TABLES[dataset])

    def securities(self) -> pd.DataFrame:
        frame = self.fetch_table(
            _UNDATED_TABLE,
            fields=[
                "permaticker",
                "ticker",
                "name",
                "exchange",
                "isdelisted",
                "category",
                "figi",
                "famaindustry",
                "sector",
                "industry",
                "currency",
                "firstpricedate",
                "lastpricedate",
            ],
            filters={"table": "fundamentals"},
        )
        frame = frame.rename(
            columns={
                "permaticker": "security_id",
                "famaindustry": "fama_industry",
                "firstpricedate": "first_price_date",
                "lastpricedate": "last_price_date",
            }
        )
        frame["is_delisted"] = frame["isdelisted"] == "Y"
        return frame[list(SECURITY_COLUMNS)]

    def shares_outstanding(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        Return every ARQ filing's Share Count, Re-filings included; share_counts in src/panel.py drops them.

        See: docs/adr/0001-a-refiled-quarter-keeps-the-first-share-count.md
        """
        # ARQ keys rows on filing date and excludes restatements, so it cannot leak later data.
        frame = self.fetch_table(
            "fundamentals",
            start,
            end,
            tickers,
            fields=["reportperiod", "sharesbas", "sharefactor"],
            filters={"dimension": "ARQ"},
        )
        frame = frame.rename(
            columns={
                "date": "filed_date",
                "reportperiod": "period_end",
                "sharesbas": "shares_outstanding",
                "sharefactor": "share_factor",
            }
        )
        return frame[list(SHARES_OUTSTANDING_COLUMNS)]

    def market_caps(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self.fetch_table("daily", start, end, tickers, fields=["marketcap"])
        frame["market_cap_usd"] = frame["marketcap"] * _MARKET_CAP_UNIT_USD
        return frame[list(MARKET_CAP_COLUMNS)]

    def prices(
        self,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        frame = self.fetch_table(
            "stocks",
            start,
            end,
            tickers,
            fields=["open", "high", "low", "close", "closeunadj", "closeadj", "volume"],
        )
        frame = frame.rename(
            columns={"closeunadj": "close_unadjusted", "closeadj": "close_with_dividends"}
        )
        return frame[list(PRICE_COLUMNS)]

    def fetch_table(
        self,
        table: str,
        start: DateLike | None = None,
        end: DateLike | None = None,
        tickers: Sequence[str] | None = None,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> pd.DataFrame:
        """
        Return Sharadar rows with their native column names, for criteria beyond the Datasets.
        `ticker`, `date` and any filtered column are always included; `filters` match text exactly.

        Raises:
            NotEntitledError: the subscription does not include the table.
            InsufficientHistoryError: an explicit start precedes the subscription's history.
            DataProviderError: the request failed after retries.
        """
        if table != _UNDATED_TABLE and table not in _DATED_TABLES:
            raise ValueError(f"Unsupported table {table!r}.")
        filters = dict(filters or {})
        ticker_list = _normalise_tickers(tickers)
        self._require_tier(table)

        if table == _UNDATED_TABLE:
            if start is not None or end is not None:
                raise ValueError(f"{_UNDATED_TABLE} has no date column to bound.")
            columns = _with_required_columns(fields, filters, ("ticker",))
            rows = self._fetch_undated(columns, ticker_list, filters)
        else:
            first, last = self._resolve_window(table, start, end)
            columns = _with_required_columns(fields, filters, ("ticker", "date"))
            condition = _row_condition(first, last, ticker_list, filters)
            if _suits_rest(first, last, ticker_list):
                rows = self._fetch_dated(table, first, last, columns, ticker_list, filters)
                rows = rows.filter(condition)
            else:
                rows = self._read_snapshot(table, last, columns, condition)
        return _to_frame(rows)

    def fetch_snapshot(
        self,
        table: str,
        tickers: Sequence[str] | None = None,
        fields: Sequence[str] | None = None,
        filters: Mapping[str, str] | None = None,
    ) -> pd.DataFrame:
        """
        Return Sharadar rows from a table's local snapshot, including those older than the
        rolling subscription floor; `ticker`, `date` and any filtered column are always included.

        Raises:
            NotEntitledError: the subscription does not include the table.
            DataProviderError: the snapshot had to be downloaded and the download failed.
        """
        if table not in _DATED_TABLES:
            raise ValueError(f"Table {table!r} has no bulk snapshot.")
        filters = dict(filters or {})
        ticker_list = _normalise_tickers(tickers)
        condition = _equals_condition(filters)
        if ticker_list is not None:
            condition = condition & pc.field("ticker").isin(ticker_list)
        columns = _with_required_columns(fields, filters, ("ticker", "date"))
        return _to_frame(self._read_snapshot(table, date.today(), columns, condition))

    def refresh_snapshot(self, table: str) -> Path:
        """
        Download the latest bulk file for a table, archiving any previous local snapshot.

        Raises:
            NotEntitledError: the subscription does not include the table.
            DataProviderError: the download failed.
        """
        if table not in _DATED_TABLES:
            raise ValueError(f"Table {table!r} has no bulk snapshot.")
        tier = self._require_tier(table)
        url = self._bulk_url(table, tier)
        if url is None:
            raise NotEntitledError(f"The subscription no longer includes bulk {table} data.")

        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = self._snapshot_path(table, tier)
        with tempfile.TemporaryDirectory(dir=self._snapshot_dir) as work_dir:
            archive = Path(work_dir) / "bulk.zip"
            parquet = Path(work_dir) / "snapshot.parquet"
            logger.info("Downloading the %s bulk file (tier %s).", table, tier)
            self._download(url, archive, table)
            self._convert_archive(table, archive, parquet)
            self._archive_snapshot(path)
            os.replace(parquet, path)
        return path

    def _archive_snapshot(self, path: Path) -> None:
        if not path.exists():
            return
        archive_dir = self._snapshot_dir / "archive"
        archive_dir.mkdir(exist_ok=True)
        taken = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%dT%H%M%S%f")
        os.link(path, archive_dir / f"{path.stem}-{taken}{path.suffix}")

    def snapshot_date(self, table: str) -> date | None:
        """
        Return when the local snapshot of a table was downloaded, or None if there is none.
        """
        path = self._snapshot_path(table, self._require_tier(table))
        return date.fromtimestamp(path.stat().st_mtime) if path.exists() else None

    def _read_snapshot(
        self, table: str, last: date, columns: list[str] | None, condition: pc.Expression
    ) -> pa.Table:
        path = self._snapshot_path(table, self._require_tier(table))
        if not path.exists():
            self.refresh_snapshot(table)
        taken = date.fromtimestamp(path.stat().st_mtime)
        if last - taken > _SNAPSHOT_STALE_AFTER:
            warnings.warn(
                f"The {table} snapshot is from {taken}, but data through {last} was requested. "
                f"Call refresh_snapshot({table!r}) to update it.",
                stacklevel=4,
            )
        return pq.read_table(path, columns=columns, filters=condition)

    def _snapshot_path(self, table: str, tier: str) -> Path:
        return self._snapshot_dir / f"{table}-{tier}.parquet"

    def _download(self, url: str, destination: Path, table: str) -> None:
        # The signed URL is a credential and the bulk host must never receive the API key.
        try:
            with self._session.get(url, stream=True, timeout=_TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    raise DataProviderError(
                        f"The {table} bulk download failed with HTTP {response.status_code}."
                    )
                with destination.open("wb") as file:
                    for chunk in response.iter_content(_DOWNLOAD_CHUNK_BYTES):
                        file.write(chunk)
        except requests.RequestException as error:
            raise DataProviderError(
                f"The {table} bulk download failed: {type(error).__name__}."
            ) from None

    def _convert_archive(self, table: str, archive: Path, parquet: Path) -> None:
        with zipfile.ZipFile(archive) as bundle:
            names = bundle.namelist()
            if len(names) != 1:
                raise DataProviderError(f"Expected one file in the {table} bulk zip, found {names}.")
            with bundle.open(names[0]) as csv_stream:
                reader = pa_csv.open_csv(csv_stream, convert_options=self._convert_options(table))
                with pq.ParquetWriter(parquet, reader.schema, compression="zstd") as writer:
                    for batch in reader:
                        writer.write_batch(batch)

    def _fetch_dated(
        self,
        table: str,
        first: date,
        last: date,
        columns: list[str] | None,
        tickers: list[str] | None,
        filters: Mapping[str, str],
    ) -> pa.Table:
        # Pages advance by date because `skip` over a non-unique sort drops and repeats rows.
        params = {**filters, "to": last.isoformat(), "sort": "date.asc", "limit": _PAGE_LIMIT}
        if columns:
            params["fields"] = ",".join(columns)

        pages = []
        for ticker_param in _ticker_params(tickers):
            scoped = {**params, "ticker": ticker_param} if ticker_param else params
            cursor = first
            while True:
                page = self._get_csv(table, {**scoped, "from": cursor.isoformat()})
                if page.num_rows < _PAGE_LIMIT:
                    pages.append(page)
                    break
                page_end = pc.max(page["date"]).as_py()
                if page_end == cursor:
                    raise DataProviderError(
                        f"{table} has at least {_PAGE_LIMIT} rows on {cursor}; narrow the request."
                    )
                pages.append(page.filter(pc.field("date") < page_end))
                cursor = page_end
        return pa.concat_tables(pages)

    def _fetch_undated(
        self,
        columns: list[str] | None,
        tickers: list[str] | None,
        filters: Mapping[str, str],
    ) -> pa.Table:
        params = {**filters, "sort": "ticker.asc", "limit": _PAGE_LIMIT}
        if columns:
            params["fields"] = ",".join(columns)
        pages = []
        for ticker_param in _ticker_params(tickers):
            scoped = {**params, "ticker": ticker_param} if ticker_param else params
            page = self._get_csv(_UNDATED_TABLE, scoped)
            if page.num_rows >= _PAGE_LIMIT:
                raise DataProviderError(
                    f"{_UNDATED_TABLE} reached the {_PAGE_LIMIT} row limit; results would be partial."
                )
            pages.append(page)
        return pa.concat_tables(pages).filter(_equals_condition(filters))

    def _get_csv(self, table: str, params: Mapping[str, object]) -> pa.Table:
        response = self._request(f"data/{table}", params)
        _raise_for_status(response, table)
        return pa_csv.read_csv(
            pa.BufferReader(response.content), convert_options=self._convert_options(table)
        )

    def _convert_options(self, table: str) -> pa_csv.ConvertOptions:
        # Only empty cells are null: pyarrow's defaults would erase the real ticker "NA".
        return pa_csv.ConvertOptions(
            column_types=self._schema(table), null_values=[""], strings_can_be_null=True
        )

    def _schema(self, table: str) -> dict[str, pa.DataType]:
        if table not in self._schemas:
            response = self._request(f"schema/{table}", {"format": "postgres"})
            _raise_for_status(response, table)
            self._schemas[table] = {
                name: _ARROW_TYPES[kind] for name, kind in _SCHEMA_COLUMN.findall(response.text)
            }
        return self._schemas[table]

    def _require_tier(self, table: str) -> str:
        # A 200 proves nothing: unentitled keys silently receive a partial free-tier universe.
        tier = self._history_tier(table)
        if tier is None:
            raise NotEntitledError(
                f"The subscription does not include {table}; compare plans at sharadar.com/subscribe."
            )
        return tier

    def _history_tier(self, table: str) -> str | None:
        if table not in self._tiers:
            self._tiers[table] = next(
                (tier for tier in _HISTORY_YEARS_BY_TIER if self._bulk_url(table, tier)), None
            )
        return self._tiers[table]

    def _bulk_url(self, table: str, tier: str) -> str | None:
        response = self._request(f"data/{table}", {"years": tier}, allow_redirects=False)
        if response.status_code == 302:
            return response.headers["Location"]
        if response.status_code in (401, 403):
            return None
        _raise_for_status(response, table)
        raise DataProviderError(f"Expected a redirect for bulk {table}, got HTTP 200.")

    def _earliest_table_date(self, table: str) -> date:
        years = _HISTORY_YEARS_BY_TIER[self._require_tier(table)]
        if years is None:
            return _EARLIEST_POSSIBLE_DATE
        return (pd.Timestamp(date.today()) - pd.DateOffset(years=years)).date()

    def _resolve_window(
        self, table: str, start: DateLike | None, end: DateLike | None
    ) -> tuple[date, date]:
        floor = self._earliest_table_date(table)
        first = floor if start is None else _to_date(start)
        last = date.today() if end is None else _to_date(end)
        if first < floor:
            raise InsufficientHistoryError(
                f"{table} is available from {floor} on this subscription; {first} was requested. "
                "Pass start=None to use all available history."
            )
        if first > last:
            raise ValueError(f"start {first} is after end {last}.")
        return first, last

    def _request(
        self, path: str, params: Mapping[str, object], allow_redirects: bool = True
    ) -> requests.Response:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(
                    f"{_BASE_URL}/{path}",
                    params=params,
                    headers={"x-api-key": self._api_key},
                    timeout=_TIMEOUT_SECONDS,
                    allow_redirects=allow_redirects,
                )
            except requests.RequestException as error:
                if attempt == _MAX_ATTEMPTS:
                    raise DataProviderError(
                        f"Request to {path} failed: {type(error).__name__}."
                    ) from None
                delay = 2.0**attempt
            else:
                if response.status_code not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS:
                    return response
                delay = _retry_delay(response, attempt)
            logger.warning("Retrying %s in %.0f seconds.", path, delay)
            time.sleep(delay)
        raise AssertionError("The retry loop always returns or raises.")


def _retry_delay(response: requests.Response, attempt: int) -> float:
    headers = response.headers
    if "Retry-After" in headers:
        return float(headers["Retry-After"])
    if headers.get("X-RateLimit-Remaining") == "0" and "X-RateLimit-Reset" in headers:
        return max(float(headers["X-RateLimit-Reset"]) - time.time(), 1.0)
    return 2.0**attempt


def _raise_for_status(response: requests.Response, table: str) -> None:
    if response.status_code == 200:
        return
    if response.status_code in (401, 403):
        raise NotEntitledError(f"{table}: {response.text[:200]}")
    raise DataProviderError(f"{table}: HTTP {response.status_code}: {response.text[:200]}")


def _to_date(value: DateLike) -> date:
    return pd.Timestamp(value).date()


def _normalise_tickers(tickers: Sequence[str] | None) -> list[str] | None:
    if tickers is None:
        return None
    ticker_list = [tickers] if isinstance(tickers, str) else list(dict.fromkeys(tickers))
    if not ticker_list:
        raise ValueError("tickers is empty; pass None to request the whole universe.")
    return ticker_list


def _with_required_columns(
    fields: Sequence[str] | None, filters: Mapping[str, str], required: Sequence[str]
) -> list[str] | None:
    if fields is None:
        return None
    return list(dict.fromkeys([*required, *fields, *filters]))


def _suits_rest(first: date, last: date, tickers: list[str] | None) -> bool:
    if tickers is not None and len(tickers) <= _MAX_REST_TICKERS:
        return True
    return last - first <= _MAX_REST_WINDOW


def _ticker_params(tickers: list[str] | None) -> Iterator[str | None]:
    if tickers is None:
        yield None
        return
    batch: list[str] = []
    for ticker in tickers:
        candidate = [*batch, ticker]
        if (
            len(candidate) > _MAX_TICKERS_PER_REQUEST
            or len(",".join(candidate)) > _MAX_TICKER_PARAM_LENGTH
        ):
            yield ",".join(batch)
            candidate = [ticker]
        batch = candidate
    yield ",".join(batch)


def _equals_condition(filters: Mapping[str, str]) -> pc.Expression:
    condition = pc.scalar(True)
    for column, value in filters.items():
        condition = condition & (pc.field(column) == value)
    return condition


def _row_condition(
    first: date, last: date, tickers: list[str] | None, filters: Mapping[str, str]
) -> pc.Expression:
    # Also applied to REST rows, because the API silently ignores filters it does not support.
    condition = _equals_condition(filters)
    condition = condition & (pc.field("date") >= first) & (pc.field("date") <= last)
    if tickers is not None:
        condition = condition & pc.field("ticker").isin(tickers)
    return condition


def _to_frame(rows: pa.Table) -> pd.DataFrame:
    keys = [column for column in ("date", "ticker") if column in rows.column_names]
    ordered = rows.sort_by([(key, "ascending") for key in keys])
    return ordered.to_pandas(date_as_object=False)
