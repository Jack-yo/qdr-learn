from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest

from quant_research.clock import TradingClock
from quant_research.data.http import DataUnavailable, HttpCache, RawResponse
from quant_research.data.providers.alpaca import AlpacaProvider
from quant_research.data.providers.french import parse_daily_zip
from quant_research.data.providers.sec import SECProvider, recent_filings


def zip_csv(content):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("daily.csv", content)
    return buffer.getvalue()


def test_french_percentage_missing_footer():
    body = zip_csv("Synthetic test data\n,Mkt-RF,SMB,HML,RMW,CMA,RF\n20241127,1.23,-0.50,-99.99,0,0.2,0.01\n\nAnnual Factors\n2024,1,2,3\n")
    rows = parse_daily_zip(body, datetime(2026, 1, 1, tzinfo=timezone.utc), "hash")
    assert len(rows) == 6
    assert rows[0].value_decimal == 0.0123
    assert rows[1].value_decimal == -0.005
    assert rows[2].value_decimal is None
    assert all(r.use_policy == "ATTRIBUTION_ONLY" for r in rows)
    assert all(r.available_at.year == 2026 for r in rows)


@pytest.mark.parametrize("content", [",Mom\n20241127,nan\n", ",Mom\n20241127,0.1\n20241127,0.2\n", ",Mom\n20241127,200\n", "not a dataset"])
def test_french_bad_inputs(content):
    with pytest.raises(ValueError):
        parse_daily_zip(zip_csv(content), datetime(2026, 1, 1, tzinfo=timezone.utc), "hash")


def test_alpaca_pagination_offline_and_raw(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "fake-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fake-secret")
    requests = []
    def opener(url, headers):
        query = parse_qs(urlsplit(url).query)
        requests.append(query)
        symbol = "SPY" if "page_token" not in query else "IWM"
        return json.dumps({"bars": {symbol: [{"t": "2024-11-27T05:00:00Z", "o": 100, "h": 103, "l": 99, "c": 102, "v": 1000}]},
                           "next_page_token": "second" if symbol == "SPY" else None}).encode()
    clock = TradingClock()
    rows = AlpacaProvider(clock, HttpCache(tmp_path, opener=opener)).bars(["SPY", "IWM"], "2024-11-27", "2024-11-27")
    assert len(rows) == 2
    assert requests[0]["adjustment"] == ["raw"]
    assert requests[0]["asof"] == ["-"]
    assert all(r.available_at > r.event_time and r.availability_basis == "first_observed" for r in rows)
    monkeypatch.delenv("ALPACA_API_KEY")
    monkeypatch.delenv("ALPACA_SECRET_KEY")
    replay = AlpacaProvider(clock, HttpCache(tmp_path, offline=True)).bars(["SPY", "IWM"], "2024-11-27", "2024-11-27")
    assert replay == rows


def test_alpaca_credentials_and_page_loop(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    with pytest.raises(DataUnavailable, match="required"):
        AlpacaProvider(TradingClock(), HttpCache(tmp_path)).bars(["SPY"], "2024-11-27", "2024-11-27")
    monkeypatch.setenv("ALPACA_API_KEY", "fake")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "fake")
    http = HttpCache(tmp_path, opener=lambda *_: b'{"bars":{},"next_page_token":"loop"}', sleep=lambda _: None)
    with pytest.raises(DataUnavailable, match="Repeated"):
        AlpacaProvider(TradingClock(), http).bars(["SPY"], "2024-11-27", "2024-11-27")


def test_sec_headers_snapshots_not_pit(tmp_path):
    seen = []
    def opener(url, headers):
        seen.append(headers)
        recent = {"accessionNumber": ["test"], "form": ["10-K"], "reportDate": ["2024-09-30"],
                  "acceptanceDateTime": ["2024-11-01T20:00:00Z"]}
        return json.dumps({"cik": 320193, "filings": {"recent": recent}} if "submissions" in url else {"cik":320193,"facts":{}}).encode()
    with pytest.raises(DataUnavailable, match="SEC_USER_AGENT"):
        SECProvider(HttpCache(tmp_path), "missing-email").snapshots("320193")
    snapshots = SECProvider(HttpCache(tmp_path, opener=opener), "Tests unit@example.com").snapshots("320193")
    assert len(snapshots) == 2
    assert seen[0]["User-Agent"] == "Tests unit@example.com"
    filings = recent_filings(snapshots[0])
    assert filings[0]["available_at"] > filings[0]["accepted_at"]
    assert filings[0]["quality_flag"] == "SNAPSHOT_ONLY|NOT_PIT"
    assert len(SECProvider(HttpCache(tmp_path, offline=True)).snapshots("320193")) == 2


def test_sec_rate_limit_below_ten_per_second(tmp_path):
    waits = []
    client = HttpCache(tmp_path, opener=lambda *_: b"ok", sleep=waits.append)
    client._last.pop("data.sec.gov", None)
    client.get("https://data.sec.gov/a")
    client.get("https://data.sec.gov/b")
    assert any(0.1 < wait <= 0.21 for wait in waits)
