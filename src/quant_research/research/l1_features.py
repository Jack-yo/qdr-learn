"""L1 feature registry, optional PIT measurement ingestion and dimension audit.

A feature definition is never proof of a connected feed or predictive validity.
Optional measurements remain descriptive and cannot establish PIT attestation.
"""
from __future__ import annotations
import re
import numpy as np
import pandas as pd

DOMAINS = {
 'price':'价格与趋势','breadth':'市场广度','volatility':'波动结构',
 'options_pricing':'期权风险定价','options_positioning':'期权仓位与对冲',
 'microstructure':'微观结构','correlation':'相关性与离散度',
 'cross_asset':'跨资产传导','positioning':'资金与拥挤',
 'events':'宏观与事件','funding':'融资条件','path':'路径与尾部风险'
}
CORE = {
 'price':['market_return_1','market_return_5','market_return_20','market_overnight_return','market_intraday_return','market_close_location','market_return_acceleration'],
 'breadth':['breadth_up_share','breadth_above_ma20_share','breadth_new_low20_share','breadth_down_dollar_volume_share','breadth_impulse_5','breadth_price_divergence'],
 'volatility':['market_vol_5','market_vol_20','market_vol_ratio','market_downside_rv20','market_vol_change_5'],
 'correlation':['sector_dispersion_5','sector_corr_20','stock_dispersion_1'],
 'cross_asset':['equal_weight_relative_return_5','credit_proxy_relative_return_5','small_cap_relative_return_5'],
 'path':['market_gap_abs_5','market_range_5'],
}
OPTIONAL = {
 'volatility':['vix_30d','vvix'],
 'options_pricing':['vix_term_30_90','put_25d_iv_minus_call','implied_minus_realized_var','put_call_volume_ratio'],
 'options_positioning':['oi_expiry_concentration','oi_strike_concentration','zero_dte_volume_share','dealer_gamma_scenario'],
 'microstructure':['quoted_spread_bps','book_imbalance','trade_sign_imbalance','price_impact_bps'],
 'cross_asset':['treasury_2y_change','treasury_10y_change','hy_oas_change','move_level','dxy_return_5','gold_return_5'],
 'positioning':['etf_flow_pct_aum','cot_position_percentile','short_interest_pct_float'],
 'events':['fomc_countdown','option_expiry_countdown','macro_surprise','earnings_weight_share'],
 'funding':['sofr_iorb_spread','commercial_paper_spread','financial_conditions_index','repo_stress_proxy']
}
REGISTRY={k:d for d,names in {**CORE, **{k:CORE.get(k,[])+v for k,v in OPTIONAL.items()}}.items() for k in names}
# Merge explicitly rather than letting dict overwrite overlap domains.
REGISTRY={feature:domain for source in (CORE,OPTIONAL) for domain,names in source.items() for feature in names}
assert set(DOMAINS)==set(REGISTRY.values())
OPTIONAL_NAMES={x for vals in OPTIONAL.values() for x in vals}


