"""Official-source L1 adapters: offline deterministic contracts; no live data invented."""
from datetime import datetime, timezone
import json
from urllib.parse import urlsplit

import pytest

from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable, BoundedCache
from quant_research.data.l1_official_sources import (
    OfficialL1Sources, parse_treasury_curve, parse_nyfed_rates,
    parse_cftc_tff, scan_official_l1,
)

CLOCK=datetime(2026,11,15,12,0,tzinfo=timezone.utc)
XML=b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
 xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices">
<entry><content><m:properties>
<d:NEW_DATE>2026-11-13T00:00:00</d:NEW_DATE>
<d:BC_2YEAR m:type="Edm.Double">3.62</d:BC_2YEAR>
<d:BC_10YEAR m:type="Edm.Double">4.14</d:BC_10YEAR>
</m:properties></content></entry></feed>"""
SOFR=json.dumps({"refRates":[{"effectiveDate":"2026-11-13","type":"SOFR",
                                "percentRate":3.92}]}).encode()
EFFR=json.dumps({"refRates":[{"effectiveDate":"2026-11-13","type":"EFFR",
                                "percentRate":3.89}]}).encode()
CFTC=json.dumps([{"cftc_contract_market_code":"13874A",
                   "market_and_exchange_names":"E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
                   "report_date_as_yyyy_mm_dd":"2026-11-10T00:00:00.000",
                   "open_interest_all":"1000000",
                   "lev_money_positions_long":"100000",
                   "lev_money_positions_short":"180000"}]).encode()


def _client(tmp_path, broken=None):
    calls=[]
    def fetch(url,headers):
        calls.append(url)
        path=urlsplit(url).path
        if broken and broken in url:
            raise SourceUnavailable("HTTP_503")
        if path.endswith("/xml"):return XML
        if path.endswith("/sofr/last/10.json"):return SOFR
        if path.endswith("/effr/last/10.json"):return EFFR
        if path.endswith("/gpe5-46if.json"):return CFTC
        raise AssertionError("Unexpected endpoint: "+url)
    src=LiveSources(tmp_path,fetch=fetch,env={},now=lambda:CLOCK)
    return src,calls


def test_parsers_units_and_strict_lookups():
    treasury=parse_treasury_curve(XML)
    assert treasury["2026-11-13"]["treasury_2y_pct"]==3.62
    assert treasury["2026-11-13"]["treasury_2s10s_bp"]==52.0
    assert parse_nyfed_rates(SOFR,"SOFR")["2026-11-13"]==3.92
    assert parse_cftc_tff(CFTC)["2026-11-10"]["cftc_emini_sp500_lev_net_pct_oi"]==-8.0
    with pytest.raises(SourceUnavailable):
        parse_treasury_curve(b"<html>Not an XML feed</html>")
    with pytest.raises(SourceUnavailable):
        parse_cftc_tff(b"[{}]")
    with pytest.raises(SourceUnavailable):
        parse_nyfed_rates(EFFR,"SOFR")


def test_scan_independent_feeds_and_bounded_cache(tmp_path):
    client,calls=_client(tmp_path)
    first=scan_official_l1(tmp_path,sources=client,now=CLOCK)
    second=scan_official_l1(tmp_path,sources=client,now=CLOCK)
    assert first["schema"]=="qdr.l1.official.v1"
    assert first["status"]=="OBSERVATION_ONLY"
    assert first["asof_session"]=="2026-11-13"
    assert first["historical_pit_verified"] is False
    assert first["not_in_model_scores"] is True
    by_id={x["id"]:x for x in first["features"]}
    assert by_id["treasury_2s10s_bp"]["value"]==52.
    assert by_id["nyfed_sofr_minus_effr_bp"]["value"]==3.
    assert by_id["cftc_emini_sp500_lev_net_pct_oi"]["value"]==-8.
    assert by_id["cftc_emini_sp500_lev_net_pct_oi"]["domain"]=="positioning"
    assert by_id["treasury_2y_pct"]["domain"]=="cross_asset"
    assert by_id["nyfed_sofr"]["domain"]=="funding"
    assert len(calls)==4
    assert first["features"]==second["features"]
    cache=list((tmp_path/"data"/"cache"/"l1_on_demand").glob("*.json"))
    assert len(cache)==4
    assert sum(p.stat().st_size for p in cache)<32_000_000


def test_provider_error_does_not_block_healthy_sources(tmp_path):
    src,_=_client(tmp_path,broken="cftc")
    res=scan_official_l1(tmp_path,sources=src,now=CLOCK)
    assert res["source_health"]["cftc_sp500"]["status"]=="MISSING"
    assert res["source_health"]["cftc_sp500"]["code"]=="HTTP_503"
    assert any(x["id"]=="nyfed_sofr" for x in res["features"])
    assert not any(x["domain"]=="positioning" for x in res["features"])


def test_cot_not_present_before_conservative_friday_release(tmp_path):
    src,_=_client(tmp_path)
    before=datetime(2026,11,13,21,20,tzinfo=timezone.utc)
    res=scan_official_l1(tmp_path,sources=src,now=before)
    assert res["source_health"]["cftc_sp500"]["status"]=="MISSING"
    assert not any(x["domain"]=="positioning" for x in res["features"])


def test_refuse_future_or_unknown_public_source(tmp_path):
    src,_=_client(tmp_path)
    with pytest.raises(ValueError):
        scan_official_l1(tmp_path,sources=src,now=CLOCK,asof="2026-11-16")
    with pytest.raises(SourceUnavailable,match="UNAPPROVED_SOURCE"):
        src.request("https://example.org/hostile",refresh=True)
