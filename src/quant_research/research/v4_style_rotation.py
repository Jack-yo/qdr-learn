"""V4 classic style observation and leading-return research.

ETF pairs are tradable style *proxies*, not equivalent to French long-short
factors. Historical French data may be revised and is not intraday available.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from quant_research.features.context import rolling_available
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


STYLE_PAIRS = {'small':('IWM','SPY'),'value':('IWD','IWF'),
               'momentum':('MTUM','SPY'),'quality':('QUAL','SPY'),
               'low_vol':('USMV','SPY')}


def style_observations(prices: pd.DataFrame, availability: pd.DataFrame,
                       pairs: dict = STYLE_PAIRS) -> pd.DataFrame:
    """Causal factor-style features from dated ETF prices; no forward fill."""
    if (not isinstance(prices.index,pd.DatetimeIndex)
            or not prices.index.equals(availability.index)
            or not prices.columns.equals(availability.columns)
            or prices.index.has_duplicates or not prices.index.is_monotonic_increasing):
        raise ValueError('Causal style prices/availability must share one calendar and universe')
    out=[]
    for style,(long_symbol,short_symbol) in pairs.items():
        if long_symbol not in prices or short_symbol not in prices:
            continue
        a,b=prices[long_symbol],prices[short_symbol]
        ratio=a.div(b.replace(0,np.nan))
        ret=ratio.pct_change(fill_method=None)
        rel5=ratio.div(ratio.shift(5))-1
        rel20=ratio.div(ratio.shift(20))-1
        previous5=ratio.shift(5).div(ratio.shift(10))-1
        lookback_available=rolling_available(availability[[long_symbol,short_symbol]],21).max(axis=1)
        complete=(prices[[long_symbol,short_symbol]].notna().rolling(
            21,min_periods=21).sum().eq(21).all(axis=1)
            & availability[[long_symbol,short_symbol]].notna().rolling(
            21,min_periods=21).sum().eq(21).all(axis=1))
        values=pd.DataFrame({
            'date':prices.index, 'style_id':style,
            'relative_return_5d':rel5.to_numpy(),
            'relative_return_20d':rel20.to_numpy(),
            'relative_acceleration_5d':(rel5-previous5).to_numpy(),
            'relative_up_days_10':ret.gt(0).where(ret.notna()).rolling(10,min_periods=10).sum().to_numpy(),
            'relative_volatility_20d':ret.rolling(20,min_periods=20).std(ddof=1).to_numpy(),
            'available_at':lookback_available.to_numpy(),
            'complete_historical_window':complete.to_numpy(),
            'long_symbol':long_symbol,'short_symbol':short_symbol})
        names=['relative_return_5d','relative_return_20d','relative_acceleration_5d',
               'relative_up_days_10','relative_volatility_20d']
        values.loc[~values.complete_historical_window,names]=np.nan
        out.append(values)
    if not out:
        raise ValueError('No ETF style pair has observed price history')
    return pd.concat(out,ignore_index=True)


def style_lead_oos(observations: pd.DataFrame, labels: pd.DataFrame,
                   exchange_sessions, evaluation_dates, trading_clock, *,
                   min_training_sessions: int = 252, gap_sessions: int = 5) -> pd.DataFrame:
    """Per-style quarterly Ridge OOS study of next-open to future-close spread.

    Outcome labels must come from independently verified action-consistent
    ETF returns. Nothing is marked decision-eligible by this calculation.
    """
    required={'date','style_id','horizon','forward_relative_return',
              'label_available_at','label_kind','signal_time','entry_time','exit_time'}
    if required-set(labels):
        raise ValueError('Future style spread labels need dated identity and availability')
    if not 30<=min_training_sessions<=2000 or gap_sessions<5:
        raise ValueError('Invalid training/embargo requirements')
    if labels.duplicated(['date','style_id','horizon']).any():
        raise ValueError('Duplicate style spread outcomes')
    observed=labels.forward_relative_return.notna()
    if labels.loc[observed,'label_kind'].ne('VERIFIED_RAW_RELATIVE_RETURN').any():
        raise ValueError('No retrospective ETF price proxy may train style forecasts')
    factors=['relative_return_5d','relative_return_20d','relative_acceleration_5d',
             'relative_up_days_10','relative_volatility_20d']
    joined=labels.merge(observations[['date','style_id','available_at']+factors],
                        on=['date','style_id'],validate='many_to_one',how='inner')
    if joined.empty:
        return pd.DataFrame()
    joined['date']=pd.to_datetime(joined.date)
    for column in ('label_available_at','signal_time','available_at','entry_time','exit_time'):
        joined[column]=pd.to_datetime(joined[column],utc=True)
    if joined.available_at.gt(joined.signal_time).any():
        raise ValueError('Style observations arrived after the signal')
    if joined.loc[joined.forward_relative_return.notna(),'label_available_at'].lt(
            joined.loc[joined.forward_relative_return.notna(),'exit_time']).any():
        raise ValueError('Style label was supposedly available before exit')
    for (day,horizon), part in joined.groupby(['date','horizon']):
        window=trading_clock.window(day,int(horizon))
        if not (part.signal_time.eq(pd.Timestamp(window.signal_time)).all()
                and part.entry_time.eq(pd.Timestamp(window.entry_time)).all()
                and part.exit_time.eq(pd.Timestamp(window.exit_time)).all()):
            raise ValueError('Style label timing violates T close to T+H exit')
    sessions=pd.DatetimeIndex(exchange_sessions)
    requested=pd.DatetimeIndex(evaluation_dates)
    if (sessions.has_duplicates or not sessions.is_monotonic_increasing or
            not requested.isin(sessions).all()):
        raise ValueError('Invalid exchange session calendar')
    rows=[]
    for quarter in requested.to_period('Q').unique():
        group_dates=requested[requested.to_period('Q')==quarter]
        start=group_dates.min()
        location=sessions.get_loc(start)
        if location<=gap_sessions:
            continue
        eligible_sessions=sessions[:location-gap_sessions]
        test=joined.loc[joined.date.isin(group_dates)].copy()
        if test.empty:
            continue
        fit_time=test.signal_time.min()
        train=joined.loc[joined.date.isin(eligible_sessions)
                         & joined.forward_relative_return.notna()
                         & joined.label_available_at.le(fit_time)].copy()
        for (style,horizon), future in test.groupby(['style_id','horizon']):
            past=train.loc[train.style_id.eq(style)&train.horizon.eq(horizon)].dropna(subset=factors)
            future=future.dropna(subset=factors)
            if past.date.nunique()<min_training_sessions or future.empty:
                continue
            model=make_pipeline(StandardScaler(),Ridge(alpha=1.0))
            model.fit(past[factors],past.forward_relative_return)
            part=future[['date','style_id','horizon','forward_relative_return']].copy()
            part['predicted_relative_return']=model.predict(future[factors])
            part['naive_relative_return']=float(past.forward_relative_return.mean())
            part['fit_time']=fit_time
            part['train_sessions']=past.date.nunique()
            part['research_only']=True
            part['decision_eligible']=False
            rows.append(part)
    return pd.concat(rows,ignore_index=True) if rows else pd.DataFrame()



def score_style_lead(predictions: pd.DataFrame, *, min_sessions: int = 60) -> pd.DataFrame:
    """Report strictly OOS performance against an expanding-window mean baseline."""
    required={'date','style_id','horizon','forward_relative_return',
              'predicted_relative_return','naive_relative_return'}
    if required-set(predictions):
        raise ValueError('Missing style leading-return prediction evidence')
    if predictions.duplicated(['date','style_id','horizon']).any():
        raise ValueError('Duplicate style forecasts')
    rows=[]
    for (style,horizon), group in predictions.groupby(['style_id','horizon']):
        group=group.dropna(subset=['forward_relative_return','predicted_relative_return','naive_relative_return'])
        if group.empty:
            continue
        mse=float(((group.predicted_relative_return-group.forward_relative_return)**2).mean())
        baseline=float(((group.naive_relative_return-group.forward_relative_return)**2).mean())
        rows.append({'style_id':style,'horizon':int(horizon),
                     'sessions':group.date.nunique(),'rows':len(group),
                     'oos_mse':mse,'naive_mse':baseline,
                     'mse_gain':baseline-mse,
                     'directional_accuracy':float((
                          group.predicted_relative_return.gt(0)==group.forward_relative_return.gt(0)).mean()),
                     'status':'RESEARCH_ONLY' if group.date.nunique()>=min_sessions
                              else 'INSUFFICIENT_OOS_SESSIONS',
                     'execution_eligible':False})
    return pd.DataFrame(rows)
