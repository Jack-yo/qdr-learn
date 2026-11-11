"""V4 cross-sectional Alpha validation, explicitly not an execution backtest.

Ranks are matched against future independently verified excess-return labels.
Top/bottom spreads are descriptive label statistics; they omit portfolio
accounting, real fills, corporate-action cash timing, impact and crowding.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def evaluate_alpha_ranking(predictions: pd.DataFrame, *,
                           min_securities: int = 20, group_fraction: float = .20,
                           min_sessions: int = 60) -> tuple[pd.DataFrame,pd.DataFrame]:
    required={'date','security_id','variant','horizon','predicted_excess_return','excess_return'}
    if required-set(predictions):
        raise ValueError('Missing Alpha ranking/evaluation columns')
    if predictions.duplicated(['date','security_id','variant','horizon']).any():
        raise ValueError('Duplicate Alpha rank keys')
    if min_securities<5 or min_sessions<20 or not 0<group_fraction<=.5:
        raise ValueError('Invalid cross-sectional research protocol')
    daily=[]
    for (variant,horizon,day),frame in predictions.groupby(['variant','horizon','date']):
        sample=frame[['predicted_excess_return','excess_return']].apply(
            pd.to_numeric,errors='coerce').replace([np.inf,-np.inf],np.nan).dropna()
        if len(sample)<min_securities or sample.predicted_excess_return.nunique()<2 or sample.excess_return.nunique()<2:
            continue
        n=max(1,int(len(sample)*group_fraction))
        ranked=sample.sort_values('predicted_excess_return',ascending=False,kind='stable')
        score=sample.predicted_excess_return.rank(method='average').corr(
            sample.excess_return.rank(method='average'))
        daily.append({'variant':variant,'horizon':int(horizon),'date':day,
                      'securities':len(sample),'rank_ic':float(score),
                      'top_group_excess_return':float(ranked.excess_return.head(n).mean()),
                      'bottom_group_excess_return':float(ranked.excess_return.tail(n).mean()),
                      'long_short_group_spread':float(
                          ranked.excess_return.head(n).mean()-ranked.excess_return.tail(n).mean()),
                      'research_only':True})
    details=pd.DataFrame(daily)
    if details.empty:
        return pd.DataFrame(),details
    report=[]
    for (variant,horizon),part in details.groupby(['variant','horizon']):
        values=part.rank_ic.dropna()
        icir=float(values.mean()/values.std(ddof=1)) if len(values)>1 and values.std(ddof=1)>0 else None
        report.append({'variant':variant,'horizon':int(horizon),
                       'sessions':part.date.nunique(),
                       'mean_securities':float(part.securities.mean()),
                       'rank_ic_mean':float(values.mean()) if len(values) else None,
                       'rank_icir_unannualized':icir,
                       'top_group_excess_return_mean':float(part.top_group_excess_return.mean()),
                       'bottom_group_excess_return_mean':float(part.bottom_group_excess_return.mean()),
                       'mean_top_bottom_spread':float(part.long_short_group_spread.mean()),
                       'status':'OOS_CROSS_SECTION_STUDIED' if part.date.nunique()>=min_sessions
                                else 'INSUFFICIENT_OOS_SESSIONS',
                       'not_a_costed_portfolio_backtest':True,'research_only':True})
    return pd.DataFrame(report),details
