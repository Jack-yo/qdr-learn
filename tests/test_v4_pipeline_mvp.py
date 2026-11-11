"""Pipeline stitching tests cover source mismatch and partial research status."""
from pathlib import Path

from quant_research.workflow import v4_ops


def test_pipeline_records_research_plan_and_actual_daily_observation(monkeypatch,tmp_path):
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
    assert result['code']=='FORECAST_SOURCE_DIFFERS_FROM_DAILY_WAREHOUSE'
    assert not result['real_orders_enabled']
