"""Synthetic offline regression for L1 V3 model persistence and daily state machine.

Synthetic OHLC exists ONLY in tests. Production models never fabricate market data.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from hashlib import sha256
import json
from pathlib import Path

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
    def __init__(self,raw,root=None):
        self.raw=raw
        self.root=root
        self.calls=[]
        self.fetched_at="2026-11-17T23:00:00Z"
    def bars(self,*,days,symbols,end_date,adjustment,refresh=False,
             preserve_source_evidence=False):
        end=date.fromisoformat(end_date)
        start=end-timedelta(days=days-1)
        records={sym:[r for r in self.raw[sym]
                      if start.isoformat()<=r["t"][:10]<=end_date]
                 for sym in symbols}
        self.calls.append((days,adjustment,end_date,tuple(symbols)))
        content=json.dumps({"bars":records},sort_keys=True,separators=(",",":")).encode()
        digest=sha256(content).hexdigest()
        receipt={"feed":"sip","adjustment":adjustment,
            "fetched_at":self.fetched_at,"sha256":digest,
            "start":start.isoformat(),"end":end_date,"page":1}
        if preserve_source_evidence:
            evidence=self.root/"outputs"/"l1_v3_source_evidence"/"sha256"/(digest+".json")
            evidence.parent.mkdir(parents=True,exist_ok=True)
            evidence.write_bytes(content)
            receipt["evidence_path"]=(Path("l1_v3_source_evidence")/"sha256"/(digest+".json")).as_posix()
        return records,[receipt]


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
    feed=StubAlpaca(daily_bars,root=tmp_path)
    feed.fetched_at="2026-11-13T22:00:00Z"
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
    feed.fetched_at="2026-11-16T23:00:00Z"
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
    feed.fetched_at="2026-11-13T22:00:00Z"
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


def test_split_bar_settlement_requires_real_source_window_and_retrieval_time():
    from quant_research.workflow.l1_v3_outcomes import _receipt_evidence
    due_after=datetime(2026,11,16,21,15,tzinfo=timezone.utc)
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as folder:
        root=Path(folder)
        raw=json.dumps({"bars":{"SPY":[
            {"t":"2026-11-16T05:00:00Z","o":100.,"c":100.2}
        ]}},sort_keys=True,separators=(",",":")).encode()
        digest=sha256(raw).hexdigest()
        rel=(Path("l1_v3_source_evidence")/"sha256"/(digest+".json")).as_posix()
        evidence=root/"outputs"/rel
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(raw)
        sample={"feed":"sip","adjustment":"split","sha256":digest,
                "start":"2026-11-02","end":"2026-11-16",
                "fetched_at":"2026-11-16T22:00:00Z","evidence_path":rel}
        result=_receipt_evidence([sample],root=root,entry_day="2026-11-16",
            exit_day="2026-11-16",asof_feed="sip",due_after=due_after,
            expected_entry_open=100,expected_exit_close=100.2)
        assert result["price_basis"]=="SPLIT_ADJUSTED_PRICE_RETURN"
        assert result["receipt_sha256"]==[digest]
        fake_digest="b"*64
        fake_rel=(Path("l1_v3_source_evidence")/"sha256"/(fake_digest+".json")).as_posix()
        fake_path=root/"outputs"/fake_rel
        fake_path.write_bytes(raw)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_RAW_EVIDENCE_HASH_MISMATCH"):
            _receipt_evidence([{**sample,"sha256":fake_digest,
                                "evidence_path":fake_rel}],root=root,
                entry_day="2026-11-16",exit_day="2026-11-16",
                asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_RAW_EVIDENCE_PRICE_MISMATCH"):
            _receipt_evidence([sample],root=root,entry_day="2026-11-16",
                exit_day="2026-11-16",asof_feed="sip",due_after=due_after,
                expected_entry_open=99,expected_exit_close=100.2)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_FEED_CHANGED"):
            _receipt_evidence([sample],root=root,entry_day="2026-11-16",
                exit_day="2026-11-16",asof_feed="iex",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
        with pytest.raises(ValueError,match="V3_PRICE_BASIS_NOT_SPLIT"):
            _receipt_evidence([{**sample,"adjustment":"raw"}],root=root,
                entry_day="2026-11-16",exit_day="2026-11-16",
                asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_BAR_FETCH_PREMATURE"):
            _receipt_evidence([{**sample,"fetched_at":"2026-11-16T20:00:00Z"}],
                root=root,entry_day="2026-11-16",exit_day="2026-11-16",
                asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
        altered=evidence.read_bytes()+b" "
        evidence.write_bytes(altered)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_RAW_EVIDENCE_HASH_MISMATCH"):
            _receipt_evidence([sample],root=root,entry_day="2026-11-16",
                exit_day="2026-11-16",asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
    with TemporaryDirectory() as folder:
        root=Path(folder)
        with pytest.raises(ValueError,match="V3_SETTLEMENT_RAW_EVIDENCE_MISSING"):
            _receipt_evidence([sample],root=root,entry_day="2026-11-16",
                exit_day="2026-11-16",asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)
    with TemporaryDirectory() as folder:
        root=Path(folder)
        raw=json.dumps({"bars":{"SPY":[]}},sort_keys=True,
                       separators=(",",":")).encode()
        digest=sha256(raw).hexdigest()
        rel=(Path("l1_v3_source_evidence")/"sha256"/(digest+".json")).as_posix()
        evidence=root/"outputs"/rel
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(raw)
        missing={**sample,"sha256":digest,"evidence_path":rel}
        with pytest.raises(ValueError,match="V3_SETTLEMENT_RAW_EVIDENCE_PRICE_MISSING_OR_DUPLICATE"):
            _receipt_evidence([missing],root=root,entry_day="2026-11-16",
                exit_day="2026-11-16",asof_feed="sip",due_after=due_after,
                expected_entry_open=100,expected_exit_close=100.2)


def test_pipeline_rejects_source_receipt_after_freeze(tmp_path,daily_bars):
    feed=StubAlpaca(daily_bars)
    with pytest.raises(SourceUnavailable,match="V3_SOURCE_RECEIPT_AFTER_FREEZE"):
        run_pipeline(tmp_path,mode="daily",sources=feed,
            now=datetime(2026,11,13,22,30,tzinfo=timezone.utc))
    assert frozen_for_session(tmp_path,"2026-11-13") is None


def test_source_receipt_time_must_be_timezone_aware():
    from quant_research.workflow.l1_v3_pipeline import _validate_receipt_times
    frozen_at=datetime(2026,11,13,22,30,tzinfo=timezone.utc)
    with pytest.raises(SourceUnavailable,match="V3_SOURCE_RECEIPT_TIME_INVALID"):
        _validate_receipt_times([{"fetched_at":"2026-11-13T22:00:00"}],frozen_at)


def test_valid_earlier_source_receipt_passes_freeze_gate():
    from quant_research.workflow.l1_v3_pipeline import _validate_receipt_times
    _validate_receipt_times([{"fetched_at":"2026-11-13T22:30:00Z"}],
        datetime(2026,11,13,22,30,tzinfo=timezone.utc))


def test_model_aging_is_explicit(trained):
    model,_,_,_=trained
    assert should_retrain(model,"2026-12-31")
    assert not should_retrain(model,"2026-11-16")
