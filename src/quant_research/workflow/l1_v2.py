"""L1 V2: on-demand 12-domain market scanner and lightweight conditional research.

Retrospective analog frequencies are NEVER admitted as live calibrated forecasts.
No warehouse, no model training requirement, no synthetic fallback in production.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import math
import numpy as np
import pandas as pd
from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable

DOMAIN_NAMES={
 'price':'价格与趋势','breadth':'市场广度','volatility':'波动率结构',
 'options_pricing':'期权风险定价','options_positioning':'期权仓位与对冲',
 'microstructure':'市场微观结构','correlation':'相关性与离散度',
 'cross_asset':'跨资产风险传导','positioning':'资金流与持仓拥挤',
 'events':'宏观与事件冲击','funding':'融资与金融条件',
 'path':'路径与尾部风险',
}
HORIZONS=(1,3,5)
SECTORS=('XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY')


def normalize_bars(raw):
    """Per ETF daily bars, with no as-of reconstruction or corporate-action claim."""
    rows=[]
    for symbol, bars in raw.items():
        for r in bars:
            if not all(k in r for k in ('t','o','h','l','c','v')):continue
            try:
                date=pd.Timestamp(r['t']).tz_convert('America/New_York').date().isoformat()
                o,h,l,c,v=[float(r[k]) for k in ('o','h','l','c','v')]
                if not (0<l<=min(o,c)<=max(o,c)<=h and v>=0 and all(math.isfinite(x) for x in (o,h,l,c,v))):continue
                rows.append({'date':date,'symbol':symbol,'open':o,'high':h,'low':l,'close':c,'volume':v})
            except (ValueError,TypeError,OverflowError):continue
    if not rows:raise SourceUnavailable('NO_VALID_MARKET_BARS')
    data=pd.DataFrame(rows)
    if data.duplicated(['date','symbol']).any():raise SourceUnavailable('DUPLICATE_BARS')
    return data.sort_values(['date','symbol']).reset_index(drop=True)


def _z(series, window=100):
    past=series.rolling(window,min_periods=40).mean().shift(1)
    spread=series.rolling(window,min_periods=40).std().shift(1)
    return ((series-past)/spread.where(spread>1e-9)).clip(-3,3)


def build_scores(bars):
    if not {'SPY','IWM','RSP','HYG','LQD'}.issubset(set(bars.symbol)):
        raise SourceUnavailable('MARKET_CORE_SYMBOLS_MISSING')
    close=bars.pivot(index='date',columns='symbol',values='close').sort_index()
    open_=bars.pivot(index='date',columns='symbol',values='open').reindex(close.index)
    high=bars.pivot(index='date',columns='symbol',values='high').reindex(close.index)
    low=bars.pivot(index='date',columns='symbol',values='low').reindex(close.index)
    close=close.reindex(close.index)
    spy=close['SPY']; r=spy.pct_change(fill_method=None)
    spylog=np.log(spy/spy.shift(1))
    rv5=(spylog.pow(2).rolling(5,min_periods=5).mean()**.5)
    rv20=(spylog.pow(2).rolling(20,min_periods=20).mean()**.5)
    downside=(spylog.clip(upper=0).pow(2).rolling(20,min_periods=20).mean()**.5)
    relative=lambda a,b,n:close[a].pct_change(n,fill_method=None)-close[b].pct_change(n,fill_method=None)
    features=pd.DataFrame(index=close.index)
    features['spy_return_1']=r
    features['spy_return_5']=spy.pct_change(5,fill_method=None)
    features['spy_return_20']=spy.pct_change(20,fill_method=None)
    features['rv5']=rv5
    features['rv20']=rv20
    features['vol_ratio']=rv5/rv20.where(rv20>1e-9)
    features['downside_rv20']=downside
    features['breadth_proxy_rsp_spy_5']=relative('RSP','SPY',5)
    features['small_cap_relative_5']=relative('IWM','SPY',5)
    features['credit_proxy_hyg_lqd_5']=relative('HYG','LQD',5)
    features['drawdown20']=spy/spy.rolling(20,min_periods=20).max()-1
    features['overnight']=open_['SPY']/spy.shift(1)-1
    features['intraday']=spy/open_['SPY']-1
    features['close_location']=(spy-low['SPY'])/(high['SPY']-low['SPY']).replace(0,np.nan)
    sector_columns=[s for s in SECTORS if s in close]
    if len(sector_columns)>=8:
        sectors=close[sector_columns].pct_change(fill_method=None)
        features['sector_dispersion_1']=sectors.std(axis=1) # ETF proxy, not stock dispersion
        features['sector_up_share_1']=(sectors>0).where(sectors.notna()).mean(axis=1)
    if 'TLT' in close and 'SHY' in close:
        features['duration_proxy_5']=relative('TLT','SHY',5)
    features['momentum_z']=(.5*_z(features['spy_return_5'])+
                              .25*_z(features['breadth_proxy_rsp_spy_5'])+
                              .25*_z(features['small_cap_relative_5']))
    features['pressure_z']=(.30*_z(features['vol_ratio'])+
                              .25*_z(features['downside_rv20'])-
                              .25*_z(features['credit_proxy_hyg_lqd_5'])-
                              .20*_z(features['spy_return_5']))
    features['decay_z']=(features['pressure_z'].shift(5)-features['pressure_z'])
    return features.astype(float).replace([np.inf,-np.inf],np.nan), close, open_, high, low


def _event_targets(close, open_, high, low, t, h, *, up_barrier=.02, down_barrier=.015):
    """T+1 open to T+H close; unknown order within same candle remains ambiguous."""
    if t+h>=len(close):return None
    entry=open_['SPY'].iloc[t+1]
    exit_=close['SPY'].iloc[t+h]
    if not np.isfinite(entry) or not np.isfinite(exit_) or entry<=0:return None
    ret=float(exit_/entry-1)
    outcome='NEITHER'
    for i in range(t+1,t+h+1):
        hi,lo=high['SPY'].iloc[i],low['SPY'].iloc[i]
        if not (np.isfinite(hi) and np.isfinite(lo)):return None
        up=hi>=entry*(1+up_barrier)
        down=lo<=entry*(1-down_barrier)
        if up and down:
            outcome='AMBIGUOUS';break
        if up:outcome='UP';break
        if down:outcome='DOWN';break
    return ret,outcome


def _weighted_quantile(x,w,q):
    order=np.argsort(x);x=x[order];w=w[order]
    return float(np.interp(q,np.cumsum(w)/sum(w),x))


def _targets(close, open_, high, low, h):
    """Single pass over SPY bars; labels are internal-only, never treated as PIT."""
    n=len(close)
    o=open_['SPY'].to_numpy(float);c=close['SPY'].to_numpy(float)
    hi=high['SPY'].to_numpy(float);lo=low['SPY'].to_numpy(float)
    returns=np.full(n,np.nan); events=np.full(n,'INVALID',dtype=object)
    for i in range(n-h):
        entry=o[i+1]; exit_=c[i+h]
        if not np.isfinite(entry) or entry<=0 or not np.isfinite(exit_):continue
        returns[i]=exit_/entry-1
        outcome='NEITHER'
        for j in range(i+1,i+h+1):
            if not np.isfinite(hi[j]) or not np.isfinite(lo[j]):outcome='INVALID';break
            u=hi[j]>=entry*1.02;d=lo[j]<=entry*.985
            if u and d:outcome='AMBIGUOUS';break
            if u:outcome='UP';break
            if d:outcome='DOWN';break
        events[i]=outcome
    return returns,events


def _conditional_at(features,close,open_,high,low,t,h,min_samples=25,targets=None):
    keys=['momentum_z','pressure_z','decay_z']
    arr=features[keys].to_numpy(float)
    current=arr[t]
    if not np.all(np.isfinite(current)):return None
    if targets is None:targets=_targets(close,open_,high,low,h)
    rets,events=targets
    # T+H must have elapsed no later than current T. No in-flight target.
    stop=t-h+1
    positions=np.arange(55,stop)
    if len(positions)==0:return None
    valid=np.isfinite(arr[positions]).all(axis=1)&np.isfinite(rets[positions])&(events[positions]!='INVALID')
    positions=positions[valid]
    if len(positions)<min_samples:return None
    distance=np.linalg.norm(arr[positions]-current,axis=1)
    pick=np.argsort(distance)[:min(75,len(distance))]
    dist=distance[pick];selected=positions[pick]
    weights=np.exp(-dist**2/2)
    total=float(weights.sum());effective=total**2/max(float((weights**2).sum()),1e-12)
    if total<1e-12 or effective<min_samples:return None
    returns=rets[selected];w=weights/total
    sequence=events[selected]
    known=sequence!='AMBIGUOUS'
    unknown=int((~known).sum())
    result={'sample_count':len(selected),'effective_samples':round(effective,1),
         'expected_return':round(float(np.sum(w*returns)),6),
         'quantiles':[_weighted_quantile(returns,w,q) for q in (.10,.25,.50,.75,.90)],
         'up_frequency':round(float(w[returns>0].sum()),4),
         'first_touch':None,'unknown_sequence_count':unknown}
    if int(known.sum())>=min_samples and unknown/len(selected)<=.05:
        known_weights=w[known];den=known_weights.sum()
        result['first_touch']={x:round(float(w[(sequence==x)].sum()/den),4)
                               for x in ['UP','DOWN','NEITHER']}
    return result


def _paired_backtest(features,close,open_,high,low,h,*,min_cases=35,targets=None):
    if targets is None:targets=_targets(close,open_,high,low,h)
    returns,events=targets
    vals=[];end=len(close)-h-1
    for t in range(max(100,end-79),end+1,2):
        estimate=_conditional_at(features,close,open_,high,low,t,h,targets=targets)
        actual=returns[t]
        if not estimate or not np.isfinite(actual):continue
        historic=returns[35:t-h+1]
        valid=historic[np.isfinite(historic)]
        if len(valid)<25:continue
        y=float(actual>0)
        p=estimate['up_frequency'];bp=float((valid>0).mean())
        vals.append(((p-y)**2,(bp-y)**2))
    if len(vals)<min_cases:return {'status':'INSUFFICIENT_OOS','samples':len(vals)}
    x=np.asarray(vals)
    delta=float(np.mean(x[:,0]-x[:,1]))
    return {'status':'RETROSPECTIVE_EXPLORATORY','samples':len(vals),
            'up_brier':round(float(x[:,0].mean()),5),'baseline_up_brier':round(float(x[:,1].mean()),5),
            'delta_model_minus_baseline':round(delta,5),
            'qualified':False} # no independently attested PIT


def _score(value):
    return round(float(np.clip(50+15*value,0,100)),1) if pd.notna(value) else None


def _domain_catalog(features,extras,errors,close=None):
    last=features.iloc[-1]

    def input_coverage(field, value):
        if close is None:
            return (1 if pd.notna(value) else 0, 1, [])
        if field in {"overnight", "intraday", "close_location"}:
            available = 1 if pd.notna(value) else 0
            return available, 1, ["SPY"] if available else []
        requirements = {
            "spy_return_5": (("SPY",), 5),
            "spy_return_20": (("SPY",), 20),
            "breadth_proxy_rsp_spy_5": (("RSP", "SPY"), 5),
            "small_cap_relative_5": (("IWM", "SPY"), 5),
            "credit_proxy_hyg_lqd_5": (("HYG", "LQD"), 5),
            "duration_proxy_5": (("TLT", "SHY"), 5),
            "sector_dispersion_1": (SECTORS, 1),
            "sector_up_share_1": (SECTORS, 1),
            "drawdown20": (("SPY",), 19),
            "rv5": (("SPY",), 5),
            "rv20": (("SPY",), 20),
            "vol_ratio": (("SPY",), 20),
            "downside_rv20": (("SPY",), 20),
        }
        symbols, lookback = requirements.get(field, (("SPY",), 0))
        valid = []
        for symbol in symbols:
            if symbol not in close:
                continue
            series = pd.to_numeric(close[symbol], errors="coerce")
            if len(series) <= lookback:
                continue
            current = series.iloc[-1]
            prior = series.iloc[-1-lookback] if lookback else current
            if pd.notna(current) and pd.notna(prior) and prior > 0:
                valid.append(symbol)
        return len(valid), len(symbols), valid
    fields={
     'price':[('5日SPY涨跌','spy_return_5'),('20日SPY涨跌','spy_return_20'),('隔夜变化','overnight'),('日内变化','intraday')],
     'breadth':[('等权ETF强弱代理','breadth_proxy_rsp_spy_5'),('板块上涨占比代理','sector_up_share_1')],
     'volatility':[('实现波动RV5','rv5'),('RV5/RV20','vol_ratio'),('下行RV20','downside_rv20')],
     'correlation':[('板块ETF收益离散度','sector_dispersion_1')],
     'cross_asset':[('高收益信用代理','credit_proxy_hyg_lqd_5'),('久期ETF代理','duration_proxy_5')],
     'path':[('过去20日回撤','drawdown20')],
    }
    domain_items={k:[] for k in DOMAIN_NAMES}
    for k, rows in fields.items():
        for label,field in rows:
            val=last.get(field)
            coverage_n,expected_n,input_symbols=input_coverage(field,val)
            feature_status = ("MISSING" if pd.isna(val) else
                              "PARTIAL" if coverage_n < expected_n else "OBSERVED")
            domain_items[k].append({'id':field,'label':label,
                'value':round(float(val),6) if pd.notna(val) else None,
                'source':'ALPACA_ETF_PROXY','status':feature_status,
                'coverage_n':coverage_n,'expected_n':expected_n,
                'metadata':{'input_symbols':input_symbols,
                            'coverage_scope':'CORE_ETF_INPUTS_NOT_FULL_MARKET'}})
    # On-demand sourced contemporary metrics; without historical receipt evidence, NOT historical PIT.
    for domain,items in extras.items():
        domain_items[domain].extend(items)
    out=[]
    for domain,name in DOMAIN_NAMES.items():
        items=domain_items[domain]
        available=sum(1 for f in items if f.get('status') in ('OBSERVED','PARTIAL'))
        fully_observed=all(f.get('status')=='OBSERVED' for f in items)
        if not available:status='MISSING'
        elif domain in ('price','volatility','cross_asset','path') and available==len(items) and fully_observed and len(items)>1:status='OBSERVED'
        else:status='PARTIAL'
        reasons=[]
        if domain=='breadth':reasons.append('ETF代理非PIT全市场股票广度')
        if domain=='correlation':reasons.append('板块ETF离散度非全市场股票相关性')
        if domain=='options_pricing':reasons.append('VIX不足以代表完整期权偏斜与期限结构')
        if domain=='options_positioning':reasons.append('缺少可核验的期权完整仓位与交易商净头寸')
        if domain=='microstructure':reasons.append('缺少经授权的完整市场盘口数据')
        if domain=='positioning':reasons.append('缺少ETF实际申赎与历史COT数据')
        if domain=='events':reasons.append('缺少已发布的PIT经济事件日历及意外值')
        if domain=='funding':reasons.append('当前利率观测不能代替完整融资条件')
        if not items:reasons.append(errors.get(domain,'SOURCE_NOT_CONNECTED'))
        first=next((x for x in items if x.get('status')=='OBSERVED'),None)
        out.append({'id':domain,'name':name,'status':status,
                    'value':first['value'] if first else None,'label':first['label'] if first else None,
                    'coverage':{'available':available,'registered':len(items)},
                    'reason':'；'.join(reasons) or None,'features':items})
    return out


def analyze_market(bars, *, receipts, extras=None, errors=None, asof_limit=None, min_rows=180):
    extras=extras or {};errors=errors or {}
    bars=normalize_bars(bars) if isinstance(bars,dict) else bars.copy()
    if asof_limit is not None:bars=bars[bars.date<=str(asof_limit)]
    features,close,open_,high,low=build_scores(bars)
    if len(close)<min_rows:raise SourceUnavailable('INSUFFICIENT_MARKET_HISTORY')
    if close['SPY'].notna().mean()<.98:raise SourceUnavailable('SPY_HISTORY_COVERAGE_INSUFFICIENT')
    asof=str(close.index[-1])
    if pd.isna(close['SPY'].iloc[-1]):raise SourceUnavailable('SPY_LATEST_SESSION_MISSING')
    last=features.iloc[-1]
    if not all(pd.notna(last.get(x)) for x in ('momentum_z','pressure_z','decay_z')):
        raise SourceUnavailable('INSUFFICIENT_CORE_FEATURES')
    domain_items=_domain_catalog(features,extras,errors,close=close)
    by_domain={d['id']:d for d in domain_items}
    anomaly_names={'spy_return_5':'SPY 五日走势','breadth_proxy_rsp_spy_5':'等权ETF相对强度',
        'credit_proxy_hyg_lqd_5':'信用ETF相对强度','vol_ratio':'短期波动压力',
        'sector_dispersion_1':'行业收益离散度','drawdown20':'20日最大回撤'}
    anomalies=[]
    for key,name in anomaly_names.items():
        if key not in features:continue
        z=_z(features[key]).iloc[-1]
        if pd.notna(z) and abs(z)>=1.8 and pd.notna(last.get(key)):
            anomalies.append({'id':key,'label':name,'z_score':round(float(z),2),
                'value':round(float(last[key]),6),'status':'OBSERVATION_ONLY',
                'source':'ALPACA_ETF_PROXY'})
    anomalies.sort(key=lambda x:-abs(x['z_score']))
    output={'schema':'qdr.l1.v2','status':'OBSERVATION_ONLY','asof_session':asof,
            'source':'ALPACA','data_feed':receipts[0].get('feed') if receipts else 'UNKNOWN',
            'asof_basis':'LAST_COMPLETED_DAILY_BAR','historical_pit_verified':False,
            'basis':'RAW_PRICE_ONLY_NO_TOTAL_RETURN','fetched_at':receipts[0].get('fetched_at') if receipts else None,
            'source_receipts':receipts,'domains':domain_items,
            'quotes':{sym:round(float(close[sym].iloc[-1]),4) for sym in ['SPY','QQQ','IWM'] if sym in close and pd.notna(close[sym].iloc[-1])},
            'scores':{
                'momentum':_score(last['momentum_z']),
                'sell_pressure':_score(last['pressure_z']),
                'pressure_decay':_score(last['decay_z'])},
            'drivers':[], 'anomalies':anomalies[:8], 'horizons':{}}
    for col,label in [('spy_return_5','SPY 五日走势'),('breadth_proxy_rsp_spy_5','等权ETF相对强度'),
                      ('credit_proxy_hyg_lqd_5','信用ETF相对强度'),('vol_ratio','短期波动压力'),
                      ('sector_dispersion_1','行业离散度')]:
        value=last.get(col)
        if pd.notna(value):output['drivers'].append({'id':col,'label':label,'value':round(float(value),6),
            'status':'OBSERVATION_ONLY','is_predictive_driver':False,'source':'ALPACA_ETF'})
    t=len(close)-1
    for h in HORIZONS:
        targets=_targets(close,open_,high,low,h)
        analog=_conditional_at(features,close,open_,high,low,t,h,targets=targets)
        evidence=_paired_backtest(features,close,open_,high,low,h,targets=targets)
        output['horizons'][str(h)]={'horizon':h,'status':'HISTORICAL_ANALOG_RESEARCH_ONLY' if analog else 'INSUFFICIENT_ANALOG_SAMPLES',
            'analog':analog,'validation':evidence,
            'reliability':'NOT_CALIBRATED_NOT_PIT_VALIDATED',
            'up_barrier':.02,'down_barrier':-.015}
    return output


def current_l1_v2(root, *, refresh=False, sources=None, now=None):
    sources=sources or LiveSources(root)
    raw,receipts=sources.bars(refresh=refresh)
    # Determine last completely closed session from authoritative exchange calendar.
    from quant_research.clock import TradingClock
    stamp=now or datetime.now(timezone.utc)
    clock=TradingClock()
    latest=clock.calendar.date_to_session(stamp.date(),direction='previous')
    while clock.close(latest)+clock.delay>stamp:
        latest=clock.calendar.previous_session(latest)
    limit=latest.date().isoformat()
    errors={};extras={};snapshot_prices={}
    # Last trade and level-1 snapshots are observational only, never predictive PIT labels.
    try:
        snapshots,quote_receipt=sources.snapshots(refresh=refresh)
        for symbol,record in snapshots.items():
            trade=record.get('latestTrade') or record.get('latest_trade') or {}
            quote=record.get('latestQuote') or record.get('latest_quote') or {}
            px=trade.get('p',trade.get('price'))
            if px is not None and np.isfinite(float(px)) and float(px)>0:
                snapshot_prices[symbol]={'price':float(px),'at':trade.get('t',trade.get('timestamp')),
                    'source':quote_receipt['source'],'kind':'LAST_TRADE_MAY_BE_DELAYED'}
            bid=quote.get('bp',quote.get('bid_price'))
            ask=quote.get('ap',quote.get('ask_price'))
            if symbol=='SPY' and bid and ask and 0<float(bid)<float(ask):
                midpoint=(float(bid)+float(ask))/2
                spread=10000*(float(ask)-float(bid))/midpoint
                if spread<1000:
                    extras.setdefault('microstructure',[]).append({'id':'spy_level1_spread_bps',
                        'label':'SPY一级报价买卖价差 (bps)','value':round(spread,3),
                        'observed_date':limit,'source':quote_receipt['source'],
                        'fetched_at':quote_receipt['fetched_at'],
                        'status':'OBSERVED','pit':'QUOTE_ONLY_NOT_ORDER_BOOK'})
    except (SourceUnavailable,ValueError,TypeError,OverflowError,AttributeError) as exc:
        errors['microstructure']=getattr(exc,'code',type(exc).__name__)
    def load_cboe():return sources.cboe_vix(refresh=refresh)
    jobs={'vix':load_cboe}
    if sources.env.get('FRED_API_KEY'):
        jobs.update({'credit_spread':lambda:sources.fred('BAMLH0A0HYM2',refresh=refresh),
                     'treasury_yield':lambda:sources.fred('DGS10',refresh=refresh),
                     'sofr':lambda:sources.fred('SOFR',refresh=refresh)})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results={key:pool.submit(fn) for key,fn in jobs.items()}
        for key,task in results.items():
            try:
                values,receipt=task.result()
                present=[(d,v) for d,v in values.items() if d<=limit]
                if not present:raise SourceUnavailable('NO_RECENT_VALUE')
                d,val=max(present)
                if (pd.Timestamp(limit)-pd.Timestamp(d)).days>7:raise SourceUnavailable('STALE_EXTERNAL_VALUE')
                domain={'vix':'volatility','credit_spread':'cross_asset','treasury_yield':'cross_asset',
                        'sofr':'funding'}[key]
                if key=='vix':domain_extra='options_pricing'
                else:domain_extra=domain
                extras.setdefault(domain_extra,[]).append({'id':key,'label':{'vix':'VIX收盘','credit_spread':'高收益信用利差',
                           'treasury_yield':'10年期国债收益率','sofr':'SOFR'}[key],
                    'value':val,'observed_date':d,'source':receipt['source'],
                    'fetched_at':receipt['fetched_at'],'status':'OBSERVED','pit':'CURRENT_VINTAGE'})
            except (SourceUnavailable,ValueError,KeyError,TypeError) as exc:
                domain={'vix':'volatility','credit_spread':'cross_asset','treasury_yield':'cross_asset',
                        'sofr':'funding'}[key]
                errors[domain]=getattr(exc,'code',type(exc).__name__)
    if not sources.env.get('FRED_API_KEY'):
        errors.update({'funding':'FRED_API_KEY_NOT_CONFIGURED','cross_asset':'FRED_API_KEY_NOT_CONFIGURED'})
    result=analyze_market(raw,receipts=receipts,extras=extras,errors=errors,asof_limit=limit)
    result['latest_quotes']=snapshot_prices
    result['expected_asof_session']=limit
    result['data_freshness']='CURRENT_COMPLETED_SESSION' if result['asof_session']==limit else 'STALE_COMPLETED_SESSION'
    return result


def main(argv=None):
    """Manual/scheduled on-demand run; optional tiny immutable daily score digest."""
    import argparse
    import json
    from hashlib import sha256
    from pathlib import Path
    p=argparse.ArgumentParser(description='QDR L1 V2, bounded on-demand data and observation scores')
    p.add_argument('--root',default='.')
    p.add_argument('--refresh',action='store_true')
    p.add_argument('--save-summary',action='store_true')
    args=p.parse_args(argv)
    try:result=current_l1_v2(Path(args.root),refresh=args.refresh)
    except SourceUnavailable as exc:
        print(json.dumps({'status':'BLOCKED','code':exc.code}))
        return 2
    public={'schema':result['schema'],'asof_session':result['asof_session'],
        'status':result['status'],'scores':result['scores'],
        'coverage':[{k:d[k] for k in ('id','status','reason')} for d in result['domains']],
        'horizons':result['horizons'],'anomalies':result['anomalies'],
        'source_receipts':result['source_receipts']}
    if args.save_summary:
        root=Path(args.root)/'outputs'/'l1_v2_daily'
        root.mkdir(parents=True,exist_ok=True)
        name=result['asof_session']+'.json'
        data=json.dumps(public,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)
        dest=root/name
        # append-only, never silently rewrite historical findings
        try:
            with dest.open('x',encoding='utf-8') as stream:stream.write(data)
        except FileExistsError:
            print(json.dumps({'status':'EXISTS','path':str(dest)}))
        else:
            print(json.dumps({'status':'SAVED','path':str(dest),'sha256':sha256(data.encode()).hexdigest()}))
    print(json.dumps(public,ensure_ascii=False,allow_nan=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
