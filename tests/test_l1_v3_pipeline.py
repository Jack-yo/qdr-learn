"""Synthetic offline regression for L1 V3 model persistence and daily state machine.

Synthetic OHLC exists ONLY in tests. Production models never fabricate market data.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json

import numpy as np
import pandas as pd
import pytest

from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.workflow.l1_v3_persist import (
    build_model_bundle,save_model_bundle,read_model_bundle,
    find_model_bundle,should_retrain,infer_market_from_bundle,
    CORE_SYMBOLS,_validated_source_bars)
from quant_research.workflow.l1_v3_pipeline import (
    run_pipeline,latest_frozen,current_pipeline_status,
    frozen_for_session,_JobLock)


@pytest.fixture(scope="module")
def daily_bars():
    rng=np.random.default_rng(10491)
    days=pd.bdate_range(end="2026-11-17",periods=1380)
    current={sym:150. if sym!="SPY" else 330. for sym in CORE_SYMBOLS}
    raw={sym:[] for sym in CORE_SYMBOLS}
    for t,day in enumerate(days):
        market=rng.normal(.00015,.012)
        for sym in CORE_SYMBOLS:
            r=(market*(1. if sym=="SPY" else 1.1 if sym=="IWM" else .87
               if sym=="RSP" else .35 if sym=="HYG" else -.15)
               +rng.normal(0,.003 if sym in ("SPY","IWM","RSP") else .001))
            o=current[sym]*(1+rng.normal(0,.001))
            c=current[sym]*(1+r)
            raw[sym].append({"t":day.strftime("%Y-%m-%dT05:00:00Z"),
                "o":o,"h":max(o,c)*1.003,"l":min(o,c)*.997,
                "c":c,"v":1_000_000+t})
            current[sym]=c
    return raw


class StubAlpaca:
    def __init__(self,raw):
        self.raw=raw
        self.calls=[]
    def bars(self,*,days,symbols,end_date,adjustment,refresh=False):
        end=date.fromisoformat(end_date)
        start=end-timedelta(days=days-1)
        records={sym:[r for r in self.raw[sym]
                      if start.isoformat()<=r["t"][:10]<=end_date]
                 for sym in symbols}
        self.calls.append((days,adjustment,end_date,tuple(symbols)))
        content=json.dumps(records,sort_keys=True).encode()
        return records,[{"feed":"sip","adjustment":adjustment,
            "fetched_at":"2026-11-17T23:00:00Z",
            "sha256":sha256(content).hexdigest(),
            "start":start.isoformat(),"end":end_date,"page":1}]


@pytest.fixture(scope="module")
def trained(daily_bars):
    stub=StubAlpaca(daily_bars)
    bars,receipts=stub.bars(days=2500,symbols=CORE_SYMBOLS,
                            end_date="2026-11-13",adjustment="split")
    model=build_model_bundle(bars,receipts=receipts,asof="2026-11-13")
    return model,bars,receipts,stub


def test_persisted_coefficients_replay_actual_probabilities(tmp_path,trained):
    model,bars,receipts,stub=trained
    path=save_model_bundle(tmp_path,model)
    path_again=save_model_bundle(tmp_path,model)
    assert path==path_again
    loaded=read_model_bundle(tmp_path/path["path"])
    assert loaded==model
    _,ref=find_model_bundle(tmp_path,asof="2026-11-16")
    assert ref["model_sha256"]==path["model_sha256"]
    predicted=infer_market_from_bundle(
        bars,model=loaded,model_ref=ref,receipts=receipts,asof="2026-11-13")
    assert predicted["execution_eligible"] is False
    assert predicted["historical_pit_verified"] is False
    assert len(predicted["raw_observations"])>=7
    for h in ("1","3","5"):
        row=predicted["horizons"][h]
        p=row["research_estimates"]
        assert abs(sum(p.values())-1)<1e-5
        assert row["admitted_probabilities"] is None
        assert all("standardized" in x and "raw_value" in x
                   for x in row["trace"]["feature_inputs"])
        assert sum(x["up_logit_contribution"]
                   for x in row["trace"]["feature_inputs"])+row["trace"]["up_logit_intercept"] == pytest.approx(
                   row["trace"]["up_logit_sum"],abs=.0002)
    corrupt=tmp_path/path["path"]
    corrupt.write_text(corrupt.read_text()+" ",encoding="utf-8")
    with pytest.raises(SourceUnavailable,match="V3_MODEL_HASH_MISMATCH"):
        read_model_bundle(corrupt)


def test_daily_job_trains_once_then_loads_saved_model(tmp_path,daily_bars):
    feed=StubAlpaca(daily_bars)
    first=run_pipeline(tmp_path,mode="daily",sources=feed,
                now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))
    assert first["status"]=="FROZEN_RESEARCH_ONLY"
    assert sum(call[0]==2500 for call in feed.calls)==1
    assert frozen_for_session(tmp_path,"2026-11-13")
    model=find_model_bundle(tmp_path,asof="2026-11-13")
    assert model and model[0]["status"]=="RESEARCH_MODEL_ONLY"
    second=run_pipeline(tmp_path,mode="daily",sources=feed,
                now=datetime(2026,11,13,23,30,tzinfo=timezone.utc))
    assert second["status"]=="ALREADY_FROZEN"
    assert second["frozen_sha256"]==first["frozen_sha256"]
    assert sum(call[0]==2500 for call in feed.calls)==1
    nxt=run_pipeline(tmp_path,mode="daily",sources=feed,
                now=datetime(2026,11,16,23,30,tzinfo=timezone.utc),
                action_checker=lambda start,end:['a'*64])
    assert nxt["status"]=="FROZEN_RESEARCH_ONLY"
    assert sum(call[0]==2500 for call in feed.calls)==1
    assert any(call[0]==420 for call in feed.calls)
    assert nxt["model_sha256"]==first["model_sha256"]
    assert nxt["outcomes"]["new_outcomes"]>=1  # Friday H1 settled on Monday.
    latest=latest_frozen(tmp_path,
           now=datetime(2026,11,16,23,30,tzinfo=timezone.utc))
    assert latest["asof_session"]=="2026-11-16"
    assert latest["freshness_status"]=="CURRENT"
    status=current_pipeline_status(tmp_path,
           now=datetime(2026,11,16,23,30,tzinfo=timezone.utc))
    assert status["model_available"] and status["frozen_current"]
    assert status["settled_count_recent"]>=1


def test_legacy_on_demand_snapshots_do_not_count_as_daily_freezes(tmp_path,daily_bars):
    from quant_research.workflow.l1_v3 import save_research_snapshot
    feed=StubAlpaca(daily_bars)
    run_pipeline(tmp_path,mode="daily",sources=feed,
                 now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))
    frozen,_=frozen_for_session(tmp_path,"2026-11-13")
    frozen["snapshot_status"]="ON_DEMAND_NOT_DAILY_SCHEDULED"
    save_research_snapshot(tmp_path,frozen)
    frozen["notice"]="another legacy research snapshot"
    save_research_snapshot(tmp_path,frozen)
    assert frozen_for_session(tmp_path,"2026-11-13")[0]["snapshot_status"]=="IMMUTABLE_DAILY_FROZEN"
    assert run_pipeline(tmp_path,mode="daily",sources=feed,
                        now=datetime(2026,11,13,23,30,tzinfo=timezone.utc))["status"]=="ALREADY_FROZEN"


def test_no_model_or_frozen_predictions_are_fabricated(tmp_path):
    p=latest_frozen(tmp_path,
        now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))
    assert p["status"]=="NO_FROZEN_RESEARCH"
    assert p["horizons"]=={}
    status=current_pipeline_status(tmp_path,
        now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))
    assert status["model_available"] is False
    with _JobLock(tmp_path):
        with pytest.raises(SourceUnavailable,match="V3_JOB_ALREADY_RUNNING"):
            run_pipeline(tmp_path,mode="daily",sources=StubAlpaca({}),
                now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))


def test_data_completeness_blocks_stale_etf(daily_bars):
    feed=StubAlpaca(daily_bars)
    bars,receipts=feed.bars(days=420,symbols=CORE_SYMBOLS,
                           end_date="2026-11-13",adjustment="split")
    last=bars["HYG"].pop()
    with pytest.raises(SourceUnavailable,match="V3_STALE_CORE_ETF_BAR"):
        _validated_source_bars(bars,"2026-11-13")
    bars["HYG"].append(last)


def test_no_action_requires_hashed_complete_grouped_evidence(tmp_path,monkeypatch):
    from quant_research.workflow.l1_v3_pipeline import _check_no_actions
    import quant_research.data.providers.actions as action_module
    class StubProvider:
        def __init__(self,http): self.pages=[]
        def events(self,symbols,start,end):
            raw=json.dumps({'corporate_actions':self.groups,'next_page_token':None}).encode()
            digest=sha256(raw).hexdigest()
            folder=tmp_path/'data/raw/objects';folder.mkdir(parents=True,exist_ok=True)
            (folder/digest).write_bytes(raw)
            self.pages=[{'raw_sha256':digest}]
            return []
    monkeypatch.setattr(action_module,'ActionProvider',StubProvider)
    StubProvider.groups={}
    with pytest.raises(SourceUnavailable,match='V3_ACTION_COVERAGE_UNVERIFIED'):
        _check_no_actions(tmp_path,'2026-11-03','2026-11-04')
    StubProvider.groups={'dividend':[],'split':[]}
    with pytest.raises(SourceUnavailable,match='V3_ACTION_EX_DATE_COVERAGE_UNVERIFIED'):
        _check_no_actions(tmp_path,'2026-11-03','2026-11-04')


def test_model_aging_is_explicit(trained):
    model,_,_,_=trained
    assert should_retrain(model,"2026-12-31")
    assert not should_retrain(model,"2026-11-16")
