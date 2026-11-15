"""L1 V3 scenario probabilities, no-future-data gates and immutable audit contract.

Fixtures are deterministic synthetic OHLC bars ONLY for testing; never production.
"""
from datetime import datetime, timedelta, timezone
import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data.l1_light_sources import SourceUnavailable
from quant_research.workflow.l1_probability_v3 import (
    HORIZONS, _labels, _temperature_prob, _valid_indices,
    analyze_l1_v3, build_scores,
)
from quant_research.workflow.l1_v3 import (
    latest_completed_session, save_research_snapshot, recent_research_snapshots,
)


@pytest.fixture(scope="module")
def etf_bars():
    rng=np.random.default_rng(20261115)
    dates=pd.bdate_range("2020-01-01",periods=1430)
    rows=[]
    symbols=("SPY","RSP","IWM","HYG","LQD")
    prices={key:(310. if key=="SPY" else 110.) for key in symbols}
    for i,day in enumerate(dates):
        regime=.0015 if (i//110)%2==0 else -.0015
        market=float(np.clip(rng.normal(regime,.0095),-.055,.055))
        for symbol in symbols:
            if symbol=="SPY":ret=market
            elif symbol=="RSP":ret=market*.92+rng.normal(0,.0026)
            elif symbol=="IWM":ret=market*1.20+rng.normal(0,.004)
            elif symbol=="HYG":ret=market*.30+rng.normal(0,.0018)
            else:ret=-market*.17+rng.normal(0,.0019)
            start=prices[symbol]
            opening=float(start*(1+rng.normal(0,.0010)))
            ending=float(start*(1+ret))
            high=max(opening,ending)*1.003
            low=min(opening,ending)*.997
            rows.append({"date":day.date().isoformat(),"symbol":symbol,
                         "open":opening,"close":ending,"high":high,
                         "low":low,"volume":1000000.})
            prices[symbol]=ending
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def computed(etf_bars):
    return analyze_l1_v3(etf_bars,receipts=[{"sha256":"f"*64,
        "fetched_at":"2026-11-15T00:00:00+00:00","feed":"iex"}])


def test_three_horizons_have_real_trace_but_never_claim_certification(computed):
    d=computed
    assert d["schema"]=="qdr.l1.probability.v3"
    assert d["status"]=="RESEARCH_ONLY"
    assert d["historical_pit_verified"] is False
    assert d["execution_eligible"] is False
    assert set(d["horizons"])=={"1","3","5"}
    assert any(x["id"]=="SPY" and len(x["history"])==20
               for x in d["raw_observations"])
    for h in HORIZONS:
        row=d["horizons"][str(h)]
        assert row["status"]=="RESEARCH_ONLY"
        assert row["admitted_probabilities"] is None
        assert row["qualification"]["admitted"] is False
        assert "HISTORICAL_PIT_UNVERIFIED" in row["qualification"]["reasons"]
        p=row["research_estimates"]
        assert set(p)=={"UP","FLAT","DOWN"}
        assert all(0<=value<=1 for value in p.values())
        assert sum(p.values())==pytest.approx(1,abs=.00001)
        trace=row["trace"]
        assert len(trace["feature_inputs"])==7
        assert trace["up_logit_sum"]==pytest.approx(
            trace["up_logit_intercept"]+
            sum(v["up_logit_contribution"] for v in trace["feature_inputs"]),abs=.00009)
        assert row["calibration_samples"]>=110
        assert row["train_samples"]>=450
        assert len(row["trace_sha256"])==64
        assert row["validation"]["qualified"] is False
        assert row["validation"]["status"]=="RETROSPECTIVE_OOS_NOT_PIT_ATTESTED"


def test_split_never_learns_from_a_label_ending_on_or_after_origin():
    x=np.ones((60,7))
    y=np.arange(60)%3
    for h in (1,3,5):
        for cutoff in (15,22,40):
            idx=_valid_indices(x,y,h,cutoff,low=3)
            assert all(t+h<cutoff for t in idx)
            assert len(idx)>0


def test_labels_use_next_open_and_future_close_not_same_day(etf_bars):
    f,close,o,hi,lo=build_scores(etf_bars)
    for h in HORIZONS:
        y,returns,b=_labels(f,o,close,h)
        t=250
        expected=close["SPY"].iloc[t+h]/o["SPY"].iloc[t+1]-1
        assert returns[t]==pytest.approx(expected)
        assert .003<=b[t]<=.035
        assert y[t] in (0,1,2)
        assert y[len(f)-h]==-1  # Not yet completed by the final date.


def test_temperature_always_outputs_valid_complementary_categories():
    raw=np.array([[.65,.28,.07],[.15,.60,.25]])
    for t in (.75,1.,1.4,2.5):
        out=_temperature_prob(raw,t)
        assert np.all(np.isfinite(out))
        assert np.all(out>=0)
        assert np.allclose(out.sum(axis=1),1.0)
    assert np.allclose(_temperature_prob(raw,1),raw)


def test_no_future_market_bar_can_change_an_old_asof(etf_bars,computed):
    limit=etf_bars["date"].max()
    # Simulated extra future bars must be dropped when asking for the older asof.
    extra=etf_bars.loc[etf_bars["date"]==limit].copy()
    extra["date"]="2027-01-04"
    extra["close"]*=1000  # Would leak catastrophically if included.
    more=pd.concat([etf_bars,extra],ignore_index=True)
    old=analyze_l1_v3(more,asof_limit=limit,receipts=computed["source_receipts"])
    for h in HORIZONS:
        assert old["horizons"][str(h)]["trace_sha256"]==computed["horizons"][str(h)]["trace_sha256"]
        assert old["horizons"][str(h)]["research_estimates"]==computed["horizons"][str(h)]["research_estimates"]


def test_snapshot_idempotent_and_rejects_unqualified_promotion(tmp_path,computed):
    first=save_research_snapshot(tmp_path,computed)
    mutated=dict(computed,research_snapshot=first)
    again=save_research_snapshot(tmp_path,mutated)
    assert first["sha256"]==again["sha256"]
    assert len(list((tmp_path/"outputs"/"l1_v3_research").glob("*/*.json")))==1
    indexed=recent_research_snapshots(tmp_path)
    assert len(indexed)==1
    assert indexed[0]["status"]=="RESEARCH_ONLY"
    promoted=json.loads(json.dumps(computed))
    promoted["horizons"]["1"]["admitted_probabilities"]={"UP":.5,"FLAT":.3,"DOWN":.2}
    with pytest.raises(ValueError,match="forbidden"):
        save_research_snapshot(tmp_path,promoted)


def test_trading_clock_never_uses_an_incomplete_session():
    # On Friday Nov 13 2026 close is 21:00 UTC, +15 minutes delay.
    assert latest_completed_session(datetime(2026,11,13,21,45,tzinfo=timezone.utc))=="2026-11-13"
    assert latest_completed_session(datetime(2026,11,13,20,58,tzinfo=timezone.utc))=="2026-11-12"
    with pytest.raises(ValueError):
        latest_completed_session(datetime(2026,11,13,21,45))


def test_refuse_too_little_history_and_missing_core(etf_bars):
    tiny=etf_bars.loc[etf_bars["date"]<=sorted(etf_bars["date"].unique())[300]]
    with pytest.raises(SourceUnavailable,match="V3_NEEDS_LONGER_DAILY_HISTORY"):
        analyze_l1_v3(tiny)
    missing=etf_bars.loc[etf_bars["symbol"]!="HYG"]
    with pytest.raises(SourceUnavailable,match="MARKET_CORE_SYMBOLS_MISSING"):
        analyze_l1_v3(missing)