def add_l1_features(base:pd.DataFrame, bars:pd.DataFrame, cutoffs:pd.DataFrame,
                    optional:pd.DataFrame|None=None) -> tuple[pd.DataFrame,pd.DataFrame]:
    """Compute feasible extras; require explicit dated evidence for optional feeds.

    All output observations retain research-only qualification. Any late measurement
    is blocked rather than backdated. Missing PIT sources remain null.
    """
    out=base.sort_values('date').copy().reset_index(drop=True)
    dates=pd.to_datetime(out.date)
    if dates.duplicated().any():raise ValueError('Duplicate observation session')
    out['market_return_acceleration']=out.market_return_5.div(5)-out.market_return_20.div(20)
    out['market_vol_change_5']=out.market_vol_20.div(out.market_vol_20.shift(5))-1
    out['breadth_impulse_5']=out.breadth_up_share-out.breadth_up_share.shift(5)
    out['breadth_price_divergence']=out.breadth_impulse_5-out.market_return_5
    bars=bars.copy();bars['date']=pd.to_datetime(bars.date)
    spy=bars.loc[bars.symbol.eq('SPY')].sort_values('date')
    spy=out[['date']].merge(spy,on='date',validate='one_to_one',how='left')
    out['market_gap_abs_5']=(spy.open.div(spy.close.shift(1))-1).abs().rolling(5,min_periods=5).mean()
    out['market_range_5']=((spy.high-spy.low)/spy.open).rolling(5,min_periods=5).mean()
    out['sector_dispersion_5']=np.nan
    out['sector_corr_20']=np.nan
    out['stock_dispersion_1']=np.nan
    # The equity level cross-section is only complete when base breadth is eligible.
    good_dates=set(out.loc[out.breadth_status.eq('RESEARCH_ONLY_UNATTESTED_PIT') &
                       out.breadth_bar_coverage.ge(.98),'date'])
    if good_dates and 'security_id' in bars and universe is not None:
        # Reconstruct one-day security returns only when its previous *market*
        # session exists; do not infer history from today's surviving symbols.
        universe_ids=universe.copy();universe_ids['date']=pd.to_datetime(universe_ids.date)
        members=universe_ids.loc[universe_ids.is_member.eq(True),['date','security_id']]
        b=bars.sort_values(['security_id','date']).copy()
        by=b.groupby('security_id',sort=False)
        b['prev_close']=by.close.shift(1)
        b['prev_date']=by.date.shift(1)
        prior=out.date.shift(1)
        prev_map=dict(zip(out.date,prior))
        b['is_consecutive']=b.prev_date.eq(b.date.map(prev_map))
        b['return_one']=b.close.div(b.prev_close).sub(1).where(b.is_consecutive)
        member_bars=members.merge(b[['date','security_id','return_one']],on=['date','security_id'],how='left',validate='one_to_one')
        for d,g in member_bars.loc[member_bars.date.isin(good_dates)].groupby('date'):
            values=g.return_one.dropna()
            if len(g)>=30 and len(values)/len(g)>=min_stock_coverage:
                out.loc[out.date.eq(d),'stock_dispersion_1']=float(values.std(ddof=0))
    sectors=['XLK','XLF','XLE','XLV','XLI','XLP','XLY','XLU','XLB','XLRE']
    sec=bars.loc[bars.symbol.isin(sectors)].pivot(index='date',columns='symbol',values='close').reindex(dates)
    if sec.shape[1]>=6:
        all_present=sec.notna().all(axis=1)
        rr=sec.pct_change(fill_method=None)
        for i in range(20,len(out)):
            if not all_present.iloc[i-20:i+1].all():continue
            s=rr.iloc[i-19:i+1]
            corr=s.corr().to_numpy()
            triangle=corr[np.triu_indices_from(corr,1)]
            if np.isfinite(triangle).all():out.loc[i,'sector_corr_20']=triangle.mean()
            out.loc[i,'sector_dispersion_5']=(sec.iloc[i]/sec.iloc[i-5]-1).std(ddof=0)
    clock=cutoffs[['date','decision_cutoff_utc']].copy();clock.date=pd.to_datetime(clock.date)
    clock.decision_cutoff_utc=pd.to_datetime(clock.decision_cutoff_utc,utc=True)
    audits=[]
    if optional is not None:
        fields={'date','feature_id','value','available_at','source','source_snapshot_sha256','source_attested'}
        if missing:=fields-set(optional):raise ValueError(f'Optional measurement missing {sorted(missing)}')
        extra=optional.copy();extra.date=pd.to_datetime(extra.date)
        extra.available_at=pd.to_datetime(extra.available_at,utc=True)
        if extra.duplicated(['date','feature_id']).any():raise ValueError('Duplicate optional feature')
        if not extra.feature_id.isin(OPTIONAL_NAMES).all():raise ValueError('Unknown optional feature')
        if not extra.source_attested.isin([True,False]).all():raise ValueError('Invalid attestation flag')
        if not extra.source_snapshot_sha256.astype(str).str.fullmatch('[a-f0-9]{64}').all():raise ValueError('Missing valid provider digest')
        extra.value=pd.to_numeric(extra.value,errors='coerce')
        if not np.isfinite(extra.value.to_numpy(dtype=float)).all():raise ValueError('Invalid optional numeric value')
        extra=extra.merge(clock,on='date',how='left',validate='many_to_one')
        if extra.decision_cutoff_utc.isna().any():raise ValueError('Optional feature outside sessions')
        extra['valid']=extra.source_attested.eq(True)&extra.available_at.le(extra.decision_cutoff_utc)
        for name,g in extra.groupby('feature_id'):
            out[name]=out.date.map(g.set_index('date').value.where(g.set_index('date').valid))
        for r in extra.itertuples(index=False):
            audits.append({'date':r.date,'feature':r.feature_id,'status':'OBSERVED' if r.valid else 'BLOCKED',
                           'source':r.source,'available_at':r.available_at,'reason':'ON_TIME_AND_ATTESTED' if r.valid else 'LATE_OR_UNATTESTED'})
    specific={(r['date'],r['feature']):r for r in audits}
    for name in REGISTRY:
        if name not in out:out[name]=np.nan
    for r in out.itertuples(index=False):
        for feature in REGISTRY:
            key=(r.date,feature)
            if key not in specific:
                val=getattr(r,feature)
                specific[key]={'date':r.date,'feature':feature,'status':'OBSERVED' if pd.notna(val) else 'MISSING',
                               'source':'calculated' if feature not in OPTIONAL_NAMES else 'external',
                               'available_at':r.decision_cutoff_utc,'reason':'COMPUTED_OR_PRESENT' if pd.notna(val) else 'NOT_AVAILABLE'}
    return out,pd.DataFrame(list(specific.values())).sort_values(['date','feature']).reset_index(drop=True)


def domain_status(features:pd.DataFrame,audit:pd.DataFrame,*,asof=None)->list[dict]:
    date=pd.Timestamp(asof) if asof is not None else features.date.max()
    rows=features.loc[features.date.eq(date)]
    if len(rows)!=1:raise ValueError('No unique session')
    row=rows.iloc[0];ans=[]
    for domain,title in DOMAINS.items():
        names=[x for x,d in REGISTRY.items() if d==domain]
        valid=[x for x in names if pd.notna(row.get(x))]
        blocked=audit.loc[audit.date.eq(date)&audit.feature.isin(names),'status'].eq('BLOCKED').any()
        status=('OBSERVED' if len(valid)==len(names) else 'PARTIAL') if valid else ('BLOCKED' if blocked else 'MISSING')
        lead=valid[0] if valid else None
        ans.append({'id':domain,'name':title,'status':status,
                    'value':None if lead is None else float(row[lead]),'label':lead,
                    'coverage':{'available':len(valid),'registered':len(names)},
                    'source_available_at':None})
    return ans