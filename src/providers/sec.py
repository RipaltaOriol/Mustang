"""
SEC EDGAR reader for the shares outstanding, per Share Class, on a filing's cover page.
"""

import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import requests

from .base import DataProviderError

logger = logging.getLogger(__name__)

_COVER_FACT = "EntityCommonStockSharesOutstanding"
_PERIODIC_FORMS = frozenset({"10-K", "10-Q", "10-KT", "10-QT"})
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"
_MAX_ATTEMPTS = 5
_TIMEOUT_SECONDS = 60
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
# SEC allows ten requests a second per client.
_PAUSE_SECONDS = 0.12

_LINKBASE = re.compile(r"(_cal|_def|_lab|_pre)\.xml$|FilingSummary\.xml$")
_INLINE_CONTEXT = re.compile(
    r"<xbrli:context\b[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</xbrli:context>", re.S
)
_INLINE_MEMBER = re.compile(
    r"<xbrldi:explicitMember[^>]*dimension=\"([^\"]+)\"[^>]*>\s*([^<\s]+)\s*</xbrldi:explicitMember>"
)
_INLINE_FACT = re.compile(
    rf"<ix:nonFraction\b([^>]*\bname=\"dei:{_COVER_FACT}\"[^>]*)>(.*?)</ix:nonFraction>", re.S
)
_ATTRIBUTE = re.compile(r"([\w:-]+)=\"([^\"]*)\"")
_TAG = re.compile(r"<[^>]+>")
_NUMBER_WORDS = {
    "no": 0, "none": 0, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip


def cover_share_counts(document: str | bytes) -> dict[str, float]:
    """
    Return the shares outstanding on the cover of an XBRL or inline XBRL document, keyed by
    their `Axis=Member` dimensions, with "" for the count that carries no dimension.
    """
    text = document.decode("utf-8", "replace") if isinstance(document, bytes) else document
    if f"dei:{_COVER_FACT}" in text and "<ix:" in text:
        return _inline_counts(text)
    if _COVER_FACT in text:
        return _instance_counts(text)
    return {}


class SecProvider:
    """
    Read periodic reports and their cover pages from SEC EDGAR, caching every download.

    Raises:
        DataProviderError: a request failed after retries.
    """

    def __init__(
        self,
        user_agent: str,
        cache_dir: Path | str,
        session: requests.Session | None = None,
        pause_seconds: float = _PAUSE_SECONDS,
    ) -> None:
        if not user_agent:
            raise ValueError("SEC requires a User-Agent that names a contact.")
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = user_agent
        self._cache_dir = Path(cache_dir)
        self._pause_seconds = pause_seconds
        self._reports: dict[int, pd.DataFrame] = {}

    def __repr__(self) -> str:
        return f"SecProvider(cache_dir={str(self._cache_dir)!r})"

    def periodic_reports(self, cik: int) -> pd.DataFrame:
        """
        Return a Company's 10-K and 10-Q filings as `accession`, `filed_date` and `form`.
        """
        if cik not in self._reports:
            index = json.loads(self._fetch(f"{_SUBMISSIONS_URL}CIK{cik:010d}.json") or b"{}")
            filings = index.get("filings", {})
            pages = [filings.get("recent", {})]
            for older in filings.get("files", []):
                pages.append(json.loads(self._fetch(_SUBMISSIONS_URL + older["name"]) or b"{}"))
            frame = pd.concat(
                [
                    pd.DataFrame(
                        {
                            "accession": page.get("accessionNumber", []),
                            "filed_date": page.get("filingDate", []),
                            "form": page.get("form", []),
                        }
                    )
                    for page in pages
                ],
                ignore_index=True,
            )
            frame = frame[frame["form"].isin(_PERIODIC_FORMS)]
            frame["filed_date"] = pd.to_datetime(frame["filed_date"]).astype("datetime64[ns]")
            self._reports[cik] = frame.sort_values("filed_date").reset_index(drop=True)
        return self._reports[cik]

    def undimensioned_cover_counts(self, cik: int) -> pd.DataFrame:
        """
        Return the cover's shares outstanding that carry no Share Class, as `accession`,
        `filed_date` and `shares_outstanding`; Companies that report only per class have none.
        """
        url = f"{_CONCEPT_URL}CIK{cik:010d}/dei/{_COVER_FACT}.json"
        body = self._fetch(url)
        facts = json.loads(body)["units"].get("shares", []) if body else []
        frame = pd.DataFrame(
            {
                "accession": [fact["accn"] for fact in facts],
                "filed_date": pd.to_datetime([fact["filed"] for fact in facts]),
                "shares_outstanding": [float(fact["val"]) for fact in facts],
            }
        )
        frame["filed_date"] = frame["filed_date"].astype("datetime64[ns]")
        return frame.sort_values("filed_date").reset_index(drop=True)

    def cover(self, cik: int, accession: str) -> dict[str, float]:
        """
        Return the shares outstanding on one filing's cover, empty when it carries no XBRL.

        Raises:
            DataProviderError: the filing could not be downloaded.
        """
        cached = self._cache_dir / "covers" / f"{accession}.json"
        if cached.exists():
            return json.loads(cached.read_text())

        folder = accession.replace("-", "")
        archive = self._fetch(f"{_ARCHIVES_URL}/{cik}/{folder}/{accession}-xbrl.zip")
        counts = _archive_counts(archive) if archive is not None else {}
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(counts))
        return counts

    def _fetch(self, url: str) -> bytes | None:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, timeout=_TIMEOUT_SECONDS)
            except requests.RequestException as error:
                if attempt == _MAX_ATTEMPTS:
                    raise DataProviderError(f"{url} failed: {type(error).__name__}.") from None
            else:
                time.sleep(self._pause_seconds)
                if response.status_code == 200:
                    return response.content
                if response.status_code == 404:
                    return None
                if response.status_code not in _RETRYABLE_STATUSES or attempt == _MAX_ATTEMPTS:
                    raise DataProviderError(f"{url} failed with HTTP {response.status_code}.")
            logger.warning("Retrying %s.", url)
            time.sleep(2.0**attempt)
        raise AssertionError("The retry loop always returns or raises.")


