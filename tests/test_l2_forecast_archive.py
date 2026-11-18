"""Immutable P4 forecast archive tests."""
import json

import pytest

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
        "forecast_protocol_version":"qdr-l2-style-forecast-v1",
        "model_version":MODEL_VERSION,
        "config":{"min_training_sessions":252,"embargo_sessions":5,"ridge_alpha":1.0},
        "eligible_units":21,"blocked_units":0,"forecasts":rows,
        "historical_decision_eligible":False,"real_orders_enabled":False,
    }


def test_freeze_is_idempotent_for_same_identity(tmp_path):
    payload=_payload()
    first=freeze_forecast_snapshot_v1(tmp_path,payload)
    second=freeze_forecast_snapshot_v1(tmp_path,payload)
    assert first["identity"]==second["identity"]
    loaded=load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)
    assert loaded["identity"]==first["identity"]
    assert loaded["eligible_units"]==21
    assert loaded["real_orders_enabled"] is False


def test_same_session_model_cannot_be_overwritten_with_different_prediction(tmp_path):
    payload=_payload()
    freeze_forecast_snapshot_v1(tmp_path,payload)
    changed=_payload()
    changed["forecasts"][0]["predicted_relative_return"]=0.5
    with pytest.raises(FileExistsError,match="DIFFERENT_IDENTITY"):
        freeze_forecast_snapshot_v1(tmp_path,changed)


def test_archive_rejects_incomplete_or_execution_eligible_rows(tmp_path):
    payload=_payload()
    payload["forecasts"]=payload["forecasts"][:-1]
    with pytest.raises(ValueError,match="21 explicit"):
        freeze_forecast_snapshot_v1(tmp_path,payload)
    payload=_payload()
    payload["forecasts"][0]["decision_eligible"]=True
    with pytest.raises(ValueError,match="execution eligible"):
        freeze_forecast_snapshot_v1(tmp_path,payload)


def test_archive_detects_manifest_tampering(tmp_path):
    payload=_payload()
    freeze_forecast_snapshot_v1(tmp_path,payload)
    path=tmp_path/"outputs/l2_style_forecasts/2025-04-09"/MODEL_VERSION/"manifest.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    data["eligible_units"]=20
    path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError,match="IDENTITY_MISMATCH"):
        load_frozen_forecast_v1(tmp_path,"2025-04-09",MODEL_VERSION)
