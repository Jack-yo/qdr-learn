"""Stage-run tests use explicit function stubs, no market data or fake signals."""
from pathlib import Path
import json
import pytest

from quant_research.clock import TradingClock
from quant_research.workflow.v4_daily import run_v4_daily,read_v4_daily
from quant_research.policy import PolicyError


def _day():
    return '2026-11-10'


def test_all_stage_callbacks_complete_but_execution_is_not_granted(tmp_path):
    observed=[]
    def stage(name):
        def fn(day, history):
            observed.append((name,len(history)))
            return {'status':'PASS','detail':{'stage_test':name}}
        return fn
    names=['data','market','styles','alpha','risk','freeze']
    adapters={name:stage(name) for name in names}
    result=run_v4_daily(tmp_path,_day(),source_snapshot_sha256='a'*64,
                        protocol_sha256='b'*64,adapters=adapters)
    assert result['status']=='STAGES_COMPLETE_ADMISSION_PENDING'
    assert not result['execution_eligible'] and not result['paper_ledger_advanced']
    assert [x[0] for x in observed]==names
    again=run_v4_daily(tmp_path,_day(),source_snapshot_sha256='a'*64,
                       protocol_sha256='b'*64,adapters=adapters)
    assert again==result and len(observed)==len(names)
    read=read_v4_daily(tmp_path,_day(),result['identity'])
    assert read==result


def test_blocked_alpha_stops_risk_and_freeze(tmp_path):
    called=[]
    def stage(name):
        def fn(day, history):
            called.append(name)
            return {'status':'BLOCKED' if name=='alpha' else 'PASS',
                    'code':'MODEL_MISSING' if name=='alpha' else ''}
        return fn
    names=['data','market','styles','alpha','risk','freeze']
    result=run_v4_daily(tmp_path,_day(),source_snapshot_sha256='c'*64,
                        protocol_sha256='d'*64,adapters={name:stage(name) for name in names})
    assert called==names[:4]
    assert result['status']=='BLOCKED_OR_NO_TRADE'
    assert result['stages'][-1]['code']=='MODEL_MISSING'


def test_missing_adapter_and_tampered_archive(tmp_path):
    result=run_v4_daily(tmp_path,_day(),source_snapshot_sha256='e'*64,
                        protocol_sha256='f'*64,adapters={})
    assert result['stages'][0]['code']=='STAGE_ADAPTER_NOT_CONNECTED'
    path=tmp_path/'outputs/v4_daily'/_day()/result['identity']/'manifest.json'
    payload=json.loads(path.read_text(encoding='utf-8'))
    payload['paper_ledger_advanced']=True
    path.write_text(json.dumps(payload),encoding='utf-8')
    with pytest.raises(PolicyError,match='modified'):
        read_v4_daily(tmp_path,_day(),result['identity'])


def test_nonexchange_date_rejected(tmp_path):
    with pytest.raises(ValueError):
        run_v4_daily(tmp_path,'2026-11-08',source_snapshot_sha256='a'*64,
                     protocol_sha256='b'*64,adapters={})



def test_descriptive_market_still_allows_independent_risk_review(tmp_path):
    called=[]
    def fn(name):
        def run(day,history):
            called.append(name)
            return {'status':'RESEARCH_ONLY' if name in ('market','styles','alpha') else 'PASS'}
        return run
    adapters={name:fn(name) for name in ['data','market','styles','alpha','risk','freeze']}
    result=run_v4_daily(tmp_path,_day(),source_snapshot_sha256='9'*64,
                        protocol_sha256='8'*64,adapters=adapters)
    assert called==['data','market','styles','alpha','risk']
    assert result['stages'][-1]['code']=='RESEARCH_ONLY_NOT_ADMITTED_FOR_EXECUTION'
    assert result['status']=='RESEARCH_UPDATED_NO_TRADE'
    assert not result['paper_ledger_advanced']