def _archive_counts(archive: bytes) -> dict[str, float]:
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [name for name in bundle.namelist() if not _LINKBASE.search(name)]
        documents = [name for name in names if name.endswith(".xml")] + [
            name for name in names if name.endswith((".htm", ".html"))
        ]
        for name in documents:
            counts = cover_share_counts(bundle.read(name))
            if counts:
                return counts
    return {}


def _instance_counts(text: str) -> dict[str, float]:
    root = ET.fromstring(text.encode())
    dimensions = {
        context.get("id"): _dimension_key(
            (member.get("dimension"), member.text)
            for member in context.iter()
            if _local(member.tag) == "explicitMember"
        )
        for context in root.iter()
        if _local(context.tag) == "context"
    }
    return {
        dimensions.get(fact.get("contextRef"), ""): float(fact.text)
        for fact in root
        if _local(fact.tag) == _COVER_FACT
    }


def _inline_counts(text: str) -> dict[str, float]:
    dimensions = {
        context_id: _dimension_key(_INLINE_MEMBER.findall(body))
        for context_id, body in _INLINE_CONTEXT.findall(text)
    }
    counts = {}
    for attributes, content in _INLINE_FACT.findall(text):
        attribute = dict(_ATTRIBUTE.findall(attributes))
        value = _inline_number(_TAG.sub("", content).strip(), attribute.get("format", ""))
        counts[dimensions.get(attribute["contextRef"], "")] = value * 10 ** int(
            attribute.get("scale", "0")
        )
    return counts


def _inline_number(raw: str, number_format: str) -> float:
    if "zero" in number_format or raw in ("", "-", "—", "&#8212;"):
        return 0.0
    if "word" in number_format:
        return float(_NUMBER_WORDS.get(raw.lower(), "nan"))
    if "comma-decimal" in number_format or "numcommadecimal" in number_format:
        return float(raw.replace(".", "").replace(" ", "").replace(",", "."))
    return float(raw.replace(",", "").replace(" ", ""))


def _dimension_key(members: Iterable[tuple[str | None, str | None]]) -> str:
    return "|".join(sorted(f"{_local_name(axis)}={_local_name(member)}" for axis, member in members))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _local_name(qualified: str | None) -> str:
    return (qualified or "").strip().split(":")[-1]
