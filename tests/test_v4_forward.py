"""Forward-model unit tests. Numeric fixtures are not actual market forecasts."""
import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.models.v4_forward import forecast_asof
from quant_research.models.v4_oos import OOSProtocol


def _sample():
    clock=TradingClock()
    sessions=clock.calendar.sessions_in_range('2024-01-01','2026-01-01')[:300]
    result=[]
    for day_index, day in enumerate(sessions):
        for horizon in (1,3,5):
            window=clock.window(day,horizon)
            for sid in ('AAA','BBB','CCC','DDD','EEE'):
                frozen=day==sessions[-1]
                j=ord(sid[-1])-ord('A')
                ret=[.04,-.035,.015,-.01][(day_index+j)%4]
                result.append({'date':day,'security_id':sid,'horizon':horizon,
                               'signal_time':pd.Timestamp(window.signal_time),
                               'feature_available_at':pd.Timestamp(window.signal_time)-pd.Timedelta(minutes=5),
                               'exit_time':pd.Timestamp(window.exit_time),
                               'label_available_at':pd.NaT if frozen else pd.Timestamp(window.exit_time)+pd.Timedelta(minutes=20),
                               'gross_return':np.nan if frozen else ret,
                               'excess_return':np.nan if frozen else ret-.001,
                               'alpha':float((day_index+j)%15)/15,
                               'market':float(day_index%31)/31,
                               'style':float((day_index+j*3)%17)/17})
    return pd.DataFrame(result), sessions


def _forecast(panel,sessions):
    return forecast_asof(panel,{'A':['alpha'],'B':['alpha','market'],
                               'C':['alpha','style'],'D':['alpha','market','style']},
                         sessions,sessions[-1],source_snapshot_sha256='a'*64,
                         protocol=OOSProtocol(min_training_sessions=35,training_window_sessions=150,
                                              calibration_sessions=16,gap_sessions=5,
                                              min_calibration_per_class=3))


def test_daily_forward_returns_are_frozen_and_not_executable():
    panel,sessions=_sample()
    result=_forecast(panel,sessions)
    assert result['status']=='FORWARD_RESEARCH_PREDICTIONS_ONLY'
    assert not result['execution_eligible'] and not result['real_orders_enabled']
    p=result['forecasts']
    assert not p.empty and not p.decision_eligible.any()
    assert p.date.nunique()==1 and p.date.iloc[0]==sessions[-1]
    assert set(p.model_variant)=={'A','B','C','D'}
    assert set(p.horizon)=={1,3,5}
    assert p.expected_gross_trade_return.notna().all()
    assert p.expected_excess_return.notna().all()
    assert p.model_version.str.startswith('v4-forecast-').all()
    cards=result['model_cards']
    assert cards.training_last_label_available.le(
        pd.Timestamp(panel.loc[panel.date.eq(sessions[-1]),'signal_time'].min())).all()


def test_never_read_or_accept_asof_future_outcomes():
    panel,sessions=_sample()
    with_result=_forecast(panel,sessions)
    invalid=panel.copy()
    invalid.loc[invalid.date.eq(sessions[-1]),'gross_return']=.9
    invalid.loc[invalid.date.eq(sessions[-1]),'excess_return']=.8
    with pytest.raises(ValueError,match='must not contain future'):
        _forecast(invalid,sessions)
    assert not with_result['forecasts'].empty


def test_feature_availability_and_digest_fail_closed():
    panel,sessions=_sample()
    invalid=panel.copy()
    invalid.loc[invalid.date.eq(sessions[-1]),'feature_available_at']=pd.Timestamp('2030-01-01',tz='UTC')
    with pytest.raises(ValueError,match='not known'):
        _forecast(invalid,sessions)
    with pytest.raises(ValueError,match='digest'):
        forecast_asof(panel,{'A':['alpha']},sessions,sessions[-1],source_snapshot_sha256='not-a-hash')
