import io
import json
import zipfile

import pytest

from src.providers.sec import SecProvider, cover_share_counts

INSTANCE = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:dei="http://xbrl.sec.gov/dei/2014-01-31"
    xmlns:us-gaap="http://fasb.org/us-gaap/2016-01-31">
  <xbrli:context id="ClassA">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassAMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2017-01-27</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="ClassB">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassBMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:instant>2017-01-27</xbrli:instant></xbrli:period>
  </xbrli:context>
  <dei:EntityCommonStockSharesOutstanding contextRef="ClassA" unitRef="shares" decimals="INF">774680</dei:EntityCommonStockSharesOutstanding>
  <dei:EntityCommonStockSharesOutstanding contextRef="ClassB" unitRef="shares" decimals="INF">1304592522</dei:EntityCommonStockSharesOutstanding>
  <us-gaap:Revenues contextRef="ClassA" unitRef="usd" decimals="-6">5</us-gaap:Revenues>
</xbrli:xbrl>
"""

INLINE = """<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
<ix:header><ix:resources>
<xbrli:context id="c-1"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
  <xbrli:period><xbrli:instant>2026-10-20</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c-2"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassBMember</xbrldi:explicitMember></xbrli:segment>
  </xbrli:entity><xbrli:period><xbrli:instant>2026-10-20</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c-3"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassCMember</xbrldi:explicitMember></xbrli:segment>
  </xbrli:entity><xbrli:period><xbrli:instant>2026-10-20</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="c-4"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
  <xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementClassOfStockAxis">us-gaap:CommonClassDMember</xbrldi:explicitMember></xbrli:segment>
  </xbrli:entity><xbrli:period><xbrli:instant>2026-10-20</xbrli:instant></xbrli:period></xbrli:context>
