"""Forward archive mathematical integrity tests; no real market data is used."""
import json

import pandas as pd
import pytest

from quant_research.research.v4_forecast_archive import (
    freeze_research_forecast,read_research_forecast,latest_forward_research)


def _forecast():
    return {'status':'FORWARD_RESEARCH_PREDICTIONS_ONLY',
            'asof_session':'2025-01-02',
            'source_snapshot_sha256':'a'*64,
            'forecasts':pd.DataFrame([
                {'date':'2025-01-02','security_id':'TEST-ID',
                 'model_variant':'D','horizon':3,
                 'expected_gross_trade_return':.025,
                 'p_up':.55,'decision_eligible':False,'research_only':True}]),
            'model_cards':pd.DataFrame([
                {'model_version':'v4-unapproved-test',
                 'training_sessions':600,'research_only':True}])}


def test_forward_record_is_outcome_free_and_immutable(tmp_path):
    archived=freeze_research_forecast(tmp_path,_forecast(),protocol_sha256='b'*64)
    assert archived['status']=='VERIFIED_LOCAL_RETROSPECTIVE_ASOF_ONLY'
    assert archived['manifest']['prospective_before_next_open'] is False
    assert archived['manifest']['forecast_rows']==1
    assert archived['manifest']['decision_eligible'] is False
    ident=archived['manifest']['identity']
    result=read_research_forecast(tmp_path,'2025-01-02',ident,include_rows=True)
    assert result['forecasts'].iloc[0].expected_gross_trade_return==pytest.approx(.025)
    assert not result['forecasts'].decision_eligible.any()
    assert len(latest_forward_research(tmp_path))==1
    with pytest.raises(FileExistsError):
        freeze_research_forecast(tmp_path,_forecast(),protocol_sha256='b'*64)


def test_rejects_realized_labels_and_execution_claim(tmp_path):
    payload=_forecast();payload['forecasts']['gross_return']=.10
    with pytest.raises(ValueError,match='realized'):
        freeze_research_forecast(tmp_path,payload,protocol_sha256='b'*64)
    payload=_forecast();payload['forecasts']['decision_eligible']=True
    with pytest.raises(ValueError,match='execution-eligible'):
        freeze_research_forecast(tmp_path,payload,protocol_sha256='b'*64)


def test_manifest_corruption_is_reported(tmp_path):
    archived=freeze_research_forecast(tmp_path,_forecast(),protocol_sha256='b'*64)
    root=tmp_path/'outputs/v4_forecasts/2025-01-02'
    manifest=root/archived['manifest']['identity']/'manifest.json'
    obj=json.loads(manifest.read_text(encoding='utf-8'))
    obj['decision_eligible']=True
    manifest.write_text(json.dumps(obj),encoding='utf-8')
    with pytest.raises(ValueError,match='restricted'):
        read_research_forecast(tmp_path,'2025-01-02',archived['manifest']['identity'])
    assert latest_forward_research(tmp_path)[0]['status']=='CORRUPT_FORECAST_ARCHIVE'


def test_v2_source_artifact_bytes_change_forecast_identity(tmp_path):
    contract={'artifacts_sha256':{
        'factors.parquet':'c'*64,'labels.parquet':'d'*64,
        'market_style.parquet':'e'*64,'candidate_meta.parquet':'f'*64},
        'factor_names':['reversal_5d'],'source_symbols':['AAA','SPY']}
    first=freeze_research_forecast(tmp_path,_forecast(),
        protocol_sha256='b'*64,input_contract=contract)
    assert first['manifest']['schema']=='v4-forward-2'
    changed={**contract,'artifacts_sha256':{
        **contract['artifacts_sha256'],'factors.parquet':'0'*64}}
    second=freeze_research_forecast(tmp_path,_forecast(),
        protocol_sha256='b'*64,input_contract=changed)
    assert first['manifest']['identity']!=second['manifest']['identity']
    assert first['manifest']['input_contract_sha256']!=second['manifest']['input_contract_sha256']
    assert len(latest_forward_research(tmp_path))==2


def test_v2_source_input_contract_tampering_is_detected(tmp_path):
    contract={'artifacts_sha256':{
        'factors.parquet':'c'*64,'labels.parquet':'d'*64,
        'market_style.parquet':'e'*64},
        'factor_names':['alpha'],'source_symbols':['AAA']}
    item=freeze_research_forecast(tmp_path,_forecast(),
        protocol_sha256='b'*64,input_contract=contract)
    identity=item['manifest']['identity']
    path=(tmp_path/'outputs/v4_forecasts/2025-01-02'/identity/'manifest.json')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    manifest['input_contract']['artifacts_sha256']['factors.parquet']='f'*64
    path.write_text(json.dumps(manifest),encoding='utf-8')
    with pytest.raises(ValueError,match='input provenance'):
        read_research_forecast(tmp_path,'2025-01-02',identity)


