"""Pipeline stitching tests cover source mismatch and partial research status."""
from pathlib import Path

from quant_research.workflow import v4_ops
from quant_research.workflow import v4_pipeline_preflight


def _allow_matched_source(monkeypatch):
    monkeypatch.setattr(v4_pipeline_preflight,'preflight_v4_day',
        lambda *args,**kw:{'status':'PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY',
                           'source_snapshot_sha256':'a'*64,
                           'source_symbols':['AAA','SPY'],
                           'real_orders_enabled':False})
    monkeypatch.setattr(v4_ops,'research_readiness',
        lambda root,asof,*,symbols:{'stages':{'dataset':{
            'status':'OBSERVATION_ONLY','evidence':{
                'asof_date_et':asof,'symbols':symbols,
                'latest_session_complete':True,
                'source_snapshot_sha256':'a'*64}}}})


def test_pipeline_records_research_plan_and_actual_daily_observation(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    monkeypatch.setattr(
        __import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day']),
        'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
                          'source_snapshot_sha256':'a'*64,
                          'plan_identity':'f'*16,'research_plan_count':2,
                          'real_orders_enabled':False})
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',
        lambda *args,**kw:{'status':'RESEARCH_UPDATED_NO_TRADE',
                           'source_snapshot_sha256':'a'*64,
                           'paper_ledger_advanced':False})
    result=v4_ops.run_v4_pipeline_day(
        tmp_path,'2026-11-10',bundle_id='dated-source',
        research_budget=100000)
    assert result['status']=='RESEARCH_PLAN_AND_DIARY_SAVED'
    assert not result['real_orders_enabled'] and not result['paper_ledger_advanced']


def test_cross_snapshot_mismatch_cannot_create_daily_admission(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    monkeypatch.setattr(
        __import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day']),
        'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
                           'source_snapshot_sha256':'a'*64,
                           'real_orders_enabled':False})
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',
        lambda *args,**kw:{'status':'RESEARCH_UPDATED_NO_TRADE',
                           'source_snapshot_sha256':'b'*64,
                           'paper_ledger_advanced':False})
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='dated-source')
    assert result['status']=='SOURCE_SNAPSHOT_MISMATCH'
    assert result['code']=='POST_ADMISSION_WAREHOUSE_SOURCE_CHANGED'
    assert not result['real_orders_enabled']



def test_preflight_failure_never_calls_model_or_creates_frozen_plan(monkeypatch,tmp_path):
    def deny(*args,**kwargs):
        raise ValueError('BUNDLE_DIFFERS_FROM_LIVE_WAREHOUSE_SNAPSHOT')
    monkeypatch.setattr(v4_pipeline_preflight,'preflight_v4_day',deny)
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    def forbidden(*args,**kwargs):
        raise AssertionError('Model or immutable plan was reached before admission')
    monkeypatch.setattr(module,'run_v4_review_day',forbidden)
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='inconsistent')
    assert result['status']=='PREFLIGHT_BLOCKED_NO_ARCHIVE_WRITE'
    assert result['code']=='BUNDLE_DIFFERS_FROM_LIVE_WAREHOUSE_SNAPSHOT'
    assert not (tmp_path/'outputs/v4_forecasts').exists()
    assert not (tmp_path/'outputs/v4_research_plans').exists()



def test_missing_daily_source_receipt_is_not_a_success(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    monkeypatch.setattr(module,'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
                           'source_snapshot_sha256':'a'*64})
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',
        lambda *args,**kw:{'status':'BLOCKED','code':'NO_SOURCE_ATTESTED_DAILY_SNAPSHOT'})
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='dated-source')
    assert result['status']=='DAILY_SOURCE_NOT_VERIFIED'
    assert result['code']=='DAILY_DIARY_HAS_NO_VERIFIABLE_SOURCE_DIGEST'
    assert result['real_orders_enabled'] is False


def test_missing_plan_source_receipt_is_not_a_success(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    monkeypatch.setattr(module,'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER'})
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',
        lambda *args,**kw:{'status':'RESEARCH_UPDATED_NO_TRADE',
                           'source_snapshot_sha256':'a'*64})
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='dated-source')
    assert result['status']=='PLAN_SOURCE_NOT_VERIFIED'
    assert result['real_orders_enabled'] is False



def test_failed_forecast_never_writes_daily_archive(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    monkeypatch.setattr(module,'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_BLOCKED','code':'MODEL_NOT_CALIBRATED'})
    def forbidden(*args,**kw):
        raise AssertionError('daily immutable archive reached after model rejection')
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',forbidden)
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='bundle')
    assert result['status']=='RESEARCH_PLAN_BLOCKED_BEFORE_DAILY_FREEZE'
    assert result['code']=='MODEL_NOT_CALIBRATED'
    assert result['paper_ledger_advanced'] is False


def test_post_preflight_plan_source_change_never_writes_daily_archive(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    monkeypatch.setattr(module,'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
                           'source_snapshot_sha256':'b'*64})
    def forbidden(*args,**kw):
        raise AssertionError('daily immutable archive reached after source drift')
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',forbidden)
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',bundle_id='bundle')
    assert result['status']=='SOURCE_SNAPSHOT_MISMATCH'
    assert result['code']=='POST_ADMISSION_PLAN_SOURCE_CHANGED'


def test_post_fit_source_change_never_writes_immutable_daily(monkeypatch,tmp_path):
    _allow_matched_source(monkeypatch)
    monkeypatch.setattr(v4_ops,'research_readiness',
        lambda root,asof,*,symbols:{'stages':{'dataset':{
            'status':'OBSERVATION_ONLY','evidence':{
                'asof_date_et':asof,'symbols':symbols,
                'latest_session_complete':True,
                'source_snapshot_sha256':'b'*64}}}})
    module=__import__('quant_research.workflow.v4_review_cli',fromlist=['run_v4_review_day'])
    monkeypatch.setattr(module,'run_v4_review_day',
        lambda *args,**kw:{'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
                           'source_snapshot_sha256':'a'*64})
    def forbidden(*args,**kwargs):
        raise AssertionError('Immutable daily archive attempted with stale source')
    monkeypatch.setattr(v4_ops,'run_observed_v4_daily',forbidden)
    result=v4_ops.run_v4_pipeline_day(tmp_path,'2026-11-10',
                                       bundle_id='source-mutated')
    assert result['status']=='SOURCE_SNAPSHOT_MISMATCH'
    assert result['code']=='POST_MODEL_WAREHOUSE_SOURCE_CHANGED_BEFORE_DAILY_FREEZE'
    assert not result['paper_ledger_advanced']
