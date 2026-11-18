import csv
import hashlib
import json

import pytest

from quant_research.workflow import l1_retrospective_report


def test_report_preserves_observation_scope_and_source_evidence(tmp_path, monkeypatch):
    payload={'status':'CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION','asof_session':'2026-11-13',
             'forecast':None,'current_prediction_eligible':False,
             'knowledge_cutoff_utc':'2026-11-14T09:00:00Z','source_snapshot_sha256':'a'*64,
             'features':[{'id':'market_return_5','domain':'price','status':'OBSERVED',
                          'source':'ALPACA:SIP:raw:SPY','available_at':'2026-11-14T08:00:00Z',
                          'reason':'CURRENT_VINTAGE_ETF_RETROSPECTIVE'},
                         {'id':'breadth_up_share','domain':'breadth','status':'MISSING',
                          'source':None,'available_at':None,'reason':'HISTORICAL_PIT_UNIVERSE_NOT_VERIFIED'}]}
    monkeypatch.setattr(l1_retrospective_report,'current_observation_for_api',lambda *a,**k:payload)
    out=tmp_path/'report'
    result=l1_retrospective_report.write_retrospective_report(tmp_path,'2026-11-13',out)
    assert result['observed_features']==1 and result['model_admitted'] is False
    rows=list(csv.DictReader((out/'feature_coverage.csv').open(encoding='utf-8',newline='')))
    assert rows[0]['source']=='ALPACA:SIP:raw:SPY'
    assert rows[0]['available_at']=='2026-11-14T08:00:00Z'
    assert rows[0]['coverage_scope']=='ASOF_FEATURE_AVAILABILITY_ONLY'
    assert rows[1]['blocked_reason']=='HISTORICAL_PIT_UNIVERSE_NOT_VERIFIED'
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['outputs_sha256']['observations.json']==hashlib.sha256((out/'observations.json').read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        l1_retrospective_report.write_retrospective_report(tmp_path,'2026-11-13',out)


def test_report_rejects_prediction_or_mismatched_date(tmp_path, monkeypatch):
    payload={'asof_session':'2026-11-13','forecast':{'p_up':.5},'current_prediction_eligible':False}
    monkeypatch.setattr(l1_retrospective_report,'current_observation_for_api',lambda *a,**k:payload)
    with pytest.raises(ValueError,match='SCOPE_INVALID'):
        l1_retrospective_report.write_retrospective_report(tmp_path,'2026-11-13',tmp_path/'report')
    assert not (tmp_path/'report').exists()
    payload['forecast']=None
    with pytest.raises(ValueError,match='SCOPE_INVALID'):
        l1_retrospective_report.write_retrospective_report(tmp_path,'2026-11-12',tmp_path/'report')
