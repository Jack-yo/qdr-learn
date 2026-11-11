"""V4 Market Regime: separate market direction and downside forecasts.

The initial baseline deliberately excludes hindsight-revised breadth or
unverified credit spreads. Higher-complexity HMM/VAR-DY models remain
challengers, not presumed production predictors.
"""
from __future__ import annotations

import pandas as pd

from quant_research.models.v4_oos import OOSProtocol, run_oos, score_oos


def research_market_regime(*, states: pd.DataFrame, labels: pd.DataFrame,
                           exchange_sessions, trading_clock, evaluation_dates,
                           source_snapshot_sha256: str,
                           protocol: OOSProtocol = OOSProtocol()) -> dict:
    """Build an explicitly dated SPY research panel, then perform rolling OOS."""
    needed_states={'date','state_available_at'}
    needed_labels={'date','horizon','gross_return','excess_return','label_kind',
                   'entry_time','exit_time','available_at'}
    if needed_states-set(states) or needed_labels-set(labels):
        raise ValueError('Market state or return-label fields missing')
    if states.duplicated(['date']).any() or labels.duplicated(['date','horizon']).any():
        raise ValueError('Ambiguous SPY market observation dates')
    if not labels.horizon.isin((1,3,5)).all():
        raise ValueError('Unknown market forecast horizon')
    known = labels.gross_return.notna() | labels.excess_return.notna()
    if (labels.loc[known,'label_kind'].ne('VERIFIED_RAW_TRADE_TOTAL_RETURN').any()
            or labels.loc[~known,'label_kind'].ne('FUTURE_UNOBSERVED').any()
            or labels.loc[known,['gross_return','excess_return']].isna().any().any()):
        raise ValueError('Retrospective price-proxy outcomes cannot train Market Regime')
    state=states.copy()
    state['date']=pd.to_datetime(state.date)
    raw=labels.copy()
    raw['date']=pd.to_datetime(raw.date)
    feature_names=sorted(c for c in state if c.startswith('market_')
                         and pd.api.types.is_numeric_dtype(state[c]))
    initial=['market_return_5','market_vol_20']
    if not set(initial)<=set(feature_names):
        raise ValueError('Market baseline requires 5-day return and 20-day volatility')
    # Broad index participation requires historical stock-membership evidence;
    # an ETF breadth proxy can be used for research but must be named as such.
    other=[c for c in feature_names if not c.startswith('market_breadth_')]
    if len(other)<2:
        raise ValueError('No valid market predictors')
    panel=raw.merge(state[['date','state_available_at']+other],on='date',
                    validate='many_to_one',how='inner')
    if panel.empty:
        raise ValueError('No model/label overlap for market study')
    panel['security_id']='SPY'
    panel['signal_time']=panel.date.map(lambda day:pd.Timestamp(trading_clock.signal(day)))
    panel['feature_available_at']=pd.to_datetime(panel.state_available_at,utc=True)
    if panel.feature_available_at.gt(panel.signal_time).any():
        raise ValueError('Market state inputs were published after the signal')
    for (day,h),rows in panel.groupby(['date','horizon']):
        w=trading_clock.window(day,int(h))
        if not (pd.to_datetime(rows.entry_time,utc=True).eq(pd.Timestamp(w.entry_time)).all()
                and pd.to_datetime(rows.exit_time,utc=True).eq(pd.Timestamp(w.exit_time)).all()):
            raise ValueError('Market label mismatches exchange execution window')
    panel=panel.rename(columns={'available_at':'label_available_at'})
    groups={'M0':initial,'M1':other}
    predictions,folds=run_oos(panel,groups,exchange_sessions,protocol,evaluation_dates,
                              input_snapshot_sha256=source_snapshot_sha256)
    return {'status':'MARKET_OOS_RESEARCH_ONLY','model_variants':groups,
            'predictions':predictions,'folds':folds,
            'metrics':score_oos(predictions),
            'source_independently_attested':False,
            'historical_decision_eligible':False,'real_orders_enabled':False,
            'notes':['Downside probability is independently estimated, not 1 minus up probability',
                     'ETF breadth is descriptive and cannot stand in for PIT equity breadth',
                     'Probability calibration requires a chronological holdout and adequate event count']}
