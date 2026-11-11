"""Strict model input adapters are tested with math fixtures, not market data."""
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.models.v4_oos import OOSProtocol
from quant_research.models.v4_panel import prepare_v4_alpha_panel
from quant_research.workflow.v4_market import research_market_regime


def _clock_rows(count=170):
    clock=TradingClock()
    sessions=clock.calendar.sessions_in_range('2024-01-01','2025-12-31')[:count]
    return clock,sessions


def test_alpha_panel_blocks_proxy_and_late_inputs():
    clock,sessions=_clock_rows()
    day=sessions[70]
    signal=pd.Timestamp(clock.signal(day))
    features=pd.DataFrame([{'date':day,'security_id':'AAA',
        'feature_name':'reversal_5d','value':.1,'available_at':signal-pd.Timedelta(minutes=2),
        'decision_eligible':True}])
    states=pd.DataFrame([{'date':day,'state_available_at':signal-pd.Timedelta(minutes=2),
                          'market_return_5':.02,'style_quality_relative_return_5d':.01}])
    labels=pd.DataFrame([{'date':day,'security_id':'AAA','horizon':h,
                          'entry_time':clock.window(day,h).entry_time,
                          'exit_time':clock.window(day,h).exit_time,
                          'available_at':pd.Timestamp(clock.window(day,h).exit_time)+pd.Timedelta(hours=1),
                          'gross_return':.02,'excess_return':.01,
                          'label_kind':'VERIFIED_RAW_TRADE_TOTAL_RETURN'} for h in (1,3,5)])
    panel,meta=prepare_v4_alpha_panel(features,labels,states,clock,
                                       expected_factor_names=['reversal_5d'])
    assert len(panel)==3 and meta['decision_eligible'] is False
    assert panel.excess_return.eq(.01).all()
    bad=labels.copy();bad['label_kind']='EXPLORATORY_PRICE_PROXY_NOT_FILL'
    with pytest.raises(ValueError,match='proxy'):
        prepare_v4_alpha_panel(features,bad,states,clock,expected_factor_names=['reversal_5d'])
    future=features.copy();future['available_at']=signal+pd.Timedelta(minutes=2)
    with pytest.raises(ValueError,match='after signal'):
        prepare_v4_alpha_panel(future,labels,states,clock,expected_factor_names=['reversal_5d'])


def test_market_oos_keeps_downside_separate_and_nonexecutable():
    clock,sessions=_clock_rows()
    conditions=[];labels=[]
    for i,day in enumerate(sessions):
        window=clock.window(day,5)
        conditions.append({'date':day,'state_available_at':pd.Timestamp(clock.signal(day))-pd.Timedelta(minutes=3),
                           'market_return_5':float(i%19)/100,
                           'market_vol_20':.12+float(i%7)/100,
                           'market_credit_5':float(i%11)/100})
        for h in (1,3,5):
            w=clock.window(day,h)
            gross=[.04,-.03,.01,-.005][i%4]
            labels.append({'date':day,'horizon':h,'gross_return':gross,
                           'excess_return':gross-.0005,
                           'label_kind':'VERIFIED_RAW_TRADE_TOTAL_RETURN',
                           'entry_time':w.entry_time,'exit_time':w.exit_time,
                           'available_at':pd.Timestamp(w.exit_time)+pd.Timedelta(minutes=20)})
    result=research_market_regime(states=pd.DataFrame(conditions),labels=pd.DataFrame(labels),
            exchange_sessions=sessions,trading_clock=clock,evaluation_dates=sessions[-20:],
            source_snapshot_sha256='a'*64,
            protocol=OOSProtocol(min_training_sessions=35,calibration_sessions=16,
                                 training_window_sessions=120,min_calibration_per_class=3))
    assert result['status']=='MARKET_OOS_RESEARCH_ONLY'
    assert not result['predictions'].empty
    assert not result['predictions'].decision_eligible.any()
    assert set(result['predictions'].variant)=={'M0','M1'}
    assert set(result['predictions'].horizon)=={1,3,5}
    invalid=pd.DataFrame(labels);invalid['label_kind']='EXPLORATORY_PRICE_PROXY_NOT_FILL'
    with pytest.raises(ValueError,match='proxy'):
        research_market_regime(states=pd.DataFrame(conditions),labels=invalid,
            exchange_sessions=sessions,trading_clock=clock,evaluation_dates=sessions[-20:],
            source_snapshot_sha256='a'*64)