</ix:resources></ix:header>
<p>Class A: <ix:nonFraction unitRef="shares" contextRef="c-1" decimals="-6" name="dei:EntityCommonStockSharesOutstanding" format="ixt:num-dot-decimal" scale="6">5,888</ix:nonFraction></p>
<p>Class B: <ix:nonFraction unitRef="shares" contextRef="c-2" decimals="INF" name="dei:EntityCommonStockSharesOutstanding" format="ixt:num-dot-decimal" scale="0"><span>827,000,000</span></ix:nonFraction></p>
<p>Class C: <ix:nonFraction unitRef="shares" contextRef="c-3" decimals="INF" name="dei:EntityCommonStockSharesOutstanding" format="ixt:fixed-zero" scale="0">-</ix:nonFraction></p>
<p>Class D: <ix:nonFraction unitRef="shares" contextRef="c-4" decimals="INF" name="dei:EntityCommonStockSharesOutstanding" format="ixt-sec:numwordsen" scale="0">one</ix:nonFraction></p>
<p><ix:nonFraction unitRef="usd" contextRef="c-1" name="us-gaap:Revenues" scale="6">10</ix:nonFraction></p>
</body></html>
"""


def test_cover_counts_from_an_instance_are_keyed_by_class():
    assert cover_share_counts(INSTANCE) == {
        "StatementClassOfStockAxis=CommonClassAMember": 774_680.0,
        "StatementClassOfStockAxis=CommonClassBMember": 1_304_592_522.0,
    }


def test_cover_counts_from_inline_xbrl_apply_scale_and_formats():
    assert cover_share_counts(INLINE) == {
        "": 5_888_000_000.0,
        "StatementClassOfStockAxis=CommonClassBMember": 827_000_000.0,
        "StatementClassOfStockAxis=CommonClassCMember": 0.0,
        "StatementClassOfStockAxis=CommonClassDMember": 1.0,
    }


def test_cover_counts_are_empty_without_the_cover_fact():
    assert cover_share_counts("<html><body>No XBRL</body></html>") == {}


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        return self.responses[url]


def zipped(**files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, text in files.items():
            bundle.writestr(name, text)
    return buffer.getvalue()


def test_provider_requires_a_user_agent(tmp_path):
    with pytest.raises(ValueError):
        SecProvider("", tmp_path)


def test_provider_reads_the_cover_from_the_filing_zip_and_caches_it(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1067983/000106798317000008/0001067983-17-000008-xbrl.zip"
    archive = zipped(**{"brka-20161231.xml": INSTANCE, "brka-20161231_lab.xml": "<labels/>"})
    session = FakeSession({url: FakeResponse(200, archive)})
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    first = provider.cover(1067983, "0001067983-17-000008")
    second = provider.cover(1067983, "0001067983-17-000008")

    assert first == second == cover_share_counts(INSTANCE)
    assert session.urls == [url]
    assert session.headers["User-Agent"] == "research contact@example.com"


def test_provider_reads_inline_covers_from_the_primary_document(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000084/0001652044-26-000084-xbrl.zip"
    archive = zipped(**{"goog-20260930.htm": INLINE, "exhibit31.htm": "<html></html>"})
    session = FakeSession({url: FakeResponse(200, archive)})
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    assert provider.cover(1652044, "0001652044-26-000084") == cover_share_counts(INLINE)


def test_provider_returns_no_cover_when_the_filing_has_no_xbrl(tmp_path):
    url = "https://www.sec.gov/Archives/edgar/data/1/000000000017000001/0000000000-17-000001-xbrl.zip"
    session = FakeSession({url: FakeResponse(404)})
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    assert provider.cover(1, "0000000000-17-000001") == {}


def test_provider_lists_periodic_reports_across_submission_pages(tmp_path):
    base = "https://data.sec.gov/submissions/"
    recent = {
        "accessionNumber": ["a-3", "a-2"],
        "filingDate": ["2026-10-29", "2026-08-01"],
        "form": ["10-Q", "8-K"],
    }
    older = {"accessionNumber": ["a-1"], "filingDate": ["2017-02-03"], "form": ["10-K"]}
    session = FakeSession(
        {
            f"{base}CIK0000000001.json": FakeResponse(
                200,
                json.dumps(
                    {"filings": {"recent": recent, "files": [{"name": "CIK0000000001-1.json"}]}}
                ).encode(),
            ),
            f"{base}CIK0000000001-1.json": FakeResponse(200, json.dumps(older).encode()),
        }
    )
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    reports = provider.periodic_reports(1)

    assert reports["accession"].tolist() == ["a-1", "a-3"]
    assert reports["form"].tolist() == ["10-K", "10-Q"]
    assert str(reports["filed_date"].dtype) == "datetime64[ns]"


def test_provider_lists_undimensioned_cover_counts_by_filing(tmp_path):
    url = (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0000000001/dei/"
        "EntityCommonStockSharesOutstanding.json"
    )
    facts = {
        "units": {
            "shares": [
                {"accn": "a-2", "filed": "2026-10-29", "form": "10-Q", "val": 120},
                {"accn": "a-1", "filed": "2026-07-29", "form": "10-Q", "val": 100},
            ]
        }
    }
    session = FakeSession({url: FakeResponse(200, json.dumps(facts).encode())})
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    counts = provider.undimensioned_cover_counts(1)

    assert counts["accession"].tolist() == ["a-1", "a-2"]
    assert counts["share_count"].tolist() == [100.0, 120.0]
    assert str(counts["filed_date"].dtype) == "datetime64[ns]"


def test_provider_lists_no_undimensioned_counts_when_every_count_has_a_class(tmp_path):
    url = (
        "https://data.sec.gov/api/xbrl/companyconcept/CIK0001652044/dei/"
        "EntityCommonStockSharesOutstanding.json"
    )
    session = FakeSession({url: FakeResponse(404)})
    provider = SecProvider("research contact@example.com", tmp_path, session=session, pause_seconds=0)

    counts = provider.undimensioned_cover_counts(1652044)

    assert counts.empty
    assert list(counts.columns) == ["accession", "filed_date", "share_count"]
