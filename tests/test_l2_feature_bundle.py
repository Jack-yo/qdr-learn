"""Immutable verified L2 feature-bundle contract tests."""
import json

import pandas as pd
import pytest

from quant_research.research.l2_feature_bundle import (
    freeze_feature_bundle_v1,
    load_feature_bundle_v1,
)
from quant_research.research.l2_features import (
    FEATURE_PROTOCOL_VERSION,
    REQUIRED_FEATURE_PRICE_BASIS,
)
from quant_research.research.l2_forecast import INPUT_FEATURES, STYLE_IDS


def _features():
    dates=pd.bdate_range("2025-01-02",periods=3)
    rows=[]
    for day in dates:
        for i,style in enumerate(STYLE_IDS):
            row={
                "date":day,"style_id":style,
                "available_at":pd.Timestamp(day,tz="UTC")+pd.Timedelta(hours=21),
                "signal_time":pd.Timestamp(day,tz="UTC")+pd.Timedelta(hours=22),
                "feature_pit_eligible":True,
                "feature_status":"VERIFIED_PIT_FEATURE",
                "feature_protocol_version":FEATURE_PROTOCOL_VERSION,
                "feature_price_basis":REQUIRED_FEATURE_PRICE_BASIS,
                "action_evidence_version":"actions-v1",
                "historical_pit_attested":True,
                "decision_eligible":False,"real_orders_enabled":False,
            }
            for j,name in enumerate(INPUT_FEATURES):
                row[name]=0.001*(i+1)+0.0001*j
            rows.append(row)
    return pd.DataFrame(rows)


def test_feature_bundle_round_trip_is_source_hashed_and_pit_attested(tmp_path):
    manifest=freeze_feature_bundle_v1(
        tmp_path,"features-v1",_features(),
        source_evidence_sha256="a"*64,
        action_evidence_version="actions-v1",
    )
    assert manifest["historical_pit_attested"] is True
    assert manifest["eligible_rows"]==len(_features())
    assert set(manifest["eligible_sessions_by_style"].values())=={3}
    loaded,stored=load_feature_bundle_v1(tmp_path,"features-v1")
    assert len(loaded)==len(_features())
    assert stored["features_sha256"]==manifest["features_sha256"]
    assert loaded.feature_pit_eligible.all()


def test_feature_bundle_is_immutable_and_detects_parquet_tamper(tmp_path):
    freeze_feature_bundle_v1(
        tmp_path,"features-v1",_features(),
        source_evidence_sha256="b"*64,
        action_evidence_version="actions-v1",
    )
    with pytest.raises(FileExistsError,match="immutable"):
        freeze_feature_bundle_v1(
            tmp_path,"features-v1",_features(),
            source_evidence_sha256="b"*64,
            action_evidence_version="actions-v1",
        )
    path=tmp_path/"data/managed/l2_style_features/features-v1/features.parquet"
    path.write_bytes(path.read_bytes()+b"tamper")
    with pytest.raises(ValueError,match="HASH_MISMATCH"):
        load_feature_bundle_v1(tmp_path,"features-v1")


def test_feature_bundle_rejects_partial_style_scope(tmp_path):
    partial=_features().loc[lambda x:~x.style_id.eq("cyc_def")]
    with pytest.raises(ValueError,match="ALL_SEVEN"):
        freeze_feature_bundle_v1(
            tmp_path,"partial-v1",partial,
            source_evidence_sha256="c"*64,
            action_evidence_version="actions-v1",
        )


def test_feature_bundle_manifest_cannot_relabel_pit_or_scope(tmp_path):
    freeze_feature_bundle_v1(
        tmp_path,"features-v1",_features(),
        source_evidence_sha256="d"*64,
        action_evidence_version="actions-v1",
    )
    path=tmp_path/"data/managed/l2_style_features/features-v1/manifest.json"
    data=json.loads(path.read_text(encoding="utf-8"))
    data["historical_pit_attested"]=False
    path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError,match="IDENTITY_MISMATCH"):
        load_feature_bundle_v1(tmp_path,"features-v1")


def test_ineligible_row_cannot_claim_verified_pit_feature():
    frame=_features()
    frame.loc[0,"available_at"]=frame.loc[0,"signal_time"]+pd.Timedelta(minutes=1)
    from quant_research.research.l2_feature_bundle import validate_verified_feature_frame
    with pytest.raises(ValueError,match="PIT_EVIDENCE_INVALID"):
        validate_verified_feature_frame(frame)
