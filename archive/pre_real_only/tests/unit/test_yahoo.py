from datetime import date, datetime, timezone
import hashlib
import json

import pytest

from quant_research.clock import TradingClock
from quant_research.contracts import require_entry
from quant_research.data.http import DataUnavailable, RawResponse
from quant_research.data.providers.yahoo import YahooProvider, parse_chart
from quant_research.data.schema import PriceRecord


def chart_body():
    return json.dumps({"chart": {"error": None, "result": [{
        "meta": {"symbol":"SPY", "currency":"USD", "exchangeTimezoneName":"America/New_York", "dataGranularity":"1d"},
        "timestamp": [1732717800, 1732890600],
        "indicators": {"quote":[{"open":[100,101],"high":[102,103],"low":[99,100],"close":[101,102],"volume":[1000,2000]}],
                       "adjclose":[{"adjclose":[99.5,100.5]}]},
        "events":{"dividends":{"1732717800":{"date":1732717800,"amount":0.25}},
                  "splits":{"1732890600":{"date":1732890600,"numerator":2,"denominator":1}}}
    }]}}).encode()


def raw(body):
    return RawResponse(body, datetime(2026,1,1,tzinfo=timezone.utc), hashlib.sha256(body).hexdigest(), "test")


def test_yahoo_basis_adjusted_and_actions():
    clock = TradingClock()
    rows, actions = parse_chart(raw(chart_body()), "SPY", date(2024,11,27), date(2024,11,29), clock)
    assert len(rows) == 2
    assert rows[0].adjustment_basis == "yahoo_split_adjusted"
    assert rows[0].close == 101 and rows[0].adj_close == 99.5
    assert rows[0].available_at.year == 2026
    assert rows[1].event_time.hour == 18  # Thanksgiving Friday early close
    assert [a.factor_or_cash for a in actions] == [0.25, 2.0]
    assert all(a.announced_at is None for a in actions)
    with pytest.raises(ValueError, match=r"T\+1"):
        require_entry(clock.window("2024-11-26",1), clock.window("2024-11-26",1).entry_time, rows[0].adjustment_basis)
    with pytest.raises(ValueError, match="cannot claim raw"):
        PriceRecord.model_validate({**rows[0].model_dump(), "adjustment_basis":"raw"})


def test_yahoo_cached_offline_idempotent_and_hash(tmp_path):
    calls = []
    def download(symbol, start, end):
        calls.append(symbol)
        return chart_body()
    provider = YahooProvider(TradingClock(), tmp_path, downloader=download, sleep=lambda _:None)
    rows = provider.bars(["SPY"], "2024-11-27", "2024-11-29")
    assert calls == ["SPY"]
    replay = YahooProvider(TradingClock(), tmp_path, offline=True, downloader=lambda *_:pytest.fail("network"))
    assert rows == replay.bars(["SPY"], "2024-11-27", "2024-11-29")
    assert provider.last_actions == replay.last_actions
    with pytest.raises(DataUnavailable, match="cache miss"):
        replay.bars(["IWM"], "2024-11-27", "2024-11-29")
    (tmp_path / "objects" / rows[0].raw_sha256).write_bytes(b"bad")
    with pytest.raises(DataUnavailable, match="hash mismatch"):
        replay.bars(["SPY"], "2024-11-27", "2024-11-29")


@pytest.mark.parametrize("change", ["currency", "timezone", "granularity", "length", "future", "missing_price", "duplicate"])
def test_yahoo_rejects_bad_input(change):
    body = json.loads(chart_body())
    data = body["chart"]["result"][0]
    if change == "currency": data["meta"]["currency"] = "EUR"
    elif change == "timezone": data["meta"]["exchangeTimezoneName"] = "UTC"
    elif change == "granularity": data["meta"]["dataGranularity"] = "1h"
    elif change == "length": data["indicators"]["quote"][0]["open"] = []
    elif change == "missing_price": data["indicators"]["quote"][0]["close"][0] = None
    elif change == "duplicate": data["timestamp"][1] = data["timestamp"][0]
    r = raw(json.dumps(body).encode())
    if change == "future": r = RawResponse(r.body,datetime(2024,11,27,10,tzinfo=timezone.utc),r.sha256,r.request_key)
    with pytest.raises(ValueError):
        parse_chart(r,"SPY",date(2024,11,27),date(2024,11,29),TradingClock())


def test_yahoo_retry_and_refresh_retains_raw(tmp_path):
    calls = []
    def flaky(*_):
        calls.append(1)
        if len(calls) < 3: raise DataUnavailable("synthetic timeout")
        return chart_body()
    provider = YahooProvider(TradingClock(),tmp_path,downloader=flaky,sleep=lambda _:None)
    first = provider.bars(["SPY"],"2024-11-27","2024-11-29")
    assert len(calls) == 3
    body = json.loads(chart_body())
    body["chart"]["result"][0]["indicators"]["quote"][0]["close"][0] = 100.5
    refreshed = YahooProvider(TradingClock(),tmp_path,refresh=True,downloader=lambda *_:json.dumps(body).encode(),sleep=lambda _:None)
    second = refreshed.bars(["SPY"],"2024-11-27","2024-11-29")
    assert first[0].raw_sha256 != second[0].raw_sha256
    assert (tmp_path / "objects" / first[0].raw_sha256).exists()
