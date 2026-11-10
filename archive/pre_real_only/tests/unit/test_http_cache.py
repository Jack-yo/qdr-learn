import hashlib
import json
from urllib.error import HTTPError, URLError

import pytest

from quant_research.data.http import DataUnavailable, HttpCache

URL = "https://data.alpaca.markets/v2/stocks/bars"


def test_cache_offline_hash_and_credentials(tmp_path):
    calls = []
    def opener(url, headers):
        calls.append((url, headers))
        return b'{"bars":{}}'
    client = HttpCache(tmp_path, opener=opener, sleep=lambda _: None)
    raw = client.get(URL, {"feed": "iex"}, {"secret": "DO_NOT_CACHE"})
    assert raw.sha256 == hashlib.sha256(raw.body).hexdigest()
    cached = HttpCache(tmp_path, offline=True).get(URL, {"feed": "iex"})
    assert raw == cached
    assert len(calls) == 1
    for p in tmp_path.rglob("*.json"):
        assert "DO_NOT_CACHE" not in p.read_text()
    (tmp_path / "objects" / raw.sha256).write_bytes(b"corrupted")
    with pytest.raises(DataUnavailable, match="hash mismatch"):
        HttpCache(tmp_path, offline=True).get(URL, {"feed": "iex"})


def test_cache_miss_and_refresh(tmp_path):
    with pytest.raises(DataUnavailable, match="cache miss"):
        HttpCache(tmp_path, offline=True).get(URL)
    first = HttpCache(tmp_path, opener=lambda *_: b"one").get(URL)
    later = HttpCache(tmp_path, refresh=True, opener=lambda *_: b"two").get(URL)
    assert first.sha256 != later.sha256
    assert (tmp_path / "objects" / first.sha256).exists()
    assert len(list((tmp_path / "receipts").glob("*.json"))) == 2


def test_retry_bounded_and_sanitized(tmp_path):
    calls, sleeps = [], []
    def opener(*_):
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(URL, 429, "secret", {"Retry-After": "2"}, None)
        return b"ok"
    assert HttpCache(tmp_path, opener=opener, sleep=sleeps.append).get(URL).body == b"ok"
    assert len(calls) == 3
    assert sleeps.count(2) >= 2
    def forbidden(*_):
        raise HTTPError(URL, 403, "private-token", {}, None)
    with pytest.raises(DataUnavailable, match="HTTP 403") as exc:
        HttpCache(tmp_path / "other", opener=forbidden).get(URL)
    assert "private-token" not in str(exc.value)


def test_network_failure_four_attempts(tmp_path):
    calls = []
    def fail(*_):
        calls.append(1)
        raise URLError("private")
    with pytest.raises(DataUnavailable, match="four attempts"):
        HttpCache(tmp_path, opener=fail, sleep=lambda _: None).get(URL)
    assert len(calls) == 4


@pytest.mark.parametrize("url", ["http://data.sec.gov/a", "https://evil.example/a", "https://secret@data.sec.gov/a", "https://data.sec.gov/a?token=x"])
def test_unsafe_url_rejected(tmp_path, url):
    with pytest.raises(ValueError):
        HttpCache(tmp_path, offline=True).get(url)
