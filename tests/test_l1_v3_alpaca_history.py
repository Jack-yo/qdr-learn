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
    assert queries[0][1]["end"]==["2026-11-13T21:01:00+00:00"]
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


def test_sip_session_end_does_not_query_tomorrow_or_recent_window(tmp_path):
    """Daily requests must not ask for future midnight on free historical SIP."""
    seen=[]
    def fake(url,headers):
        query=parse_qs(urlsplit(url).query)
        seen.append(query)
        return json.dumps({"bars":{"SPY":[_bar("2026-11-16")]},
                           "next_page_token":None}).encode()
    early=LiveSources(tmp_path/"early",fetch=fake,env=_env(),
                      now=lambda:datetime(2026,11,16,21,16,tzinfo=timezone.utc))
    with pytest.raises(SourceUnavailable,match="HISTORICAL_SIP_EMBARGO_PENDING"):
        early.bars(days=30,symbols=("SPY",),end_date="2026-11-16",
                   adjustment="split")
    assert seen==[]  # No forbidden request is sent to Alpaca.
    ready=LiveSources(tmp_path/"ready",fetch=fake,env=_env(),
                      now=lambda:datetime(2026,11,16,21,20,tzinfo=timezone.utc))
    rows,receipts=ready.bars(days=30,symbols=("SPY",),end_date="2026-11-16",
                             adjustment="split")
    assert rows["SPY"][0]["t"].startswith("2026-11-16")
    assert seen[0]["end"]==["2026-11-16T21:01:00+00:00"]
    assert seen[0]["feed"]==["sip"]
    assert receipts[0]["end"]=="2026-11-16"


def test_implicit_history_end_uses_last_completed_session(tmp_path):
    seen=[]
    def fake(url,headers):
        seen.append(parse_qs(urlsplit(url).query))
        return json.dumps({"bars":{"SPY":[_bar("2026-11-16")]},
                           "next_page_token":None}).encode()
    source=LiveSources(tmp_path,fetch=fake,env=_env(),
                       now=lambda:datetime(2026,11,17,1,0,tzinfo=timezone.utc))
    source.bars(days=30,symbols=("SPY",),adjustment="split")
    assert seen[0]["end"]==["2026-11-16T21:01:00+00:00"]
    assert seen[0]["feed"]==["sip"]


def test_historical_source_rejects_unclosed_future_session(tmp_path):
    source=LiveSources(tmp_path,env=_env(),
                       now=lambda:datetime(2026,11,16,20,0,tzinfo=timezone.utc))
    with pytest.raises(SourceUnavailable,match="HISTORICAL_SESSION_NOT_CLOSED"):
        source.bars(days=30,symbols=("SPY",),end_date="2026-11-16")



def test_default_snapshot_covers_full_core_etf_basket(tmp_path):
    seen=[]
    def fake(url,headers):
        query=parse_qs(urlsplit(url).query)
        seen.append(query)
        symbols=query["symbols"][0].split(",")
        return json.dumps({"snapshots":{symbol:{} for symbol in symbols}}).encode()

    source=LiveSources(tmp_path,fetch=fake,env=_env())
    snapshots,receipt=source.snapshots()
    assert set(snapshots)==set(LiveSources.ETF_SYMBOLS)
    assert len(snapshots)==28
    assert seen[0]["feed"]==["delayed_sip"]
    assert set(seen[0]["symbols"][0].split(","))==set(LiveSources.ETF_SYMBOLS)
    assert receipt["source"]=="ALPACA_delayed_sip"


@pytest.mark.parametrize(
    ("operation","expected"),
    [
        ("bars","ALPACA_HISTORY_FEED_FORBIDDEN_SIP"),
        ("snapshots","ALPACA_SNAPSHOT_FEED_FORBIDDEN_DELAYED_SIP"),
    ],
)
def test_alpaca_forbidden_feed_returns_actionable_error(tmp_path,operation,expected):
    def forbidden(url,headers):
        from quant_research.data.l1_light_sources import SourceUnavailable
        raise SourceUnavailable("HTTP_403")

    source=LiveSources(tmp_path,fetch=forbidden,env=_env())
    with pytest.raises(SourceUnavailable,match=expected):
        if operation=="bars":
            source.bars(days=30,symbols=("SPY",),end_date="2026-11-13")
        else:
            source.snapshots(symbols=("SPY",))
