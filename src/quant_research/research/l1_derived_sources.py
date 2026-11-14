"""Optional L1 feed mathematics; input records require real release timestamps.

The data provider adapter supplies raw point-in-time values. This module owns
spread, variance, concentration and hedging *scenario* calculations. A scenario
never becomes a measured dealer position or a guaranteed flow.
"""
from __future__ import annotations
from hashlib import sha256
import numpy as np
import pandas as pd


def _safe_div(a,b):
    if not np.isfinite(a) or not np.isfinite(b) or b<=0:return np.nan
    return float(a/b)


def derive_snapshot(raw:dict,*,rv20:float|None=None)->dict[str,float]:
    """Map dated vendor raw scalars to distinct derived market measurements."""
    data={}
    for k,v in raw.items():
        try:
            number=float(v)
        except (TypeError,ValueError):continue
        if np.isfinite(number):data[k]=number
    out={}
    def has(*keys):return all(k in data for k in keys)
    if has('vix_30d','vix_90d') and data['vix_90d']>0:
        out['vix_term_30_90']=data['vix_30d']/data['vix_90d']-1
    if has('put_25_delta_iv','call_25_delta_iv'):
        out['put_25d_iv_minus_call']=data['put_25_delta_iv']-data['call_25_delta_iv']
    if has('vix_30d') and rv20 is not None and np.isfinite(rv20):
        out['implied_minus_realized_var']=(data['vix_30d']/100)**2-float(rv20)**2
    if has('put_option_volume','call_option_volume'):
        out['put_call_volume_ratio']=_safe_div(data['put_option_volume'],data['call_option_volume'])
    if has('quoted_bid','quoted_ask') and data['quoted_ask']>=data['quoted_bid']>0:
        mid=(data['quoted_bid']+data['quoted_ask'])/2
        out['quoted_spread_bps']=1e4*(data['quoted_ask']-data['quoted_bid'])/mid
    if has('book_bid_size','book_ask_size') and data['book_bid_size']>=0 and data['book_ask_size']>=0:
        total=data['book_bid_size']+data['book_ask_size']
        out['book_imbalance']=(data['book_bid_size']-data['book_ask_size'])/total if total>0 else np.nan
    if has('etf_net_flow','etf_aum'):
        out['etf_flow_pct_aum']=_safe_div(data['etf_net_flow'],data['etf_aum'])
    if has('sofr','iorb'):
        out['sofr_iorb_spread']=100*(data['sofr']-data['iorb']) if raw.get('rate_unit')=='percent' else 1e4*(data['sofr']-data['iorb'])
    if has('released_macro_value','consensus_macro_value','macro_surprise_training_sigma') and data['macro_surprise_training_sigma']>0:
        out['macro_surprise']=(data['released_macro_value']-data['consensus_macro_value'])/data['macro_surprise_training_sigma']
    return {k:float(v) for k,v in out.items() if np.isfinite(v)}


def option_interest_concentration(options:pd.DataFrame)->dict[str,float]:
    """OI concentration only, not net dealer gamma or hedging direction."""
    if {'expiry','strike','open_interest'}-set(options):raise ValueError('Missing option chain OI fields')
    x=options.copy();x['open_interest']=pd.to_numeric(x.open_interest,errors='coerce')
    if x.open_interest.isna().any() or (x.open_interest<0).any() or not np.isfinite(x.open_interest).all():
        raise ValueError('Invalid option open interest')
    total=x.open_interest.sum()
    if total<=0:return {}
    return {'oi_expiry_concentration':float(x.groupby('expiry').open_interest.sum().max()/total),
            'oi_strike_concentration':float(x.groupby('strike').open_interest.sum().max()/total)}