def _l2_binding_receipt(context_sha="1" * 64, historical_pit=False):
    return {
        "contract_version": "qdr-l2-l3-style-binding-v1",
        "scope": "HISTORICAL_AND_CURRENT",
        "start_session": "2025-01-02",
        "end_session": "2025-01-02",
        "rows": 1,
        "style_columns": ["style_l2_size_h3"],
        "context_identity_sha256": context_sha,
        "model_versions": ["ridge-v1"],
        "label_bundle_sha256s": ["2" * 64],
        "feature_bundle_sha256s": ["5" * 64],
        "source_snapshot_sha256s": ["4" * 64],
        "binding_verified": True,
        "historical_pit_attested": historical_pit,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def test_l2_style_binding_receipt_changes_l3_forecast_identity(tmp_path):
    base = {
        "artifacts_sha256": {
            "factors.parquet": "c" * 64,
            "labels.parquet": "d" * 64,
            "market_style.parquet": "e" * 64,
        },
        "factor_names": ["alpha"],
        "source_symbols": ["AAA"],
        "l2_style_context_receipt": _l2_binding_receipt(),
    }
    first = freeze_research_forecast(
        tmp_path, _forecast(), protocol_sha256="b" * 64,
        input_contract=base,
    )
    changed = {
        **base,
        "l2_style_context_receipt": _l2_binding_receipt("3" * 64),
    }
    second = freeze_research_forecast(
        tmp_path, _forecast(), protocol_sha256="b" * 64,
        input_contract=changed,
    )
    assert first["manifest"]["identity"] != second["manifest"]["identity"]
    records = latest_forward_research(tmp_path, limit=5)
    assert len(records) == 2
    assert all(row["l2_style_binding_verified"] is True for row in records)
    assert all(
        row["l2_style_historical_pit_attested"] is False
        for row in records
    )
    assert {row["l2_style_binding_context_sha256"] for row in records} == {
        "1" * 64, "3" * 64,
    }


def test_l2_binding_receipt_cannot_claim_execution_in_l3_archive(tmp_path):
    receipt = _l2_binding_receipt()
    receipt["decision_eligible"] = True
    contract = {
        "artifacts_sha256": {
            "factors.parquet": "c" * 64,
            "labels.parquet": "d" * 64,
            "market_style.parquet": "e" * 64,
        },
        "factor_names": ["alpha"],
        "source_symbols": ["AAA"],
        "l2_style_context_receipt": receipt,
    }
    with pytest.raises(ValueError, match="CANNOT_ENABLE_EXECUTION"):
        freeze_research_forecast(
            tmp_path, _forecast(), protocol_sha256="b" * 64,
            input_contract=contract,
        )


def _l2_binding_receipt_v2(admission_identity="6" * 64):
    return {
        "contract_version": "qdr-l2-l3-style-binding-v2",
        "scope": "PIT_REPLAY_HISTORY_PLUS_CURRENT_FORWARD",
        "start_session": "2025-01-02",
        "end_session": "2025-01-02",
        "rows": 1,
        "style_columns": ["style_l2_size_h3"],
        "context_identity_sha256": "1" * 64,
        "context_modes": ["CURRENT_FROZEN_FORWARD"],
        "admission_asof_session": "2025-01-02",
        "admission_validation_identity": admission_identity,
        "admission_frozen_at_utc": "2025-01-03T01:00:00Z",
        "current_forward_session": "2025-01-02",
        "historical_replay_rows": 0,
        "current_forward_rows": 1,
        "model_versions": ["ridge-v1"],
        "label_bundle_sha256s": ["2" * 64],
        "feature_bundle_sha256s": ["5" * 64],
        "source_snapshot_sha256s": ["4" * 64],
        "binding_verified": True,
        "historical_pit_attested": True,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def test_v2_l2_admission_identity_is_persisted_and_changes_l3_archive_identity(
    tmp_path,
):
    base = {
        "artifacts_sha256": {
            "factors.parquet": "c" * 64,
            "labels.parquet": "d" * 64,
            "market_style.parquet": "e" * 64,
        },
        "factor_names": ["alpha"],
        "source_symbols": ["AAA"],
        "l2_style_context_receipt": _l2_binding_receipt_v2(),
    }
    first = freeze_research_forecast(
        tmp_path, _forecast(), protocol_sha256="b" * 64,
        input_contract=base,
    )
    changed = {
        **base,
        "l2_style_context_receipt": _l2_binding_receipt_v2("7" * 64),
    }
    second = freeze_research_forecast(
        tmp_path, _forecast(), protocol_sha256="b" * 64,
        input_contract=changed,
    )
    assert first["manifest"]["identity"] != second["manifest"]["identity"]
    records = latest_forward_research(tmp_path, limit=5)
    by_identity = {row["identity"]: row for row in records}
    row = by_identity[first["manifest"]["identity"]]
    assert row["l2_style_admission_validation_identity"] == "6" * 64
    assert row["l2_style_admission_asof_session"] == "2025-01-02"
    assert row["l2_style_context_modes"] == ["CURRENT_FROZEN_FORWARD"]
    assert row["l2_style_current_forward_session"] == "2025-01-02"
    assert row["l2_style_historical_pit_attested"] is True
