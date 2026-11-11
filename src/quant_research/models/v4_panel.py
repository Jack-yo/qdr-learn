"""V4 strict input adapter for market/style-conditioned individual-stock models.

Never use the legacy raw-to-price-proxy target fallback. Historical labels
need independently verified trade-price and corporate-action accounting.
Exploratory Yahoo labels are rejected before model training.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_RAW_LABEL = 'VERIFIED_RAW_TRADE_TOTAL_RETURN'
_UNOBSERVED = 'FUTURE_UNOBSERVED'
FEATURE_COLUMNS = {'date','security_id','feature_name','value','available_at','decision_eligible'}
LABEL_COLUMNS = {'date','security_id','horizon','entry_time','exit_time',
                 'available_at','gross_return','excess_return','label_kind'}
STATE_COLUMNS = {'date','state_available_at'}


def prepare_v4_alpha_panel(features: pd.DataFrame, labels: pd.DataFrame,
                           states: pd.DataFrame, clock, *,
                           expected_factor_names: list[str]) -> tuple[pd.DataFrame, dict]:
    """Join strict PIT factor rows, market/style conditions, and trade labels."""
    if FEATURE_COLUMNS - set(features):
        raise ValueError('Incomplete dated factor evidence')
    if LABEL_COLUMNS - set(labels):
        raise ValueError('Incomplete raw label contract')
    if STATE_COLUMNS - set(states):
        raise ValueError('Missing timestamped market/style conditions')
    if not expected_factor_names or len(expected_factor_names)!=len(set(expected_factor_names)):
        raise ValueError('Expected factor names must be unique')
    if not set(expected_factor_names) <= set(features.feature_name):
        raise ValueError('At least one required factor is missing')
    if features.duplicated(['date','security_id','feature_name']).any():
        raise ValueError('Duplicate factor/date/security')
    if labels.duplicated(['date','security_id','horizon']).any():
        raise ValueError('Duplicate horizon outcome labels')
    if states.duplicated(['date']).any():
        raise ValueError('Duplicate market/style conditions per session')
    if not features.decision_eligible.map(lambda x:type(x) is bool or type(x).__name__=='bool').all():
        raise ValueError('Ambiguous feature eligibility')
    chosen = features.loc[features.feature_name.isin(expected_factor_names)].copy()
    if chosen.decision_eligible.ne(True).any():
        raise ValueError('Retrospective or ineligible features cannot enter V4 alpha')
    features_wide = chosen.pivot(index=['date','security_id'],columns='feature_name',values='value').reset_index()
    availability = chosen.groupby(['date','security_id']).available_at.max().rename('factor_available_at').reset_index()
    features_wide = features_wide.merge(availability,on=['date','security_id'],validate='one_to_one')
    state = states.copy()
    feature_cols = [c for c in state if c not in STATE_COLUMNS]
    if not feature_cols:
        raise ValueError('No market/style condition features')
    frame = features_wide.merge(state,on='date',how='left',validate='many_to_one')
    if frame.state_available_at.isna().any():
        raise ValueError('Market/style conditions unavailable for one or more signal sessions')
    frame['feature_available_at'] = pd.concat([
        pd.to_datetime(frame.factor_available_at,utc=True),
        pd.to_datetime(frame.state_available_at,utc=True)],axis=1).max(axis=1)
    frame['date']=pd.to_datetime(frame.date)
    frame['signal_time'] = frame.date.map(lambda d:pd.Timestamp(clock.signal(d)))
    if frame.feature_available_at.gt(frame.signal_time).any():
        raise ValueError('Historical factor/state observations arrived after signal freeze')
    outcomes = labels.copy()
    known = outcomes.gross_return.notna() | outcomes.excess_return.notna()
    if outcomes.loc[known,'label_kind'].ne(_RAW_LABEL).any():
        raise ValueError('Price proxy labels cannot train executable Alpha models')
    if (outcomes.loc[known,['gross_return','excess_return']].isna().any().any()
            or outcomes.loc[~known,'label_kind'].ne(_UNOBSERVED).any()):
        raise ValueError('Missing complete or explicitly unobserved trade returns')
    if not outcomes.horizon.isin((1,3,5)).all():
        raise ValueError('Invalid holding period')
    outcomes = outcomes.rename(columns={'available_at':'label_available_at'})
    joined = frame.merge(outcomes,on=['date','security_id'],how='inner',validate='one_to_many')
    if joined.empty:
        raise ValueError('No matching legitimate Alpha labels or future forecast rows')
    for (day,horizon), part in joined.groupby(['date','horizon']):
        window=clock.window(day,int(horizon))
        if not (pd.to_datetime(part.entry_time,utc=True).eq(pd.Timestamp(window.entry_time)).all()
                and pd.to_datetime(part.exit_time,utc=True).eq(pd.Timestamp(window.exit_time)).all()):
            raise ValueError('Price label execution window differs from exchange clock')
    joined['gross_return'] = pd.to_numeric(joined.gross_return,errors='coerce')
    joined['excess_return'] = pd.to_numeric(joined.excess_return,errors='coerce')
    observed = joined.gross_return.notna()
    if (not np.isfinite(joined.loc[observed,['gross_return','excess_return']].to_numpy(dtype=float)).all()
            or joined.loc[observed,'label_available_at'].isna().any()
            or pd.to_datetime(joined.loc[observed,'label_available_at'],utc=True)
               .lt(pd.to_datetime(joined.loc[observed,'exit_time'],utc=True)).any()):
        raise ValueError('Invalid dated real trade labels')
    joined = joined.rename(columns={'factor_available_at':'factor_last_available_at'})
    return joined, {'status':'STRICT_CONTRACT_ASSEMBLED_SOURCE_AUDIT_STILL_REQUIRED',
                    'rows':len(joined),'stocks':joined.security_id.nunique(),
                    'factors':expected_factor_names,'market_style_columns':feature_cols,
                    'decision_eligible':False,'real_orders_enabled':False}
