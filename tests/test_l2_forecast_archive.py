"""Immutable P4 forecast archive tests."""
import json

import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, MODEL_VERSION, STYLE_IDS
from quant_research.research.l2_forecast_archive import (
    freeze_forecast_snapshot_v1, load_frozen_forecast_v1,
)


def _payload():
    rows=[]
    for style in STYLE_IDS:
        for horizon in HORIZONS:
            rows.append({
                "date":"2025-04-09","style_id":style,"horizon":horizon,
                "predicted_relative_return":0.001*horizon,
                "zero_baseline":0.0,"mean_baseline":0.0002,
                "momentum_baseline":0.0003,"train_sessions":300,
                "forecast_status":"RESEARCH_ONLY","block_reason":None,
                "decision_eligible":False,"real_orders_enabled":False,
            })
    return {
        "status":"RESEARCH_ONLY","asof_session":"2025-04-09",
        "source_snapshot_sha256":"a"*64,
        "label_bundle_id":"accepted-v1","label_bundle_sha256":"b"*64,
        "label_source_evidence_sha256":"c"*64,
        "feature_bundle_id":"features-v1","feature_bundle_sha256":"d"*64,
        "feature_source_evidence_sha256":"e"*64,
        "feature_price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
        "historical_feature_pit_attested":True,
        "forecast_protocol_version":"qdr-l2-style-forecast-v1",
        "model_version":MODEL_VERSION,
        "config":{"min_training_sessions":252,"embargo_sessions":5,"ridge_alpha":1.0},
        "eligible_units":21,"blocked_units":0,"forecasts":rows,
        "historical_decision_eligible":False,"real_orders_enabled":False,
    }


def _forward_time():
    window=TradingClock().window("2025-04-09",1)
    return pd.Timestamp(window.signal_time)+pd.Timedelta(minutes=1)


def _late_time():
    window=TradingClock().window("2025-04-09",1)
    return pd.Timestamp(window.entry_time)+pd.Timedelta(minutes=1)


def test_freeze_is_idempotent_for_same_identity(tmp_path):
    payload=_payload()
    first=freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
    second=freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
    assert first["identity"]==second["identity"]
    assert first["status"]=="FROZEN_L2_FORWARD_RESEARCH_ONLY"
    assert first["prospective_before_next_open"] is True
    loaded=load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)
    assert loaded["identity"]==first["identity"]
    assert loaded["eligible_units"]==21
    assert loaded["prospective_before_next_open"] is True
    assert loaded["real_orders_enabled"] is False


def test_late_freeze_is_retrospective_and_cannot_be_upgraded(tmp_path):
    payload=_payload()
    frozen=freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_late_time())
    assert frozen["status"]=="FROZEN_L2_RETROSPECTIVE_ASOF_ONLY"
    assert frozen["prospective_before_next_open"] is False
    loaded=load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)
    assert loaded["prospective_before_next_open"] is False

    path=tmp_path/"outputs/l2_style_forecasts/2025-04-09"/MODEL_VERSION/"manifest.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    data["status"]="FROZEN_L2_FORWARD_RESEARCH_ONLY"
    data["prospective_before_next_open"]=True
    path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError,match="SCOPE_TIME_MISMATCH"):
        load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)


def test_same_session_model_cannot_be_overwritten_with_different_prediction(tmp_path):
    payload=_payload()
    freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
    changed=_payload()
    changed["forecasts"][0]["predicted_relative_return"]=0.5
    with pytest.raises(FileExistsError,match="DIFFERENT_IDENTITY"):
        freeze_forecast_snapshot_v1(tmp_path,changed,now_utc=_forward_time())


def test_archive_rejects_incomplete_or_execution_eligible_rows(tmp_path):
    payload=_payload()
    payload["forecasts"]=payload["forecasts"][:-1]
    with pytest.raises(ValueError,match="21 explicit"):
        freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
    payload=_payload()
    payload["forecasts"][0]["decision_eligible"]=True
    with pytest.raises(ValueError,match="execution eligible"):
        freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())


def test_archive_detects_manifest_tampering(tmp_path):
    payload=_payload()
    freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
    path=tmp_path/"outputs/l2_style_forecasts/2025-04-09"/MODEL_VERSION/"manifest.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    data["eligible_units"]=20
    path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError,match="IDENTITY_MISMATCH"):
        load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)


def test_new_p4_archive_requires_verified_feature_bundle(tmp_path):
    payload=_payload()
    payload.pop("feature_bundle_sha256")
    with pytest.raises(ValueError,match="feature bundle"):
        freeze_forecast_snapshot_v1(tmp_path,payload,now_utc=_forward_time())
