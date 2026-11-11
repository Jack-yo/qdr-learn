"""V4 risk bridge contract tests: no real market history or broker orders."""
import pandas as pd
import pytest

from quant_research.workflow import v4_candidate_bridge as bridge


def _archived():
    source='a'*64
    base={'date':'2026-11-10','horizon':3,'model_variant':'D',
          'signal_time':'2026-11-10T21:15:00Z',
          'entry_time':'2026-11-11T14:30:00Z',
          'exit_time':'2026-11-13T21:00:00Z',
          'feature_available_at':'2026-11-10T21:13:00Z',
          'model_fit_time':'2026-11-10T21:35:00Z',
          'source_snapshot_sha256':source,
          'model_version':'v4-daily-test',
          'expected_gross_trade_return':.05,
          'expected_excess_return':.035,
          'p_up':.64,'p_downside':.12,
          'probability_status_up':'CALIBRATED_CHRONOLOGICAL_HOLDOUT',
          'probability_status_downside':'CALIBRATED_CHRONOLOGICAL_HOLDOUT',
          'decision_eligible':False}
    frame=pd.DataFrame([{**base,'security_id':'AAA'},
                        {**base,'security_id':'BBB'}])
    manifest={'session_date_et':'2026-11-10',
              'prospective_before_next_open':True,
              'source_snapshot_sha256':source,
              'created_at_utc':'2026-11-10T21:37:00Z'}
    return {'manifest':manifest,'forecasts':frame,
            'manifest_sha256':'b'*64}


def _metadata():
    return pd.DataFrame([
        {'date':'2026-11-10','security_id':sid,'symbol':sid,'sector':'TECH',
         'reference_close':100.,'atr20':2.,'adv20':30_000_000.,
         'available_at':'2026-11-10T21:14:00Z','source_snapshot_sha256':'a'*64}
        for sid in ('AAA','BBB')
    ])


def _account():
    return {'status':'INTERNALLY_RECONCILED_PAPER_ESTIMATE',
            'last_session':'2026-11-10','equity':100000.,'cash':100000.,
            'position_details':{},'last_prices':{}}


def _make(monkeypatch,archive=None,metadata=None,account=None,policy=None):
    monkeypatch.setattr(bridge,'read_research_forecast',lambda *a,**kw:archive or _archived())
    return bridge.make_indicative_review(
        '.',session_date='2026-11-10',forecast_identity='c'*16,
        securities=_metadata() if metadata is None else metadata,
        account=_account() if account is None else account,
        frozen_at_utc='2026-11-10T22:00:00Z',
        policy=policy or bridge.PlanPolicy())


def test_forward_predicted_returns_connect_to_costed_nontrade_plan(monkeypatch):
    result=_make(monkeypatch)
    assert result['status']=='RESEARCH_PLANS_ONLY'
    assert not result['execution_eligible'] and not result['real_orders_enabled']
    assert result['source_forecast_manifest_sha256']=='b'*64
    assert len(result['plans'])==2
    assert all(x['indicative_shares']==75 for x in result['plans'])
    assert all(x['estimated_net_edge']>0 for x in result['plans'])


def test_historical_reconstruction_never_generates_a_live_plan(monkeypatch):
    archive=_archived()
    archive['manifest']['prospective_before_next_open']=False
    result=_make(monkeypatch,archive=archive)
    assert result['plans']==[]
    assert result['status']=='RETROSPECTIVE_RECONSTRUCTION_NOT_A_LIVE_PLAN'


def test_wrong_source_and_late_security_metadata_fail_closed(monkeypatch):
    mismatch=_metadata()
    mismatch.loc[0,'source_snapshot_sha256']='b'*64
    with pytest.raises(ValueError,match='SOURCE_MISMATCH'):
        _make(monkeypatch,metadata=mismatch)
    late=_metadata()
    late.loc[0,'available_at']='2026-11-11T14:31:00Z'
    with pytest.raises(ValueError,match='AFTER_FREEZE'):
        _make(monkeypatch,metadata=late)


def test_account_must_be_reconciled_for_same_signal_date(monkeypatch):
    account=_account()
    account['last_session']='2026-11-09'
    with pytest.raises(ValueError,match='MARKS_NOT_FROM_SIGNAL_DAY'):
        _make(monkeypatch,account=account)
    account=_account()
    account['status']='BLOCKED'
    with pytest.raises(ValueError,match='NOT_RECONCILED'):
        _make(monkeypatch,account=account)


def test_uncalibrated_probabilities_never_produce_research_candidates(monkeypatch):
    archive=_archived()
    archive['forecasts'].loc[:,'probability_status_downside']='INSUFFICIENT_CALIBRATION_EVENTS'
    result=_make(monkeypatch,archive=archive)
    assert result['plans']==[]
    assert result['status']=='NO_RESEARCH_CANDIDATES'
    assert all(x['reason']=='MODEL_PROBABILITY_NOT_CALIBRATED'
               for x in result['evaluated'])


def test_immutable_plan_archive_and_tamper_detection(tmp_path,monkeypatch):
    review=_make(monkeypatch)
    saved=bridge.freeze_indicative_review(tmp_path,session_date='2026-11-10',review=review)
    assert saved==review
    assert bridge.freeze_indicative_review(
        tmp_path,session_date='2026-11-10',review=review)==review
    identity=review['content_sha256'][:16]
    path=tmp_path/'outputs/v4_research_plans/2026-11-10'/identity/'review.json'
    path.write_text(path.read_text().replace('AAA','MUTATED'),encoding='utf-8')
    with pytest.raises(ValueError,match='modified'):
        bridge.read_indicative_review(tmp_path,'2026-11-10',identity)
