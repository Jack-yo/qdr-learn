"""Decision planner tests: numeric fixtures are not market/strategy performance."""
import pandas as pd
import pytest

from quant_research.workflow.v4_decision import PlanPolicy, indicative_plans


def _forecast():
    base = {
        'horizon':3,'signal_time':'2026-11-11T21:30:00Z',
        'feature_available_at':'2026-11-11T21:10:00Z',
        'model_fit_time':'2026-11-10T21:00:00Z',
        'entry_time':'2026-11-12T14:30:00Z',
        'exit_time':'2026-11-16T21:00:00Z',
        'source_snapshot_sha256':'a'*64,'model_version':'v4-test-model',
        'predicted_gross_return':.05,'predicted_excess_return':.03,
        'p_up':.65,'p_downside':.10,
        'up_calibration_status':'CALIBRATED_CHRONOLOGICAL_HOLDOUT',
        'downside_calibration_status':'CALIBRATED_CHRONOLOGICAL_HOLDOUT',
        'reference_close':100.,'atr20':2.,'adv20':30_000_000.,
        'sector':'TECH',
    }
    return pd.DataFrame([{**base,'symbol':'AAA','security_id':'AAA'},
                         {**base,'symbol':'BBB','security_id':'BBB'}])


def _holdings():
    return pd.DataFrame(columns=['security_id','sector','weight'])


def _plan(rows=None,holdings=None,policy=None):
    return indicative_plans(_forecast() if rows is None else rows,
        _holdings() if holdings is None else holdings,equity=100_000.,cash=100_000.,
        frozen_at_utc='2026-11-11T22:00:00Z',policy=policy or PlanPolicy())


def test_plans_are_risk_bounded_and_nonexecutable():
    out=_plan()
    assert out['status']=='RESEARCH_PLANS_ONLY' and not out['real_orders_enabled']
    assert len(out['plans'])==2
    assert sum(x['indicative_weight'] for x in out['plans'])<=.5
    for entry in out['plans']:
        assert entry['indicative_weight']==pytest.approx(.075)
        assert entry['indicative_shares']==75
        assert entry['estimated_net_edge']>0
        assert entry['execution_eligible'] is False and entry['research_only'] is True
        assert entry['stop_rule']=='2.0xATR_FROM_ACTUAL_ENTRY_FILL'
    assert len(out['content_sha256'])==64


def test_uncalibrated_probability_and_future_inputs_block():
    rows=_forecast()
    rows.loc[0,'up_calibration_status']='INSUFFICIENT_CALIBRATION_EVENTS'
    rows.loc[1,'feature_available_at']='2026-11-12T21:10:00Z'
    out=_plan(rows)
    assert out['plans']==[]
    assert {r['reason'] for r in out['evaluated']}=={
        'MODEL_PROBABILITY_NOT_CALIBRATED','FUTURE_INPUT_OR_INVALID_ENTRY_WINDOW'}


def test_insufficient_net_edge_and_existing_holdings_block():
    rows=_forecast()
    rows['predicted_gross_return']=.001
    assert not _plan(rows)['plans']
    holdings=pd.DataFrame([{'security_id':'AAA','sector':'TECH','weight':.1}])
    result=_plan(holdings=holdings)
    assert len(result['plans'])==1 and result['plans'][0]['security_id']=='BBB'
    assert result['status']=='RESEARCH_PLANS_ONLY'


def test_unknown_sector_and_duplicate_signals_rejected():
    rows=_forecast()
    rows.loc[1,'sector']='UNKNOWN'
    out=_plan(rows)
    assert len(out['plans'])==1
    assert any(x['reason']=='SECTOR_UNKNOWN' for x in out['evaluated'])
    with pytest.raises(ValueError,match='Duplicate'):
        _plan(pd.concat([rows,rows.iloc[:1]],ignore_index=True))


def test_holdings_above_limit_and_incorrect_freeze_time_rejected():
    holdings=pd.DataFrame([{'security_id':'OTHER','sector':'FIN','weight':.51}])
    assert not _plan(holdings=holdings)['plans']
    rows=_forecast()
    rows['signal_time']='2026-11-12T23:30:00Z'
    assert not _plan(rows)['plans']
