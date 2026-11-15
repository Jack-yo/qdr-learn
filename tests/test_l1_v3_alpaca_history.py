"""Alpaca historical bars: feed correctness, paging and invalid data failure."""
from datetime import datetime,timezone
from urllib.parse import urlsplit,parse_qs
import json
import pytest

from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable


def _env(**kw):
    return {"ALPACA_API_KEY":"fake_public_id",
            "ALPACA_SECRET_KEY":"fake_private_secret",
            "QDR_L1_FEED":"delayed_sip",**kw}


def _bar(when,price=100):
    return {"t":when+"T05:00:00Z","o":price,"h":price+2,
            "l":price-2,"c":price+.5,"v":1000}


def test_history_feed_separate_from_snapshot_and_split_adjustment(tmp_path):
    queries=[]
    def fake(url,headers):
        query=parse_qs(urlsplit(url).query)
        queries.append((urlsplit(url).path,query))
        if urlsplit(url).path.endswith("/stocks/bars"):
            return json.dumps({"bars":{"SPY":[_bar("2026-11-12"),_bar("2026-11-13")]},
                               "next_page_token":None}).encode()
        return json.dumps({"snapshots":{"SPY":{}}}).encode()
    live=LiveSources(tmp_path,fetch=fake,env=_env(),
                     now=lambda:datetime(2026,11,15,tzinfo=timezone.utc))
    data,receipts=live.bars(days=30,symbols=("SPY",),
                            end_date="2026-11-13",adjustment="split")
    assert len(data["SPY"])==2
    assert queries[0][1]["feed"]==["sip"]
    assert queries[0][1]["adjustment"]==["split"]
    assert queries[0][1]["end"]==["2026-11-14"]
    assert receipts[0]["feed"]=="sip"
    assert receipts[0]["adjustment"]=="split"
    live.snapshots(symbols=("SPY",))
    assert queries[1][1]["feed"]==["delayed_sip"]
    assert all("fake_public_id" not in str(url) and "fake_private_secret" not in str(url)
               for url in queries)


def test_historical_history_feed_can_be_explicit_iex(tmp_path):
    calls=[]
    def fake(url,headers):
        calls.append(parse_qs(urlsplit(url).query))
        return json.dumps({"bars":{"SPY":[_bar("2026-11-13")]},
                           "next_page_token":None}).encode()
    src=LiveSources(tmp_path,fetch=fake,env=_env(QDR_L1_HISTORY_FEED="iex"))
    src.bars(days=30,symbols=("SPY",),end_date="2026-11-13")
    assert calls[0]["feed"]==["iex"]


def test_page_token_drives_complete_multi_symbol_scan(tmp_path):
    calls=[]
    def fake(url,headers):
        q=parse_qs(urlsplit(url).query)
        calls.append(q)
        if "page_token" not in q:
            return json.dumps({"bars":{"IWM":[_bar("2026-11-11")]},
                               "next_page_token":"page-two"}).encode()
        return json.dumps({"bars":{"SPY":[_bar("2026-11-12")]},
                           "next_page_token":None}).encode()
    src=LiveSources(tmp_path,fetch=fake,env=_env())
    data,receipts=src.bars(days=30,symbols=("SPY","IWM"),
                            end_date="2026-11-13")
    assert len(calls)==2
    assert calls[1]["page_token"]==["page-two"]
    assert len(receipts)==2
    assert len(data["SPY"])==len(data["IWM"])==1


@pytest.mark.parametrize("feed",["delayed_sip","overnight","INVALID"])
def test_illegal_historical_feed_is_rejected(tmp_path,feed):
    src=LiveSources(tmp_path,env=_env(QDR_L1_HISTORY_FEED=feed))
    with pytest.raises(SourceUnavailable,match="INVALID_HISTORICAL_FEED"):
        src.bars(days=30,symbols=("SPY",))


def test_repeated_token_and_duplicate_dates_are_rejected(tmp_path):
    def token_loop(url,headers):
        return json.dumps({"bars":{"SPY":[_bar("2026-11-11")]},
                           "next_page_token":"same"}).encode()
    src=LiveSources(tmp_path,fetch=token_loop,env=_env())
    with pytest.raises(SourceUnavailable,match="ALPACA_PAGINATION_INVALID"):
        src.bars(days=30,symbols=("SPY",),end_date="2026-11-13")
    def dup(url,headers):
        return json.dumps({"bars":{"SPY":[_bar("2026-11-11"),
                                           _bar("2026-11-11")]},
                           "next_page_token":None}).encode()
    src=LiveSources(tmp_path/"dup",fetch=dup,env=_env())
    with pytest.raises(SourceUnavailable,match="DUPLICATE_ALPACA_BARS"):
        src.bars(days=30,symbols=("SPY",),end_date="2026-11-13")


def test_future_bar_is_rejected(tmp_path):
    def future(url,headers):
        return json.dumps({"bars":{"SPY":[_bar("2026-11-16")]},
                           "next_page_token":None}).encode()
    src=LiveSources(tmp_path,fetch=future,env=_env())
    with pytest.raises(SourceUnavailable,match="BAR_OUTSIDE_REQUEST_WINDOW"):
        src.bars(days=30,symbols=("SPY",),end_date="2026-11-13")
