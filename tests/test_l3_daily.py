import pandas as pd
import pytest

from quant_research.workflow import l3_daily


DAY="2026-11-10"


def _strategy():
    return {
        "id":"strategy-v1","name":"Alpha Mix","version":1,"status":"FROZEN",
        "config_sha256":"a"*64,
        "config":{"factor_mix":{"allocations":[
            {"weight":.6,"dependency":{"factor_name":"reversal"}},
            {"weight":.4,"dependency":{"factor_name":"relative_strength"}},
        ]}},
    }


def _frames():
    return {
        "candidate_meta":pd.DataFrame([
            {"date":DAY,"security_id":"AAA","symbol":"AAA","sector":"TECH",
             "reference_close":100.,"atr20":2.,"adv20":30_000_000.,
             "available_at":"2026-11-10T21:10:00Z"},
            {"date":DAY,"security_id":"BBB","symbol":"BBB","sector":"TECH",
             "reference_close":90.,"atr20":2.5,"adv20":40_000_000.,
             "available_at":"2026-11-10T21:10:00Z"},
        ])
    }


def _scores():
    return pd.DataFrame([
        {"security_id":"AAA","reversal":1.0,"relative_strength":.5,
         "alpha_score":.8,"alpha_rank_pct":1.0,
         "contribution__reversal":.6,"contribution__relative_strength":.2},
        {"security_id":"BBB","reversal":.5,"relative_strength":1.0,
         "alpha_score":.7,"alpha_rank_pct":.5,
         "contribution__reversal":.3,"contribution__relative_strength":.4},
    ])


def test_daily_alpha_snapshot_is_write_once_and_hash_verified(tmp_path,monkeypatch):
    manifest={"source_snapshot_sha256":"b"*64,
              "artifacts_sha256":{"factors.parquet":"c"*64},
              "factor_names":["reversal","relative_strength"]}
    admitted={"status":"PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY",
              "source_snapshot_sha256":"b"*64}
    monkeypatch.setattr(l3_daily,"active_strategy",
                        lambda root:{"strategy":_strategy()})
    monkeypatch.setattr(l3_daily,"_checked_inputs",
                        lambda root,bundle:(_frames(),manifest))
    monkeypatch.setattr(l3_daily,"_daily_scores",
                        lambda strategy,frames,day:(_scores(),manifest["factor_names"]))

    first=l3_daily.freeze_l3_daily(
        tmp_path,session_date=DAY,bundle_id="bundle",admitted=admitted)
    second=l3_daily.freeze_l3_daily(
        tmp_path,session_date=DAY,bundle_id="bundle",admitted=admitted)
    assert first["status"]=="FROZEN_L3_DAILY_ALPHA_RESEARCH_ONLY"
    assert second["status"]=="L3_DAILY_ALPHA_ALREADY_FROZEN"
    identity=first["manifest"]["identity"]
    loaded=l3_daily.read_l3_daily(tmp_path,DAY,identity,include_scores=True)
    assert len(loaded["scores"])==2
    assert loaded["manifest"]["strategy_version_id"]=="strategy-v1"
    assert loaded["manifest"]["real_orders_enabled"] is False

    path=tmp_path/"outputs/l3_daily"/DAY/identity/"scores.parquet"
    path.write_bytes(path.read_bytes()+b"tamper")
    with pytest.raises(ValueError,match="integrity"):
        l3_daily.read_l3_daily(tmp_path,DAY,identity)
