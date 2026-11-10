import json
from urllib.parse import parse_qs, urlsplit

import pytest

from quant_research.clock import TradingClock
from quant_research.data.http import DataUnavailable, HttpCache
from quant_research.data.providers.alpaca import AlpacaProvider


def test_resume_reuses_completed_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    first_calls = []
    def interrupted(url, headers):
        query = parse_qs(urlsplit(url).query)
        first_calls.append(query)
        if "page_token" in query:
            raise DataUnavailable("Simulated interrupted page")
        return json.dumps({"bars": {"SPY": [{"t":"2024-11-27T05:00:00Z", "o":100,"h":101,"l":99,"c":100,"v":1000}]},
                           "next_page_token": "page2"}).encode()
    clock = TradingClock()
    with pytest.raises(DataUnavailable, match="interrupted"):
        AlpacaProvider(clock, HttpCache(tmp_path, opener=interrupted)).bars(["SPY","IWM"], "2024-11-27", "2024-11-27")
    resumed_calls = []
    def resume(url, headers):
        query = parse_qs(urlsplit(url).query)
        resumed_calls.append(query)
        assert query["page_token"] == ["page2"]
        return json.dumps({"bars": {"IWM": [{"t":"2024-11-27T05:00:00Z", "o":100,"h":101,"l":99,"c":100,"v":1000}]},
                           "next_page_token": None}).encode()
    rows = AlpacaProvider(clock, HttpCache(tmp_path, opener=resume)).bars(["SPY","IWM"], "2024-11-27", "2024-11-27")
    assert len(rows) == 2
    assert len(resumed_calls) == 1
    assert len(first_calls) == 2
