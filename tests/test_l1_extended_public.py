"""Offline contracts for expanded official + bounded sample feeds.

All figures in fixtures are artificial; tests do not attest live vendor data.
"""
from datetime import datetime, date, timedelta, timezone
from urllib.parse import urlparse, parse_qs
import json

import pytest

from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.data.l1_public_extended import (
    EQUITY_SAMPLE, SAMPLE_ID, parse_cboe_options, parse_ofr_stress_csv,
    parse_bls_calendar, parse_cftc_contract, parse_cboe_equities_volume,
    sample_stock_breadth, scan_extended_public,
    parse_ici_weekly_etf_issuance, parse_finra_consolidated_short_volume,
    parse_fomc_calendar, parse_fred_observations,
)

CLOCK = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
CBOE = json.dumps({
    "ratios": [
        {"name": "TOTAL PUT/CALL RATIO", "value": "0.96"},
        {"name": "INDEX PUT/CALL RATIO", "value": "1.15"},
        {"name": "EQUITY PUT/CALL RATIO", "value": "0.50"},
        {"name": "EXCHANGE TRADED PRODUCTS PUT/CALL RATIO", "value": "1.00"},
    ],
    "SUM OF ALL PRODUCTS":[{"name":"VOLUME","call":100,"put":96,"total":196}],
    "INDEX OPTIONS":[{"name":"VOLUME","call":100,"put":115,"total":215}],
    "EQUITY OPTIONS":[{"name":"VOLUME","call":200,"put":100,"total":300}],
    "EXCHANGE TRADED PRODUCTS":[{"name":"VOLUME","call":100,"put":100,"total":200}],
    "SPX + SPXW":[{"name":"OPEN INTEREST","call":200,"put":240,"total":440}],
}).encode()
FSI = b"Date,OFR FSI,Credit,Funding\n2026-11-11,-1.90,-0.30,-0.40\n"
BLS = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
DTSTART;TZID=America/New_York:20261117T083000\r
SUMMARY:Consumer Price Index\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;TZID=America/New_York:20261120T100000\r
SUMMARY:State Employment and Unemployment\r
END:VEVENT\r
END:VCALENDAR\r
"""
ICI = ("""<html><body><h1>Release: Estimated ETF Net Issuance</h1>
<p>Washington, DC; November 10, 2026—The estimated value of all exchange-traded
fund (ETF) shares issued exceeded that of shares redeemed by $49.83 billion
for the week ended November 4, 2026, the Investment Company Institute reported today.</p>
</body></html>""").encode()
FINRA = ("""Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20261113|SPY|600|50|1000|Q
20261113|SPY|250|20|500|N
20261113|QQQ|300|30|750|N
20261113|IWM|220|10|400|B
20261113|AAPL|300|20|700|Q
1
""").encode()
CFTC_NASDAQ = json.dumps([{
    "cftc_contract_market_code":"20974A",
    "report_date_as_yyyy_mm_dd":"2026-11-10T00:00:00",
    "open_interest_all":"100000","lev_money_positions_long":"20000",
    "lev_money_positions_short":"35000",
}]).encode()
def _commodity(code):
    return json.dumps([{
        "cftc_contract_market_code":code,
        "report_date_as_yyyy_mm_dd":"2026-11-10T00:00:00",
        "open_interest_all":"200000","m_money_positions_long_all":"70000",
        "m_money_positions_short_all":"50000",
    }]).encode()
MARKET_VOLUME=(
    "Day,Market Participant,Total Notional\n"+
    "".join(f"2026-11-13,{name},{v}\n" for name,v in [
        ("NYSE",100),("NASDAQ",200),("FINRA / NYSE TRF",300),
        ("NYSE Arca",70),("BZX",80),("IEX",90),("FINRA / Nasdaq TRF",100),
        ("EDGX",60)
    ])
).encode()


def fake_stock_bars():
    days=[]
    start=date(2026,10,1)
    for i in range(50):
        d=start+timedelta(days=i)
        if d.weekday()<5 and d<=date(2026,11,13):
            days.append(d)
    assert len(days)>=21 and days[-1]==date(2026,11,13)
    out={}
    for k,sym in enumerate(EQUITY_SAMPLE):
        out[sym]=[{"t":d.isoformat()+"T21:00:00Z",
                   "c":100+i+k*.1, "h":101+i+k*.1,
                   "l":99+i+k*.1,"o":100+i+k*.1,"v":1000}
                  for i,d in enumerate(days)]
    return out


def fake_source(tmp_path,broken=None,with_stocks=True):
    calls=[]
    def fetch(url,headers):
        calls.append(url)
        if broken and broken in url:
            raise SourceUnavailable("HTTP_503")
        p=urlparse(url)
        if p.path.endswith("/v2/assets"):
            return json.dumps([
                {"symbol":f"BRD{i:03d}","class":"us_equity","status":"active",
                 "tradable":True,"exchange":"NYSE"} for i in range(40)
            ]).encode()
        if p.path.endswith("/stocks/snapshots"):
            symbols=parse_qs(p.query).get("symbols",[""])[0].split(",")
            snapshots={}
            for i,symbol in enumerate(symbols):
                snapshots[symbol]={
                    "dailyBar":{"t":"2026-11-13T21:00:00Z",
                                "c":101 if i%2==0 else 99,"v":1000},
                    "prevDailyBar":{"t":"2026-11-12T21:00:00Z","c":100},
                }
            return json.dumps({"snapshots":snapshots}).encode()
        if p.path.endswith("_daily_options"):
            return CBOE
        if p.path.endswith("/fsi.csv"):
            return FSI
        if p.path.endswith("/bls.ics"):
            return BLS
        if p.path.endswith("/72hh-3qpy.json"):
            return _commodity("088691" if "088691" in url else "067651")
        if p.path.endswith("/gpe5-46if.json"):
            return CFTC_NASDAQ
        if p.path.endswith("/market_history_2026.csv"):
            return MARKET_VOLUME
        if p.path.endswith("/etf_flows"):
            return ICI
        if "CNMSshvol" in p.path:
            return FINRA
        if p.path.endswith("/stocks/bars"):
            if not with_stocks:
                raise SourceUnavailable("MISSING_ALPACA_CREDENTIALS")
            return json.dumps({"bars":fake_stock_bars(),"next_page_token":None}).encode()
        raise AssertionError("unexpected endpoint "+url)
    env={"ALPACA_API_KEY":"public-test-key","ALPACA_SECRET_KEY":"fixture",
         "QDR_L1_FEED":"delayed_sip"} if with_stocks else {}
    return LiveSources(tmp_path,fetch=fetch,env=env,now=lambda:CLOCK),calls


def test_parsers_cboe_ofr_bls_cftc_and_market_volume():
    opts=parse_cboe_options(CBOE)
    assert opts["cboe_pcr_total"]==.96
    assert opts["cboe_spx_put_call_oi"]==1.2
    assert parse_ofr_stress_csv(FSI)["2026-11-11"]["ofr_fsi"]==-1.9
    events=parse_bls_calendar(BLS)
    assert len(events)==2
    assert events[0]["dt"].isoformat()=="2026-11-17T13:30:00+00:00"
    assert parse_cftc_contract(CFTC_NASDAQ,"20974A")["2026-11-10"]["net_pct_oi"]==-15.0
    assert parse_cftc_contract(_commodity("088691"),"088691",trader="managed")["2026-11-10"]["net_pct_oi"]==10.0
    volume=parse_cboe_equities_volume(MARKET_VOLUME)["2026-11-13"]
    assert round(volume["cboe_trf_notional_share"],1)==40.0



def test_ici_weekly_and_finra_short_volume_contracts():
    weekly=parse_ici_weekly_etf_issuance(ICI)
    row=weekly["2026-11-04"]
    assert row["ici_weekly_etf_net_issuance_bn_usd"]==49.83
    assert row["source_published_date"]=="2026-11-10"
    short=parse_finra_consolidated_short_volume(FINRA)
    assert round(short["2026-11-13"]["finra_spy_short_volume_pct"],2)==56.67
    assert short["2026-11-13"]["finra_qqq_short_volume_pct"]==40.0
    # ShortVolume ALREADY includes ShortExempt, so adding exempt again is wrong.
    with pytest.raises(SourceUnavailable,match="FINRA_VOLUME_INCONSISTENT"):
        parse_finra_consolidated_short_volume(
            FINRA.replace(b"|600|50|1000|",b"|600|900|1000|"))
    with pytest.raises(SourceUnavailable):
        parse_ici_weekly_etf_issuance(b"<html>not a real weekly release</html>")

def test_sample_breadth_is_explicitly_limited():
    sample=sample_stock_breadth(fake_stock_bars(),"2026-11-13")
    assert len(EQUITY_SAMPLE)==30 and SAMPLE_ID.endswith("30_V1")
    assert sample["stock_sample_valid_count"]==30
    assert sample["stock_sample_advance_share"]==100.0
    assert sample["stock_sample_above_ma20_share"]==100.0
    assert sample["stock_sample_new_high20_count"]==30
    with pytest.raises(SourceUnavailable,match="INSUFFICIENT"):
        sample_stock_breadth({"AAPL":fake_stock_bars()["AAPL"]},"2026-11-13")


def test_strict_invalid_data_fails_closed():
    with pytest.raises(SourceUnavailable,match="CBOE_RATIO"):
        parse_cboe_options(CBOE.replace(b'"0.96"',b'"9.96"'))
    with pytest.raises(SourceUnavailable):
        parse_cboe_options(b'{"ratios":[]}')
    with pytest.raises(SourceUnavailable):
        parse_ofr_stress_csv(b'Date,Meaningless\n2026-11-11,4.0\n')
    with pytest.raises(SourceUnavailable):
        parse_bls_calendar(b'BEGIN:VCALENDAR\nEND:VCALENDAR')
    with pytest.raises(SourceUnavailable):
        parse_cftc_contract(CFTC_NASDAQ,"NONEXISTENT")


def test_extended_scan_and_short_lived_cache(tmp_path):
    src,calls=fake_source(tmp_path)
    a=scan_extended_public(tmp_path,sources=src,now=CLOCK)
    b=scan_extended_public(tmp_path,sources=src,now=CLOCK)
    assert a["schema"]=="qdr.l1.extended.v1"
    assert a["asof_session"]=="2026-11-13"
    assert a["historical_pit_verified"] is False
    assert a["not_in_model_scores"] is True
    values={x["id"]:x for x in a["features"]}
    assert values["cboe_pcr_total"]["value"]==.96
    assert values["ofr_fsi"]["value"]==-1.9
    assert values["bls_scheduled_next_7d"]["value"]==2
    assert values["cftc_nasdaq_net_pct_oi"]["value"]==-15.0
    assert values["cftc_gold_net_pct_oi"]["value"]==10.0
    assert values["stock_sample_advance_share"]["value"]==100.0
    assert values["cboe_trf_notional_share"]["value"]==40.0
    assert len(a["calendar_events"])==2
    assert values["ici_weekly_etf_net_issuance_bn_usd"]["value"]==49.83
    assert values["ici_weekly_etf_net_issuance_bn_usd"]["published_date"]=="2026-11-10"
    assert round(values["finra_spy_short_volume_pct"]["value"],2)==56.67
    assert a["features"]==b["features"] and len(calls)==12
    cache=list((tmp_path/"data"/"cache"/"l1_on_demand").glob("*.json"))
    assert len(cache)==12 and sum(x.stat().st_size for x in cache)<32_000_000


def test_isolated_feed_failure_and_no_alpaca_credentials(tmp_path):
    src,_=fake_source(tmp_path,broken="fsi.csv",with_stocks=False)
    value=scan_extended_public(tmp_path,sources=src,now=CLOCK)
    assert value["source_health"]["ofr_fsi"]["code"]=="HTTP_503"
    assert value["source_health"]["stock_sample"]["code"]=="MISSING_ALPACA_CREDENTIALS"
    assert value["source_health"]["cboe_options"]["status"]=="OBSERVED"
    assert not any(x["id"]=="ofr_fsi" for x in value["features"])
    assert not any(x["domain"]=="breadth" for x in value["features"])


def test_cftc_does_not_use_pre_release_positions(tmp_path):
    src,_=fake_source(tmp_path,with_stocks=False)
    before=datetime(2026,11,13,21,30,tzinfo=timezone.utc)
    value=scan_extended_public(tmp_path,sources=src,now=before)
    assert value["source_health"]["cftc_nasdaq"]["status"]=="MISSING"
    assert not any(x["id"]=="cftc_nasdaq_net_pct_oi" for x in value["features"])


def test_unknown_destination_is_refused(tmp_path):
    src,_=fake_source(tmp_path)
    with pytest.raises(SourceUnavailable,match="UNAPPROVED_SOURCE"):
        src.request("https://example.org/bad.json")


def test_broad_market_breadth_uses_full_active_asset_snapshot_coverage():
    from quant_research.data.l1_public_extended import ExtendedPublicSources

    class FakeLive:
        def assets(self, refresh=False):
            assets=[{"symbol":f"STK{i:03d}"} for i in range(40)]
            return assets,{"sha256":"a"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}

        def snapshots_for_symbols(self, symbols, refresh=False, batch_size=200, max_workers=4):
            snapshots={}
            for i,symbol in enumerate(symbols):
                daily={"t":"2026-11-17T04:00:00Z","c":101 if i<20 else 99,"v":1000}
                previous={"t":"2026-11-16T04:00:00Z","c":100}
                snapshots[symbol]={"dailyBar":daily,"prevDailyBar":previous}
            receipts=[{"sha256":"b"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}]
            return snapshots,receipts,[]

    provider=ExtendedPublicSources(FakeLive())
    values,receipt=provider.market_breadth("2026-11-17",
        now=__import__("datetime").datetime.fromisoformat("2026-11-17T22:30:00+00:00"))
    row=values["2026-11-17"]
    assert row["coverage_n"]==40 and row["expected_n"]==40
    assert row["advances"]==20 and row["declines"]==20
    assert row["advance_share"]==50
    assert row["observation_mode"]=="COMPLETED_DAILY_BAR"
    assert receipt["pit"]=="CURRENT_ACTIVE_ASSET_UNIVERSE_NOT_HISTORICAL_PIT"
    assert len(receipt["sha256"])==64


def test_broad_market_breadth_does_not_call_a_partial_snapshot_full_coverage():
    from quant_research.data.l1_public_extended import ExtendedPublicSources

    class FakeLive:
        def assets(self, refresh=False):
            assets=[{"symbol":f"STK{i:03d}"} for i in range(100)]
            return assets,{"sha256":"c"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}

        def snapshots_for_symbols(self, symbols, refresh=False, batch_size=200, max_workers=4):
            snapshots={}
            for i,symbol in enumerate(symbols[:60]):
                snapshots[symbol]={"dailyBar":{"t":"2026-11-17T04:00:00Z","c":101,"v":100},
                                   "prevDailyBar":{"t":"2026-11-16T04:00:00Z","c":100}}
            return snapshots,[{"sha256":"d"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}],[{"code":"HTTP_403"}]

    provider=ExtendedPublicSources(FakeLive())
    values,receipt=provider.market_breadth("2026-11-17",
        now=__import__("datetime").datetime.fromisoformat("2026-11-17T22:30:00+00:00"))
    row=values["2026-11-17"]
    assert row["coverage_n"]==60 and row["expected_n"]==100
    assert row["market_snapshot_coverage_pct"]==60
    assert row["batch_error_count"]==1


def test_alpaca_asset_directory_and_batched_snapshots_are_bounded(tmp_path):
    calls=[]
    def fetch(url,headers):
        calls.append(url)
        p=urlparse(url)
        if p.path.endswith("/v2/assets"):
            assets=[{"symbol":f"SYM{i:03d}","class":"us_equity","status":"active",
                     "tradable":True,"exchange":"NYSE"} for i in range(205)]
            assets.extend([
                {"symbol":"INACTIVE","class":"us_equity","status":"inactive","tradable":True,"exchange":"NYSE"},
                {"symbol":"OTC1","class":"us_equity","status":"active","tradable":True,"exchange":"OTC"},
            ])
            return json.dumps(assets).encode()
        if p.path.endswith("/stocks/snapshots"):
            symbols=parse_qs(p.query)["symbols"][0].split(",")
            return json.dumps({"snapshots":{x:{"dailyBar":{"t":"2026-11-13T21:00:00Z","c":100,"v":1},
                "prevDailyBar":{"t":"2026-11-12T21:00:00Z","c":99}} for x in symbols}}).encode()
        raise AssertionError(url)
    source=LiveSources(tmp_path,fetch=fetch,
        env={"ALPACA_API_KEY":"fixture","ALPACA_SECRET_KEY":"fixture"},
        now=lambda:CLOCK)
    assets,asset_receipt=source.assets()
    snapshots,receipts,errors=source.snapshots_for_symbols(
        [x["symbol"] for x in assets],batch_size=100)
    assert len(assets)==205
    assert asset_receipt["asset_count"]==205
    assert len(snapshots)==205
    assert len(receipts)==3 and errors==[]
    assert len(calls)==4

def test_broad_market_breadth_preserves_asset_receipt_when_all_snapshot_batches_fail():
    from quant_research.data.l1_public_extended import ExtendedPublicSources

    class FakeLive:
        def assets(self, refresh=False):
            assets=[{"symbol":f"STK{i:03d}"} for i in range(120)]
            return assets,{"sha256":"e"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}

        def snapshots_for_symbols(self, symbols, refresh=False, batch_size=200, max_workers=4):
            raise SourceUnavailable("ALL_ALPACA_SNAPSHOT_BATCHES_FAILED")

    provider=ExtendedPublicSources(FakeLive())
    values,receipt=provider.market_breadth("2026-11-17",
        now=__import__("datetime").datetime.fromisoformat("2026-11-17T22:30:00+00:00"))
    row=values["2026-11-17"]
    assert row["coverage_n"]==0 and row["expected_n"]==120
    assert row["observation_mode"]=="NO_SNAPSHOT_DATA"
    assert row["snapshot_error_code"]=="ALL_ALPACA_SNAPSHOT_BATCHES_FAILED"
    assert receipt["input_receipts"]==["e"*64]
    assert receipt["coverage"]==0


def test_broad_market_breadth_retains_low_nonzero_coverage_as_partial_evidence():
    from quant_research.data.l1_public_extended import ExtendedPublicSources

    class FakeLive:
        def assets(self, refresh=False):
            assets=[{"symbol":f"STK{i:03d}"} for i in range(100)]
            return assets,{"sha256":"f"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}

        def snapshots_for_symbols(self, symbols, refresh=False, batch_size=200, max_workers=4):
            snapshots={}
            for symbol in symbols[:20]:
                snapshots[symbol]={
                    "dailyBar":{"t":"2026-11-17T04:00:00Z","c":101,"v":100},
                    "prevDailyBar":{"t":"2026-11-16T04:00:00Z","c":100},
                }
            return snapshots,[{"sha256":"1"*64,"fetched_at":"2026-11-17T22:30:00+00:00"}],[]

    provider=ExtendedPublicSources(FakeLive())
    values,_=provider.market_breadth("2026-11-17",
        now=__import__("datetime").datetime.fromisoformat("2026-11-17T22:30:00+00:00"))
    row=values["2026-11-17"]
    assert row["coverage_n"]==20 and row["expected_n"]==100
    assert row["market_snapshot_coverage_pct"]==20
    assert row["advances"]==20

FOMC_HTML = ("""<html><body>
<h3>2026 FOMC Meetings</h3>
<p>January</p><p>27-28</p>
<p>March</p><p>17-18*</p>
<p>December</p><p>8-9*</p>
<h3>2027 FOMC Meetings</h3>
<p>January</p><p>26-27</p>
<p>March</p><p>16-17</p>
<p>November</p><p>16-17</p>
<p>Note: A two-day meeting is scheduled for January 25-26, 2028.</p>
<p>Last Update: November 12, 2026</p>
</body></html>""").encode()


def test_fomc_calendar_parser_preserves_page_update_vintage():
    events=parse_fomc_calendar(FOMC_HTML)
    by_id={x["event_id"]:x for x in events}
    assert "FOMC|2026-12-08" in by_id
    assert "FOMC|2027-01-26" in by_id
    assert "FOMC|2028-01-25" not in by_id
    assert by_id["FOMC|2026-12-08"]["schedule_known_at"] == datetime(
        2026,11,12,23,59,59,tzinfo=timezone.utc)


def test_scan_extended_public_emits_fomc_feature_and_event(monkeypatch,tmp_path):
    import quant_research.data.l1_public_extended as module

    event={
        "event_id":"FOMC|2026-12-08","name":"FOMC Meeting 2026-12-08",
        "event_type":"FOMC",
        "dt":datetime(2026,12,8,23,59,59,tzinfo=timezone.utc),
        "schedule_known_at":datetime(2026,11,12,23,59,59,tzinfo=timezone.utc),
        "published_date":"2026-11-12",
    }
    receipt={
        "source":"FED_FOMC_CALENDAR","fetched_at":"2026-11-17T22:30:00+00:00",
        "sha256":"a"*64,"pit":"CURRENT_PUBLISHED_SCHEDULE_NOT_HISTORICAL_PIT",
        "published_date":"2026-11-12",
    }

    class FakeProvider:
        def __init__(self,live): pass
        def fomc_calendar(self,refresh=False): return [event],receipt
        def fred_cross_asset(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def cboe_options(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def ofr_fsi(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def bls_calendar(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def cftc_nasdaq(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def cftc_commodity(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def cboe_equity_volume(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def stock_breadth(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def market_breadth(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def ici_weekly_etf(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")
        def finra_short_volume(self,*args,**kwargs): raise SourceUnavailable("OFFLINE")

    monkeypatch.setattr(module,"ExtendedPublicSources",FakeProvider)
    result=module.scan_extended_public(tmp_path,sources=object(),
        now=datetime(2026,11,17,22,30,tzinfo=timezone.utc))
    fomc=next(x for x in result["features"] if x["id"]=="days_to_fomc")
    assert fomc["value"]==21
    assert fomc["pit"]=="CURRENT_PUBLISHED_EVENT_SCHEDULE_NOT_HISTORICAL_PIT"
    assert result["source_health"]["fomc_calendar"]["status"]=="OBSERVED"
    assert result["calendar_events"][0]["schedule_known_at"]=="2026-11-12T23:59:59+00:00"

def test_fred_observation_parser_ignores_missing_values_and_preserves_vintage():
    body=json.dumps({"observations":[
        {"date":"2026-11-16","value":"2.10","realtime_start":"2026-11-17",
         "realtime_end":"9999-12-31"},
        {"date":"2026-11-17","value":".","realtime_start":"2026-11-17",
         "realtime_end":"9999-12-31"},
    ]}).encode()
    rows=parse_fred_observations(body,"T10YIE")
    assert len(rows)==1
    assert rows[0]["date"]=="2026-11-16"
    assert rows[0]["value"]==2.10
    assert rows[0]["realtime_start"]=="2026-11-17"


def test_fred_cross_asset_fetches_asof_vintage_and_computes_broad_usd_proxy():
    import hashlib
    from quant_research.data.l1_public_extended import ExtendedPublicSources,FRED_SERIES

    days=["2026-11-10","2026-11-11","2026-11-12","2026-11-13","2026-11-16","2026-11-17"]
    class FakeLive:
        env={"FRED_API_KEY":"x"*32}
        def request(self,endpoint,params,ttl=1800,refresh=False,feed=""):
            assert endpoint=="https://api.stlouisfed.org/fred/series/observations"
            assert params["realtime_start"]=="2026-11-17"
            assert params["realtime_end"]=="2026-11-17"
            series=params["series_id"]
            if series=="DFII10":
                values=[{"date":"2026-11-17","value":"1.75"}]
            elif series=="T10YIE":
                values=[{"date":"2026-11-17","value":"2.35"}]
            elif series=="BAMLH0A0HYM2":
                values=[{"date":"2026-11-17","value":"3.05"}]
            else:
                values=[{"date":day,"value":str(100+i*0.2)}
                        for i,day in enumerate(days)]
            body=json.dumps({"observations":[
                {**x,"realtime_start":"2026-11-17","realtime_end":"9999-12-31"}
                for x in values
            ]}).encode()
            return body,"2026-11-17T22:30:00+00:00",hashlib.sha256(series.encode()).hexdigest()

    values,receipt=ExtendedPublicSources(FakeLive()).fred_cross_asset("2026-11-17")
    row=values["2026-11-17"]
    assert row["real_yield_10y"]["value"]==1.75
    assert row["breakeven_10y"]["value"]==2.35
    assert row["hy_oas"]["value"]==305.0
    assert row["dxy_return_5"]["value"]==pytest.approx(1.0)
    assert row["dxy_return_5"]["proxy"]=="DTWEXBGS_BROAD_TRADE_WEIGHTED_USD_NOT_DXY"
    assert receipt["coverage_n"]==4
    assert receipt["pit"]=="ALFRED_ASOF_CURRENT_SESSION_NOT_FULL_HISTORICAL_ARCHIVE"
    assert len(receipt["input_receipts"])==4
