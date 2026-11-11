"""Forward archive mathematical integrity tests; no real market data is used."""
import json

import pandas as pd
import pytest

from quant_research.research.v4_forecast_archive import (
    freeze_research_forecast,read_research_forecast,latest_forward_research)


def _forecast():
    return {'status':'FORWARD_RESEARCH_PREDICTIONS_ONLY',
            'asof_session':'2026-11-10',
            'source_snapshot_sha256':'a'*64,
            'forecasts':pd.DataFrame([
                {'date':'2026-11-10','security_id':'TEST-ID',
                 'model_variant':'D','horizon':3,
                 'expected_gross_trade_return':.025,
                 'p_up':.55,'decision_eligible':False,'research_only':True}]),
            'model_cards':pd.DataFrame([
                {'model_version':'v4-unapproved-test',
                 'training_sessions':600,'research_only':True}])}


def test_forward_record_is_outcome_free_and_immutable(tmp_path):
    archived=freeze_research_forecast(tmp_path,_forecast(),protocol_sha256='b'*64)
    assert archived['status']=='VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY'
    assert archived['manifest']['forecast_rows']==1
    assert archived['manifest']['decision_eligible'] is False
    ident=archived['manifest']['identity']
    result=read_research_forecast(tmp_path,'2026-11-10',ident,include_rows=True)
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
    root=tmp_path/'outputs/v4_forecasts/2026-11-10'
    manifest=root/archived['manifest']['identity']/'manifest.json'
    obj=json.loads(manifest.read_text(encoding='utf-8'))
    obj['decision_eligible']=True
    manifest.write_text(json.dumps(obj),encoding='utf-8')
    with pytest.raises(ValueError,match='restricted'):
        read_research_forecast(tmp_path,'2026-11-10',archived['manifest']['identity'])
    assert latest_forward_research(tmp_path)[0]['status']=='CORRUPT_FORECAST_ARCHIVE'
