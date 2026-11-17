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
