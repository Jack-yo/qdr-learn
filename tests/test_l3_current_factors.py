import hashlib
import json
import shutil

import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.features.factors import FunctionalFactor
from quant_research.policy import PolicyError
from quant_research.workflow import l3_current_factors
from quant_research.workflow import l3_daily


DAY="2026-11-10"
CUTOFF="2026-11-10T22:00:00+00:00"


def _strategy():
    return {
        "id":"strategy-v1","name":"Current Alpha","version":1,"status":"FROZEN",
        "config_sha256":"b"*64,
        "config":{
            "protocol":{"minimum_price":5.0,"minimum_adv20":20_000_000.0},
            "factor_mix":{"allocations":[
                {"weight":.6,"dependency":{"factor_name":"f1"}},
                {"weight":.4,"dependency":{"factor_name":"f2"}},
            ]},
        },
    }


def _write_feature_run(root, vendor=False):
    clock=TradingClock()
    sessions=clock.calendar.sessions_in_range("2026-09-15",DAY)[-30:]
    rows=[]
    symbols=["SPY","AAA","BBB","CCC","DDD","EEE"]
    for i,day in enumerate(sessions):
        for j,symbol in enumerate(symbols):
            close=100.0+i*(.2+j*.02)
            rows.append({
                "date":pd.Timestamp(day),"security_id":"SID-"+symbol,"symbol":symbol,
                "open":close-.2,"high":close+.8,"low":close-.7,"close":close,
                "volume":1_000_000+j*50_000,"available_at":pd.Timestamp(CUTOFF),
                "source":"ALPACA","feed":"sip",
                "adjustment_basis":("vendor_split_adjusted_price_proxy" if vendor else "split_adjusted_price_proxy"),
                "raw_sha256":"a"*64,"quality_flag":"REAL",
            })
    folder=root/"outputs/feature_prices/run-1"
    folder.mkdir(parents=True)
    prices=pd.DataFrame(rows)
    path=folder/"feature_prices.parquet"
    prices.to_parquet(path,index=False)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={
        "status":("FORWARD_VENDOR_SPLIT_FEATURES_VERIFIED_CURRENT_VINTAGE" if vendor
                  else "NORMALIZATION_VERIFIED_CURRENT_VINTAGE"),
        "purpose":("l3-forward" if vendor else "normalization-audit"),
        "source":"ALPACA","feed":"sip",
        "adjustment_basis":("vendor_split_adjusted_price_proxy" if vendor
                            else "split_adjusted_price_proxy"),
        "anchor_date_et":DAY,"knowledge_cutoff_utc":CUTOFF,
        "raw_snapshot_sha256":"c"*64,"feature_snapshot_sha256":"d"*64,
        "reference_comparison":{
            "status":("NOT_APPLICABLE_DIRECT_VENDOR_SOURCE" if vendor else "PASS")
        },
        "research_only":True,"execution_ready":False,"real_orders_enabled":False,
        "artifacts_sha256":{"feature_prices.parquet":digest},
    }
    (folder/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    return folder


def test_current_factor_snapshot_and_daily_rank_are_immutable(tmp_path,monkeypatch):
    _write_feature_run(tmp_path)
    strategy=_strategy()
    monkeypatch.setattr(l3_current_factors,"active_strategy",
                        lambda root:{"strategy":strategy})
    monkeypatch.setattr(
        l3_current_factors,"_active_factors",
        lambda root,strategy:(
            [
                FunctionalFactor("f1",5,lambda c:-(c.close/c.close.shift(5)-1),"f1"),
                FunctionalFactor("f2",10,lambda c:c.close/c.close.shift(10)-1,"f2"),
            ],
            ["f1","f2"],
        ),
    )
    snap=l3_current_factors.build_current_factor_snapshot(
        tmp_path,session_date=DAY,feature_run_id="run-1")
    assert snap["status"]=="FROZEN_CURRENT_L3_FACTOR_SNAPSHOT_RESEARCH_ONLY"
    assert snap["manifest"]["complete_factor_security_count"]==5
    assert snap["manifest"]["execution_eligible"] is False

    monkeypatch.setattr(l3_daily,"active_strategy",
                        lambda root:{"strategy":strategy})
    daily=l3_daily.freeze_l3_current(
        tmp_path,session_date=DAY,
        factor_snapshot_identity=snap["manifest"]["identity"])
    loaded=l3_daily.read_l3_daily(
        tmp_path,DAY,daily["manifest"]["identity"],include_scores=True)
    assert len(loaded["scores"])==5
    assert loaded["scores"].alpha_rank_pct.between(0,1).all()
    assert loaded["manifest"]["input_kind"]=="CURRENT_FACTOR_SNAPSHOT"

    factor_path=(tmp_path/"outputs/l3_factor_snapshots"/DAY/
                 snap["manifest"]["identity"]/"factors.parquet")
    factor_path.write_bytes(factor_path.read_bytes()+b"tamper")
    with pytest.raises(ValueError,match="SHA256"):
        l3_current_factors.read_current_factor_snapshot(
            tmp_path,DAY,snap["manifest"]["identity"],include_frames=True)



def test_vendor_native_forward_feature_run_is_admitted(tmp_path):
    _write_feature_run(tmp_path, vendor=True)
    run_id, manifest, path = l3_current_factors._feature_run(
        tmp_path, DAY, "run-1"
    )
    assert run_id == "run-1"
    assert path.is_file()
    assert manifest["status"] == "FORWARD_VENDOR_SPLIT_FEATURES_VERIFIED_CURRENT_VINTAGE"
    assert manifest["reference_comparison"]["status"] == "NOT_APPLICABLE_DIRECT_VENDOR_SOURCE"



def test_blocked_local_normalization_is_not_admitted_to_l3(tmp_path):
    folder = _write_feature_run(tmp_path)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = "BLOCKED"
    manifest["reference_comparison"] = {"status":"BLOCKED"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PolicyError, match="No verified split-adjusted feature-price run"):
        l3_current_factors._feature_run(tmp_path, DAY, "run-1")