def dealer_gamma_scenario(chain:pd.DataFrame,*,spot:float,contract_multiplier:int=100)->dict:
    """Optional scenario: signed dealer holdings must be independently supplied.

    1pct GEX dollar approximation = sum(position * gamma * S^2 * .01 * multiplier).
    No presumed customer/dealer sign is inferred from public OI.
    """
    need={'dealer_signed_contracts','gamma'}
    if need-set(chain):raise ValueError('Dealer-position scenario requires signed contracts and gamma')
    if not np.isfinite(spot) or spot<=0 or contract_multiplier<=0:raise ValueError('Invalid scenario spot')
    arr=chain[list(need)].apply(pd.to_numeric,errors='coerce').to_numpy()
    if not np.isfinite(arr).all():raise ValueError('Nonfinite gamma or signed holdings')
    signed=chain.dealer_signed_contracts.astype(float)
    gamma=chain.gamma.astype(float)
    exposure=float((signed*gamma).sum()*spot**2*.01*contract_multiplier)
    return {'dealer_gamma_scenario':exposure,'status':'SCENARIO_NOT_MEASURED_NET_DEALER_POSITION'}


def validate_event_calendar(events:pd.DataFrame,cutoff:pd.Timestamp)->pd.DataFrame:
    """Keep events known before cutoff; preserve future event dates, not future outcomes."""
    req={'event_id','scheduled_at','schedule_known_at','event_type'}
    if req-set(events):raise ValueError('Missing dated calendar evidence')
    x=events.copy();x['scheduled_at']=pd.to_datetime(x.scheduled_at,utc=True)
    x['schedule_known_at']=pd.to_datetime(x.schedule_known_at,utc=True)
    now=pd.Timestamp(cutoff)
    if now.tz is None:raise ValueError('UTC-aware cutoff required')
    return x.loc[x.schedule_known_at.le(now)].sort_values('scheduled_at').reset_index(drop=True)


def raw_packets_to_optional(raw:pd.DataFrame,cutoffs:pd.DataFrame,
                            observations:pd.DataFrame)->pd.DataFrame:
    """Turn dated raw provider measurements into calculated optional feature rows.

    Required raw columns: date, metric_name, value, available_at, source,
    source_snapshot_sha256, source_attested. Late or unverified measurements
    propagate as blocked downstream, never acquire a fictitious release time.
    """
    need={'date','metric_name','value','available_at','source','source_snapshot_sha256','source_attested'}
    if missing:=need-set(raw):raise ValueError(f'Raw measurement packet missing {sorted(missing)}')
    x=raw.copy();x.date=pd.to_datetime(x.date)
    x.available_at=pd.to_datetime(x.available_at,utc=True)
    if x.duplicated(['date','metric_name']).any():raise ValueError('Duplicate measurement')
    c=cutoffs[['date','decision_cutoff_utc']].copy();c.date=pd.to_datetime(c.date)
    c.decision_cutoff_utc=pd.to_datetime(c.decision_cutoff_utc,utc=True)
    x=x.merge(c,on='date',how='left',validate='many_to_one')
    if x.decision_cutoff_utc.isna().any():raise ValueError('Measurement outside calendar')
    x.value=pd.to_numeric(x.value,errors='coerce')
    if x.value.isna().any() or not np.isfinite(x.value).all():raise ValueError('Nonfinite raw measurement')
    obs=observations.copy();obs.date=pd.to_datetime(obs.date)
    output=[]
    for d,group in x.groupby('date'):
        # If any raw field needed by a derived field is late, the field is
        # still calculated but with source_attested=False, and blocked later.
        values=group.set_index('metric_name').value.to_dict()
        v=obs.loc[obs.date.eq(d),'market_vol_20']
        rv=float(v.iloc[0]) if len(v)==1 and pd.notna(v.iloc[0]) else None
        derived=derive_snapshot(values,rv20=rv)
        # Preserve pure upstream observed features (e.g. vix_30d).
        from quant_research.research.l1_features import OPTIONAL_NAMES
        derived.update({k:float(value) for k,value in values.items() if k in OPTIONAL_NAMES})
        for name,val in derived.items():
            output.append({'date':d,'feature_id':name,'value':val,
                'available_at':group.available_at.max(),
                'source':'L1_DERIVED_'+','.join(sorted(group.source.astype(str).unique())),
                'source_snapshot_sha256':sha256((''.join(sorted(group.source_snapshot_sha256.astype(str)))+name).encode()).hexdigest(),
                'source_attested':bool(group.source_attested.eq(True).all() and
                                       group.available_at.le(group.decision_cutoff_utc).all())})
    return pd.DataFrame(output,columns=['date','feature_id','value','available_at',
        'source','source_snapshot_sha256','source_attested'])