"""V4 daily forecast-to-risk CLI contracts. Test doubles are not market data."""
import pandas as pd
import pytest

from quant_research.workflow import v4_review_cli as workflow


def _setup(monkeypatch):
    meta=pd.DataFrame([{'date':'2026-11-10','security_id':'AAA',
                        'source_snapshot_sha256':'a'*64}])
    monkeypatch.setattr(workflow,'_checked_inputs',
        lambda root,bundle_id:({'candidate_meta':meta},
                               {'source_snapshot_sha256':'a'*64}))
    monkeypatch.setattr(workflow,'run_managed_forward',
        lambda root,**k:{'status':'FORWARD_RESEARCH_FROZEN_ONLY',
                         'identity':'b'*16,
                         'prospective_before_next_open':True})
    monkeypatch.setattr(workflow,'load_settings',lambda *args:object())
    monkeypatch.setattr(workflow,'account_summary',
        lambda *args:{'status':'INTERNALLY_RECONCILED_PAPER_ESTIMATE'})


def test_review_cli_connects_forecast_risk_and_freezes_only_research(monkeypatch,tmp_path):
    _setup(monkeypatch)
    called=[]
    def review(root,**kw):
        called.append(kw)
        return {'status':'RESEARCH_PLANS_ONLY','plans':[{'security_id':'AAA'}],
                'evaluated':[{'security_id':'AAA','accepted':True}],
                'content_sha256':'c'*64,'execution_eligible':False,
                'real_orders_enabled':False}
    monkeypatch.setattr(workflow,'make_indicative_review',review)
    monkeypatch.setattr(workflow,'freeze_indicative_review',
                        lambda *args,**kw:kw['review'])
    output=workflow.run_v4_review_day(tmp_path,bundle_id='real-bundle',
                                       asof_session='2026-11-10')
    assert output['status']=='RESEARCH_PLAN_FROZEN_NO_ORDER'
    assert output['research_plan_count']==1 and called[0]['forecast_identity']=='b'*16
    assert not output['real_orders_enabled'] and not output['paper_ledger_advanced']


def test_missing_account_fails_closed_before_any_plan(monkeypatch,tmp_path):
    _setup(monkeypatch)
    monkeypatch.setattr(workflow,'account_summary',
                        lambda *args:{'status':'BLOCKED','code':'NO_PAPER_LEDGER'})
    def forbidden(*args,**kwargs):
        pytest.fail('No risk planning without actual reconciled ledger')
    monkeypatch.setattr(workflow,'make_indicative_review',forbidden)
    result=workflow.run_v4_review_day(tmp_path,bundle_id='real-bundle',
                                       asof_session='2026-11-10')
    assert result['status']=='RESEARCH_PLAN_BLOCKED'
    assert result['code']=='NO_PAPER_LEDGER'


def test_retrospective_inference_never_mints_trading_plan(monkeypatch,tmp_path):
    _setup(monkeypatch)
    monkeypatch.setattr(workflow,'run_managed_forward',
        lambda *args,**kw:{'status':'RETROSPECTIVE_ASOF_RECONSTRUCTION_ONLY',
                          'prospective_before_next_open':False})
    output=workflow.run_v4_review_day(tmp_path,bundle_id='real-bundle',
                                      asof_session='2026-11-10')
    assert output['status']=='NO_PROSPECTIVE_TRADE_PLAN'
    assert not output['execution_eligible']


def test_missing_source_matched_candidate_receipt_is_visible(monkeypatch,tmp_path):
    _setup(monkeypatch)
    monkeypatch.setattr(workflow,'_checked_inputs',
        lambda *args:({}, {'source_snapshot_sha256':'a'*64}))
    result=workflow.run_v4_review_day(tmp_path,bundle_id='real-bundle',
                                       asof_session='2026-11-10')
    assert result['status']=='RESEARCH_PLAN_BLOCKED'
    assert result['code']=='SOURCE_HASHED_CANDIDATE_METADATA_MISSING'



def test_explicit_research_budget_never_reads_a_real_paper_account(monkeypatch,tmp_path):
    _setup(monkeypatch)
    def forbidden(*args,**kwargs):
        pytest.fail('Explicit research budget must not inspect paper account or settings')
    monkeypatch.setattr(workflow,'account_summary',forbidden)
    monkeypatch.setattr(workflow,'load_settings',forbidden)
    seen=[]
    def review(root,**kwargs):
        seen.append(kwargs['account'])
        return {'status':'NO_RESEARCH_CANDIDATES','plans':[],'evaluated':[],
                'content_sha256':'c'*64,'execution_eligible':False,
                'real_orders_enabled':False}
    monkeypatch.setattr(workflow,'make_indicative_review',review)
    monkeypatch.setattr(workflow,'freeze_indicative_review',
                        lambda *args,**kwargs:kwargs['review'])
    result=workflow.run_v4_review_day(tmp_path,bundle_id='observed-bundle',
                                      asof_session='2026-11-10',
                                      research_budget=100000)
    assert result['status']=='RESEARCH_PLAN_FROZEN_NO_ORDER'
    assert result['research_plan_count']==0
    assert seen[0]['status']=='EXPLICIT_EMPTY_RESEARCH_BUDGET'
    assert seen[0]['has_actual_positions'] is False
    assert seen[0]['budget']==100000.
