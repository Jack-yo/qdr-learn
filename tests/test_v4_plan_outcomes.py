"""V4 observed future-path tests. OHLC numbers are invented test fixtures only."""
from hashlib import sha256
import pandas as pd
import pytest

from quant_research.workflow import v4_candidate_bridge as bridge
from quant_research.workflow import v4_plan_outcomes as outcomes


def _frozen_review(root, *, plans=True):
    base={'status':'RESEARCH_PLANS_ONLY' if plans else 'NO_RESEARCH_CANDIDATES',
          'horizon':3,'asof_frozen_utc':'2025-01-02T22:00:00Z',
          'source_snapshot_sha256':'a'*64,
          'source_forecast_identity':'f'*16,
          'plans':[{
             'security_id':'AAA','symbol':'AAA',
             'entry_time':'2025-01-03T14:30:00Z',
             'exit_time':'2025-01-07T21:00:00Z',
             'expected_gross_return':.03,
             'estimated_net_edge':.028,
             'estimated_round_trip_cost':.002,
             'decision_atr20':2.0,
             'initial_stop_distance':4.0,
             'research_only':True,'execution_eligible':False
          }] if plans else [],
          'evaluated':[],
          'execution_eligible':False,'real_orders_enabled':False}
    base['content_sha256']=sha256(bridge._canonical(base).encode()).hexdigest()
    saved=bridge.freeze_indicative_review(root,session_date='2025-01-02',review=base)
    return saved['content_sha256'][:16]


def _future_bars():
    return pd.DataFrame([
        {'session_date':'2025-01-03','security_id':'AAA','open':100.,'high':102.,'low':99.,'close':101.,
         'available_at':'2025-01-03T21:15:00Z','source_sha256':'b'*64,'corporate_action_status':'VERIFIED_NO_ACTION'},
        {'session_date':'2025-01-06','security_id':'AAA','open':95.,'high':97.,'low':94.,'close':96.,
         'available_at':'2025-01-06T21:15:00Z','source_sha256':'c'*64,'corporate_action_status':'VERIFIED_NO_ACTION'},
        {'session_date':'2025-01-07','security_id':'AAA','open':97.,'high':99.,'low':96.,'close':98.,
         'available_at':'2025-01-07T21:15:00Z','source_sha256':'d'*64,'corporate_action_status':'VERIFIED_NO_ACTION'}
    ])


def test_future_observation_uses_actual_bars_and_gap_through_stop(tmp_path):
    identity=_frozen_review(tmp_path)
    result=outcomes.evaluate_research_outcomes(
        tmp_path,'2025-01-02',identity,_future_bars(),
        observed_at_utc='2025-01-08T10:00:00Z')
    assert result['status']=='PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY'
    row=result['evaluated'][0]
    assert row['modeled_entry_price']==100.
    assert row['modeled_exit_price']==95.
    assert row['modeled_exit_reason']=='GAP_THROUGH_STOP'
    assert row['modeled_exit_session']=='2025-01-06'
    assert row['modeled_net_return']==pytest.approx(-.052)
    assert result['real_orders_enabled'] is False
    archived=outcomes.freeze_research_outcomes(tmp_path,result)
    assert archived==result
    assert outcomes.freeze_research_outcomes(tmp_path,result)==result


def test_missing_bars_cannot_generate_outcome(tmp_path):
    identity=_frozen_review(tmp_path)
    with pytest.raises(ValueError,match='COVERAGE_INCOMPLETE'):
        outcomes.evaluate_research_outcomes(
            tmp_path,'2025-01-02',identity,_future_bars().iloc[:2],
            observed_at_utc='2025-01-08T10:00:00Z')


def test_corporate_actions_refuse_unverified_adjusted_pnl(tmp_path):
    identity=_frozen_review(tmp_path)
    bars=_future_bars()
    bars.loc[0,'corporate_action_status']='UNKNOWN'
    with pytest.raises(ValueError,match='CORPORATE_ACTION'):
        outcomes.evaluate_research_outcomes(
            tmp_path,'2025-01-02',identity,bars,observed_at_utc='2025-01-08T10:00:00Z')


def test_not_yet_observed_outcome_and_no_trades(tmp_path):
    identity=_frozen_review(tmp_path)
    status=outcomes.evaluate_research_outcomes(
        tmp_path,'2025-01-02',identity,_future_bars(),
        observed_at_utc='2025-01-06T22:00:00Z')
    assert status['status']=='FUTURE_OUTCOME_NOT_YET_OBSERVED'
    root=tmp_path/'empty'
    empty=_frozen_review(root,plans=False)
    no_plan=outcomes.evaluate_research_outcomes(
        root,'2025-01-02',empty,pd.DataFrame(),
        observed_at_utc='2025-01-08T10:00:00Z')
    assert no_plan['status']=='NO_TRADE_PLAN_TO_EVALUATE'
    assert no_plan['evaluated']==[]
