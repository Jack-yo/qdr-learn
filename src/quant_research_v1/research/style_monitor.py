"""Causal descriptive style states, not a fitted forecast or portfolio return model."""
import numpy as np
import pandas as pd
from datetime import datetime,timezone

from quant_research.clock import TradingClock
from quant_research.data.french_bundle import FACTORS


LABELS={'Mkt-RF':'市场超额收益','SMB':'小盘减大盘','HML':'价值减成长','RMW':'高盈利减低盈利',
        'CMA':'保守投资减激进投资','Mom':'动量','ST_Rev':'短期反转','RF':'无风险参考'}
PROTOCOL={'version':'french-descriptive-v1','windows':[5,20,60],'state_level':'mean(r,20)',
          'state_acceleration':'mean(r,5)-mean(r,20)','state_threshold':0,
          'aggregation':'ARITHMETIC_SUM_OF_DAILY_FACTOR_PREMIA_NOT_NAV','annualization_sessions':252,
          'threshold_fit':'NONE','trading_decision_eligible':False}


def monitor(bundle):
    frame=bundle.frame;meta=bundle.metadata;clock=TradingClock()
    sessions=clock.calendar.sessions_in_range(meta['start_date'],meta['asof_date_et'])
    frame['date']=pd.to_datetime(frame.date)
    if not frame.date.isin(sessions).all():raise ValueError('Factor date outside XNYS monitoring sessions')
    panel=frame.pivot(index='date',columns='factor_name',values='value_decimal').reindex(index=sessions,columns=FACTORS)
    availability=frame.pivot(index='date',columns='factor_name',values='available_at').reindex(index=sessions,columns=FACTORS)
    output=[]
    for factor in FACTORS:
        values=panel[factor]
        part=pd.DataFrame({'date':sessions,'factor_name':factor,'factor_label':LABELS[factor],
                           'daily_return':values.to_numpy(),'available_at':availability[factor].to_numpy()})
        for window in PROTOCOL['windows']:
            part[f'sum_{window}d']=values.rolling(window,min_periods=window).sum().to_numpy()
            times=pd.to_datetime(availability[factor],utc=True)
            available=pd.concat([times.shift(k) for k in range(window)],axis=1).max(axis=1)
            part[f'sum_{window}d_available_at']=available.where(part[f'sum_{window}d'].notna().to_numpy()).to_numpy()
        level=values.rolling(20,min_periods=20).mean()
        accel=values.rolling(5,min_periods=5).mean()-level
        part['volatility_20d_annualized']=(values.rolling(20,min_periods=20).std(ddof=1)*np.sqrt(252)).to_numpy()
        part['daily_mean_acceleration']=accel.to_numpy()
        states=np.select([(level>=0)&(accel>=0),(level>=0)&(accel<0),(level<0)&(accel>=0)],
                         ['强势加速','强势减速','弱势改善'],default='弱势恶化')
        states=pd.Series(states,index=sessions).where(level.notna()&accel.notna(),'UNKNOWN')
        if factor=='RF':states.loc[:]='REFERENCE_ONLY'
        part['state']=states.to_numpy()
        previous=states.shift(1)
        valid=states.isin(['强势加速','强势减速','弱势改善','弱势恶化'])
        part['state_changed']=(valid&previous.isin(['强势加速','强势减速','弱势改善','弱势恶化'])&states.ne(previous)).to_numpy()
        # A state depends on the entire 20-session input window, never on the row's timestamp alone.
        observed=pd.to_datetime(availability[factor],utc=True)
        required=pd.concat([observed.shift(k) for k in range(20)],axis=1).max(axis=1)
        part['state_available_at']=required.to_numpy()
        part['decision_eligible']=False
        part['missing_reason']=np.where(values.isna(),'SOURCE_ROW_MISSING_OR_NULL',
                                      np.where(part['sum_60d'].isna(),'INCOMPLETE_60_SESSION_WINDOW',''))
        output.append(part)
    history=pd.concat(output,ignore_index=True)
    latest=history.loc[history.date.eq(sessions[-1])].copy()
    latest['complete_5d']=latest.sum_5d.notna();latest['complete_20d']=latest.sum_20d.notna();latest['complete_60d']=latest.sum_60d.notna()
    missing=int(panel.isna().sum().sum())
    correlations=panel.tail(60).corr(min_periods=60).rename_axis(index='factor_a',columns='factor_b').stack(future_stack=True).rename('correlation').reset_index()
    now=datetime.now(timezone.utc)
    lag=sum(clock.close(s)+clock.delay<=now for s in clock.calendar.sessions_in_range(meta['asof_date_et'],now.date().isoformat()))-1
    result={**meta,'protocol':PROTOCOL,'latest_factor_date':meta['asof_date_et'],'source_lag_sessions_at_run':max(0,lag),
            'status':'DESCRIPTIVE_CURRENT_VINTAGE_ONLY' if latest.complete_60d.all() else 'PARTIAL_DATA_BLOCKED',
            'missing_factor_sessions':missing,'prediction_rows':0,'model_version':None,
            'eligibility':'OBSERVATION_OR_ATTRIBUTION_ONLY','state_method_version':PROTOCOL['version']}
    return history,latest,correlations,result
