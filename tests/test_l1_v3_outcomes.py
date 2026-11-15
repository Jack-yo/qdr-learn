"""Forward research settlements are strictly due-date scoped and append-only."""
from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
from quant_research.clock import TradingClock
from quant_research.workflow.l1_v3 import save_research_snapshot
from quant_research.workflow.l1_v3_outcomes import (
    settle_due_research, recent_v3_outcomes,
)
from quant_research.workflow.l1_v3_scorecard import forward_scorecard


def _fixture(clock):
    sessions=clock.calendar.sessions
    asof=clock.session("2026-11-02")
    idx=sessions.get_loc(asof)
    window=sessions[idx:idx+8]
    bars=pd.DataFrame([
        {"date":stamp.date().isoformat(),"symbol":"SPY",
         "open":100.+i,"close":100.2+i,"high":101.2+i,"low":99.0+i,
         "volume":1000000}
        for i,stamp in enumerate(window)
    ])
    frozen={
        "schema":"qdr.l1.probability.v3","status":"RESEARCH_ONLY",
        "historical_pit_verified":False,"execution_eligible":False,
        "asof_session":asof.date().isoformat(),
        "model_version":"L1_V3_ETF7.1",
        "source_receipts":[{"sha256":"f"*64,"fetched_at":"2026-11-02T22:00:00Z"}],
        "horizons":{
            str(h):{"horizon":h,"status":"RESEARCH_ONLY",
                    "research_estimates":{"UP":.35,"FLAT":.45,"DOWN":.20},
                    "baseline_probabilities":{"UP":.30,"FLAT":.40,"DOWN":.30},
                    "admitted_probabilities":None,"boundary_return":.004}
            for h in (1,3,5)
        }
    }
    return window,bars,frozen


def test_forward_settlement_never_touches_not_yet_due_horizons(tmp_path):
    clock=TradingClock()
    window,bars,frozen=_fixture(clock)
    save_research_snapshot(tmp_path,frozen)
    early=settle_due_research(tmp_path,bars,
                               latest_session=window[1].date().isoformat())
    assert early["new_outcomes"]==1
    rows=recent_v3_outcomes(tmp_path)
    assert len(rows)==1 and rows[0]["horizon"]==1
    # H3/H5 must wait for their actual exchange close.
    after=settle_due_research(tmp_path,bars,
                               latest_session=window[6].date().isoformat())
    assert after["new_outcomes"]==2
    assert len(recent_v3_outcomes(tmp_path))==3
    replay=settle_due_research(tmp_path,bars,
                                latest_session=window[6].date().isoformat())
    assert replay["new_outcomes"]==0
    for row in recent_v3_outcomes(tmp_path):
        assert row["actual_scenario"] in {"UP","FLAT","DOWN"}
        assert np.isfinite(row["brier_3class"])
        assert row["exit_session"]>=row["asof_session"]


def test_reject_modified_frozen_source(tmp_path):
    clock=TradingClock()
    window,bars,frozen=_fixture(clock)
    ref=save_research_snapshot(tmp_path,frozen)
    path=tmp_path/ref["path"]
    raw=json.loads(path.read_text(encoding="utf-8"))
    raw["horizons"]["1"]["research_estimates"]={"UP":.99,"FLAT":.005,"DOWN":.005}
    path.write_text(json.dumps(raw),encoding="utf-8")
    result=settle_due_research(tmp_path,bars,
         latest_session=window[6].date().isoformat())
    assert result["new_outcomes"]==0
    assert recent_v3_outcomes(tmp_path)==[]


def test_forward_scorecard_accepts_only_digest_linked_outcomes(tmp_path):
    clock=TradingClock()
    window,bars,frozen=_fixture(clock)
    save_research_snapshot(tmp_path,frozen)
    settled=settle_due_research(tmp_path,bars,
        latest_session=window[6].date().isoformat())
    assert settled["new_outcomes"]==3
    score=forward_scorecard(tmp_path,minimum_samples=1)
    assert score["schema"]=="qdr.l1.v3.forward.scorecard.v1"
    for h in (1,3,5):
        x=score["horizons"][str(h)]
        assert x["samples"]==1
        assert x["status"]=="FORWARD_RESEARCH_REPORT_ONLY"
        assert x["admitted"] is False
        assert x["brier"]>=0
    # Altering one settlement invalidates its content digest and score.
    first=next((tmp_path/"outputs"/"l1_v3_outcomes").glob("*/*_H1_*.json"))
    first.write_bytes(first.read_bytes()+b" ")
    bad=forward_scorecard(tmp_path,minimum_samples=1)
    assert bad["horizons"]["1"]["samples"]==0
    assert bad["horizons"]["3"]["samples"]==1
