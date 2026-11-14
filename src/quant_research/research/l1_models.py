"""Research-only L1 E01/E02/E03, purged rolling forward tests.

E01: forward realized volatility, rolling RV/EWMA and HAR-like Ridge.
E02: competing first-touch events, chronological multinomial calibration.
E03: conditional mean + volatility-scaled residual quantile distribution.
All metrics use predictions issued before labels matured. Never trade eligible.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge, LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, mean_squared_error
from scipy.special import softmax
from scipy.optimize import minimize_scalar
from quant_research.research.l1_observatory import aware_utc

HORIZONS=(1,3,5)
QUANTILES=np.array([.10,.25,.50,.75,.90])
EXTENDED_CANDIDATES=('market_return_acceleration','market_vol_change_5',
    'breadth_impulse_5','breadth_price_divergence','vix_term_30_90',
    'implied_minus_realized_var','sector_corr_20','sector_dispersion_5',
    'quoted_spread_bps','book_imbalance','credit_proxy_relative_return_5',
    'treasury_10y_change')
RETURN_FEATURES=('market_return_1','market_return_5','market_return_20',
                 'market_vol_5','market_vol_20','market_vol_ratio',
                 'market_downside_rv20','market_close_location')

@dataclass(frozen=True)
class L1Protocol:
    min_train_sessions:int=252
    train_window_sessions:int=1260
    embargo_sessions:int=5
    calibration_sessions:int=84
    refit_every:int=1
    upper_barrier:float=.02
    lower_barrier:float=.02
    seed:int=42
    def __post_init__(self):
        if not 30<=self.min_train_sessions<=self.train_window_sessions or self.embargo_sessions<5 or self.calibration_sessions<15 or self.refit_every<1 or not 0<self.upper_barrier<.5 or not 0<self.lower_barrier<.5:
            raise ValueError('Unsafe L1 protocol')


def _validate(bars, observations, cutoffs):
    req={'date','symbol','open','high','low','close','available_at'}
    if req-set(bars):raise ValueError('Missing benchmark OHLCV')
    if {'date','decision_cutoff_utc'}-set(cutoffs):raise ValueError('Missing decision clock')
    if {'date'}-set(observations):raise ValueError('Missing observation dates')
    c=cutoffs.copy();c.date=pd.to_datetime(c.date);c.decision_cutoff_utc=aware_utc(c.decision_cutoff_utc,'decision cutoff')
    if c.date.duplicated().any() or not c.date.is_monotonic_increasing or c.decision_cutoff_utc.isna().any():raise ValueError('Invalid trading calendar')
    o=observations.copy();o.date=pd.to_datetime(o.date)
    if o.date.duplicated().any():raise ValueError('Duplicate observations')
    b=bars.loc[bars.symbol.eq('SPY')].copy();b.date=pd.to_datetime(b.date);b.available_at=aware_utc(b.available_at,'bar available_at')
    if b.date.duplicated().any():raise ValueError('Duplicate SPY session')
    b=c.merge(b,on='date',how='left',validate='one_to_one')
    if b[['open','high','low','close']].isna().any().any() or b.available_at.isna().any():raise ValueError('Incomplete SPY calendar')
    if (b.available_at>b.decision_cutoff_utc).any():raise ValueError('Bar not known by signal cutoff')
    if not np.isfinite(b[['open','high','low','close']]).all().all() or (b[['open','high','low','close']]<=0).any().any() or (b.high<b[['open','low','close']].max(axis=1)).any() or (b.low>b[['open','high','close']].min(axis=1)).any():raise ValueError('Invalid OHLC')
    f=c.merge(o,on='date',how='left',validate='one_to_one')
    if 'decision_cutoff_utc_y' in f:
        f=f.drop(columns=['decision_cutoff_utc_y']).rename(columns={'decision_cutoff_utc_x':'decision_cutoff_utc'})
    if f[ list(RETURN_FEATURES) ].isna().all(axis=1).all():raise ValueError('No market features')
    return b,f,c


def first_touch_label(bars, origin_index:int, horizon:int, up:float, down:float):
    """OHLC touch relative to T+1 open; same-bar dual hit is UNKNOWN."""
    if origin_index+1>=len(bars) or origin_index+horizon>=len(bars):return None
    path=bars.iloc[origin_index+1:origin_index+horizon+1]
    entry=float(path.open.iloc[0]);high=entry*(1+up);low=entry*(1-down)
    for day in path.itertuples():
        hit_up=day.high>=high
        hit_down=day.low<=low
        if hit_up and hit_down:return 'AMBIGUOUS'
        if hit_up:return 'UP'
        if hit_down:return 'DOWN'
    return 'NEITHER'


def make_l1_labels(bars:pd.DataFrame,observations:pd.DataFrame,cutoffs:pd.DataFrame,
                   protocol:L1Protocol=L1Protocol()):
    """T features paired with future windows; labels carry actual availability."""
    b,f,c=_validate(bars,observations,cutoffs)
    daily=np.log(b.close/b.close.shift(1)).to_numpy(dtype=float)
    result=[]
    for i in range(len(b)):
        for h in HORIZONS:
            if i+h>=len(b):continue
            future=b.iloc[i+1:i+h+1]
            entry=float(future.open.iloc[0]);exit_close=float(future.close.iloc[-1])
            target=exit_close/entry-1
            rv=float(np.sqrt(252*np.mean(np.square(daily[i+1:i+h+1])))) if np.isfinite(daily[i+1:i+h+1]).all() else np.nan
            result.append({'date':b.date.iloc[i],'horizon':h,'gross_price_return':target,
                           'forward_rv':rv,'first_touch':first_touch_label(b,i,h,protocol.upper_barrier,protocol.lower_barrier),
                           'label_available_at':future.available_at.iloc[-1],
                           'exit_date':future.date.iloc[-1],
                           'entry_open':entry,'exit_close':exit_close})
    result=pd.DataFrame(result)
    return f.merge(result,on='date',how='left',validate='one_to_many')


def _features(train,test,columns):
    med=train[list(columns)].median(numeric_only=True).fillna(0)
    return (train[list(columns)].fillna(med).replace([np.inf,-np.inf],0),
            test[list(columns)].fillna(med).replace([np.inf,-np.inf],0))


def _ewma_rv(returns,decay=.94):
    """Annualized recursive EWMA of squared observed daily returns.

    The caller provides the purged training window, so this benchmark is
    deliberately lagged and never uses observations from the embargo gap.
    """
    if not 0 < decay < 1 or len(returns)==0:
        raise ValueError('EWMA requires returns and a decay between zero and one')
    squared=pd.to_numeric(returns,errors='coerce').dropna().pow(2)
    if squared.empty or not np.isfinite(squared).all():
        raise ValueError('EWMA requires finite returns')
    variance=squared.ewm(alpha=1-decay,adjust=False).mean().iloc[-1]
    return float(np.sqrt(252*max(0.0,variance)))


def _calibrate_multiclass(train_x,train_y,cal_x,cal_y,test_x,seed):
    classes=['UP','DOWN','NEITHER']
    if any(np.sum(train_y==s)<8 or np.sum(cal_y==s)<3 for s in classes):
        return None,'INSUFFICIENT_CLASS_HISTORY'
    base=make_pipeline(StandardScaler(),LogisticRegression(C=.5,max_iter=600,random_state=seed))
    base.fit(train_x,train_y)
    fitted_order=list(base[-1].classes_)
    cal_log=np.log(np.clip(base.predict_proba(cal_x),1e-9,1))
    idx=np.array([fitted_order.index(x) for x in cal_y])
    def nll(t):
        ps=softmax(cal_log / t,axis=1)
        return float(-np.log(np.maximum(1e-12,ps[np.arange(len(idx)),idx])).mean())
    opt=minimize_scalar(nll,bounds=(.4,5),method='bounded')
    if not opt.success:return None,'CALIBRATION_FAILED'
    pred=softmax(np.log(np.clip(base.predict_proba(test_x),1e-9,1))/opt.x,axis=1)[0]
    return {key:float(pred[fitted_order.index(key)]) for key in classes},'CALIBRATED_TEMP_HOLDOUT'


def _fit_predict(train:pd.DataFrame,test:pd.DataFrame,protocol:L1Protocol)->dict:
    """All fitted parameters arise from train observations only."""
    cols=[x for x in RETURN_FEATURES if x in train and x in test]
    # Candidate admission is strictly fitted on earlier observations.
    # Missing or constant optional feeds cannot influence this forecast.
    additions=[c for c in EXTENDED_CANDIDATES
               if c in train and c in test and pd.notna(test[c].iloc[0])
               and pd.to_numeric(train[c],errors='coerce').notna().mean()>=.85
               and pd.to_numeric(train[c],errors='coerce').std(skipna=True)>1e-12]
    cols+=additions[:12]
    x,tx=_features(train,test,cols)
    result={'features_used':cols,'extra_features_used':additions[:12]}
    # E01: volatility, no unseen future realization enters the features.
    rvtrain=train.dropna(subset=['forward_rv'])
    if len(rvtrain)<protocol.min_train_sessions:raise ValueError('Insufficient E01 labels')
    base_rv=float(rvtrain.forward_rv.tail(20).mean())
    ewma_rv=_ewma_rv(train.market_return_1.dropna()) if train.market_return_1.notna().sum()>=20 else base_rv
    reg=make_pipeline(StandardScaler(),Ridge(alpha=10))
    reg.fit(x.loc[rvtrain.index],np.log(np.maximum(rvtrain.forward_rv,1e-6)))
    pred_rv=float(np.exp(np.clip(reg.predict(tx)[0],-10,3)))
    result.update({'e01_rv_baseline':base_rv,'e01_rv_ewma':ewma_rv,'e01_rv_model':pred_rv})
    # E03: conditional mean and volatility-scaled residual distribution.
    y=train.gross_price_return.to_numpy(float)
    ret_model=make_pipeline(StandardScaler(),Ridge(alpha=25))
    ret_model.fit(x,y)
    pred_mu=float(ret_model.predict(tx)[0]);resid=y-ret_model.predict(x)
    base_quant=np.quantile(y,QUANTILES)
    sigma=max(float(np.std(resid,ddof=1)),1e-5)
    # Conditional RV acts as a positive forward risk scale; calibration depends
    # on the actual OOS hit rate and cannot be assumed from this fit.
    scale=np.clip(pred_rv / max(float(train.forward_rv.mean()),1e-5),.35,3)
    quant=np.sort(pred_mu+np.quantile(resid,QUANTILES)*scale)
    result.update({'e03_baseline_mean':float(np.mean(y)),'e03_baseline_quantiles':[float(t) for t in base_quant],
                   'e03_baseline_p_up':float((y>0).mean()),
                   'e03_baseline_p_downside':float((y<=-protocol.lower_barrier).mean()),
                   'e03_expected_return':pred_mu,'e03_quantiles':[float(t) for t in quant],
                   'e03_p_up_unverified':float((resid*scale+pred_mu>0).mean()),
                   'e03_p_downside_unverified':float((resid*scale+pred_mu<=-protocol.lower_barrier).mean())})
    # E02 needs chronological model, embargo, then independent calibration.
    valid=train.loc[train.first_touch.isin(['UP','DOWN','NEITHER'])].copy()
    if len(valid) < protocol.min_train_sessions or len(valid)<=protocol.calibration_sessions+30:
        result.update({'e02_probs':None,'e02_status':'INSUFFICIENT_EVENTS','e02_baseline':None})
    else:
        n_cal=protocol.calibration_sessions
        fit=valid.iloc[:-n_cal-protocol.embargo_sessions]
        cal=valid.iloc[-n_cal:]
        if len(fit)<30:
            result.update({'e02_probs':None,'e02_status':'INSUFFICIENT_CALIBRATION_WINDOW','e02_baseline':None})
        else:
            a,z=_features(fit,cal,cols);_,predict=_features(fit,test,cols)
            # Test and calibration use strictly fit-derived imputation.
            probs,stat=_calibrate_multiclass(a,fit.first_touch.to_numpy(),z,cal.first_touch.to_numpy(),predict,protocol.seed)
            prior=valid.first_touch.value_counts(normalize=True)
            result.update({'e02_probs':probs,'e02_status':stat,
                           'e02_baseline':{k:float(prior.get(k,0)) for k in ['UP','DOWN','NEITHER']}})
    result['research_only']=True
    return result


def _asof_train(panel:pd.DataFrame,sessions:pd.DatetimeIndex,asof,h,protocol):
    """Whole-calendar five-session embargo and labels actually available."""
    loc=sessions.get_loc(pd.Timestamp(asof))
    last=loc-protocol.embargo_sessions-1
    if last<0:return panel.iloc[:0]
    earliest=max(0,last-protocol.train_window_sessions+1)
    allowed=sessions[earliest:last+1]
    asof_clock=panel.loc[panel.date.eq(pd.Timestamp(asof)),'decision_cutoff_utc'].iloc[0]
    past=panel.loc[panel.horizon.eq(h)&panel.date.isin(allowed)
                   &panel.label_available_at.notna()
                   &panel.label_available_at.le(asof_clock)
                   &panel.forward_rv.notna()
                   &panel.gross_price_return.notna()].sort_values('date').copy()
    return past


def _distribution_loss(qs,y):
    qs=np.asarray(qs,float)
    err=y-qs
    return float(np.mean(np.maximum(QUANTILES*err,(QUANTILES-1)*err)))


def _bootstrap_delta(diffs,block=10,rounds=300,seed=42):
    a=np.asarray(diffs,dtype=float);a=a[np.isfinite(a)]
    if len(a)<40:return None
    rng=np.random.default_rng(seed)
    vals=[]
    for _ in range(rounds):
        ix=np.concatenate([np.arange(s,s+block)%len(a) for s in rng.integers(0,len(a),size=int(np.ceil(len(a)/block)))])[:len(a)]
        vals.append(float(a[ix].mean()))
    return [float(x) for x in np.quantile(vals,[.025,.975])]


def run_l1_oos(bars:pd.DataFrame,observations:pd.DataFrame,cutoffs:pd.DataFrame,
               protocol:L1Protocol=L1Protocol(),*,evaluation_start=None):
    """Deterministic fully matured fold research, never live trading approval.

    Evaluation folds use fixed chronological calendar embargo. For efficiency
    only every `refit_every`-th trading session is evaluated; metrics describe
    that explicit subset, not all market days.
    """
    panel=make_l1_labels(bars,observations,cutoffs,protocol)
    sessions=pd.DatetimeIndex(sorted(pd.to_datetime(cutoffs.date).unique()))
    start=pd.Timestamp(evaluation_start) if evaluation_start else sessions[protocol.min_train_sessions+protocol.embargo_sessions+protocol.calibration_sessions] if len(sessions)>protocol.min_train_sessions+protocol.embargo_sessions+protocol.calibration_sessions else sessions[-1]
    candidates=sessions[sessions>=start][::protocol.refit_every]
    outputs=[]
    for day in candidates:
        for h in HORIZONS:
            test=panel.loc[panel.date.eq(day)&panel.horizon.eq(h)]
            if len(test)!=1 or test.gross_price_return.isna().all():continue
            train=_asof_train(panel,sessions,day,h,protocol)
            if len(train)<protocol.min_train_sessions:continue
            if not train.date.lt(day).all():raise AssertionError('Forward leakage')
            model=_fit_predict(train,test,protocol)
            actual=test.iloc[0]
            outputs.append({'date':day,'horizon':h,'train_sessions':len(train),
                'train_last_date':train.date.max(),'train_last_label_available_at':train.label_available_at.max(),
                'signal_cutoff_utc':actual.decision_cutoff_utc,
                'target_return':float(actual.gross_price_return),
                'target_forward_rv':float(actual.forward_rv),
                'target_first_touch':actual.first_touch,
                **model})
    return pd.DataFrame(outputs)


def score_l1_oos(predictions:pd.DataFrame,protocol:L1Protocol=L1Protocol())->pd.DataFrame:
    if predictions.empty:return pd.DataFrame()
    report=[]
    for h,group in predictions.groupby('horizon'):
        y=group.target_return.to_numpy(float)
        rv=group.target_forward_rv.to_numpy(float)
        r1=group.e01_rv_model.to_numpy(float); r0=group.e01_rv_baseline.to_numpy(float)
        qloss=np.array([_distribution_loss(p,v) for p,v in zip(group.e03_quantiles,y)])
        baseline=np.array([_distribution_loss(p,v) for p,v in zip(group.e03_baseline_quantiles,y)])
        eligible=group[group.e02_probs.map(lambda x:isinstance(x,dict)) & group.target_first_touch.isin(['UP','DOWN','NEITHER'])]
        brier=brier0=event_logloss=None; event_n=0; event_counts={}
        if len(eligible):
            labels=['UP','DOWN','NEITHER'];obs=np.array([[float(x==actual) for x in labels] for actual in eligible.target_first_touch])
            pred=np.array([[p[k] for k in labels] for p in eligible.e02_probs]); prior=np.array([[p[k] for k in labels] for p in eligible.e02_baseline])
            brier=float(((pred-obs)**2).sum(axis=1).mean());brier0=float(((prior-obs)**2).sum(axis=1).mean());event_n=len(eligible)
            event_logloss=float(-np.sum(obs*np.log(np.clip(pred,1e-12,1)),axis=1).mean())
            chosen=np.argmax(pred,axis=1)
            for i,label in enumerate(labels):
                positive=obs[:,i].astype(bool); predicted=chosen==i
                event_counts[label]={'actual':int(positive.sum()),
                    'false_positives':int((predicted & ~positive).sum()),
                    'false_negatives':int((~predicted & positive).sum())}
        mean_pred=group.e03_expected_return.to_numpy(float)
        mean_base=group.e03_baseline_mean.to_numpy(float)
        up=(y>0).astype(float);down=(y<=-protocol.lower_barrier).astype(float)
        p_up=group.e03_p_up_unverified.to_numpy(float)
        p_down=group.e03_p_downside_unverified.to_numpy(float)
        quantiles=np.asarray(group.e03_quantiles.tolist(),dtype=float)
        report.append({'horizon':int(h),'samples':len(group),
          'e01_rv_mse':float(np.mean((r1-rv)**2)),'e01_baseline_mse':float(np.mean((r0-rv)**2)),
          'e01_ewma_mse':float(np.mean((group.e01_rv_ewma.to_numpy(float)-rv)**2)),
          'e01_paired_delta_95ci':_bootstrap_delta((r1-rv)**2-(r0-rv)**2,seed=protocol.seed),
          'e03_pinball_loss':float(qloss.mean()),'e03_baseline_pinball_loss':float(baseline.mean()),
          'e03_paired_delta_95ci':_bootstrap_delta(qloss-baseline,seed=protocol.seed),
          'e03_q10_q90_coverage':float(np.mean([(q[0]<=v<=q[4]) for q,v in zip(group.e03_quantiles,y)])),
          'e03_quantile_hit_rates':{f'q{int(q*100)}':float(np.mean(y<=quantiles[:,i])) for i,q in enumerate(QUANTILES)},
          'e03_mean_mse':float(np.mean((mean_pred-y)**2)),
          'e03_baseline_mean_mse':float(np.mean((mean_base-y)**2)),
          'e03_up_brier_unverified':float(np.mean((p_up-up)**2)),
          'e03_up_baseline_brier':float(np.mean((group.e03_baseline_p_up.to_numpy(float)-up)**2)),
          'e03_downside_brier_unverified':float(np.mean((p_down-down)**2)),
          'e03_downside_baseline_brier':float(np.mean((group.e03_baseline_p_downside.to_numpy(float)-down)**2)),
          'e03_probability_status':'NOT_CALIBRATED_RESEARCH_ONLY',
          'e03_downside_threshold':-protocol.lower_barrier,
          'e02_scored_samples':event_n,'e02_brier':brier,'e02_baseline_brier':brier0,
          'e02_log_loss':event_logloss,
          'e02_event_counts':event_counts,
          'e02_ambiguous_samples':int(group.target_first_touch.eq('AMBIGUOUS').sum()),
          'research_only':True,'model_admitted':False})
    return pd.DataFrame(report)


def forecast_l1_research(bars:pd.DataFrame,observations:pd.DataFrame,
                         cutoffs:pd.DataFrame,protocol:L1Protocol=L1Protocol(),*,asof=None):
    """Latest as-of research calculation; never asserts it was frozen at T."""
    panel=make_l1_labels(bars,observations,cutoffs,protocol)
    sessions=pd.DatetimeIndex(sorted(pd.to_datetime(cutoffs.date).unique()))
    day=pd.Timestamp(asof) if asof else sessions[-1]
    if day not in sessions:raise ValueError('As-of date not on exchange calendar')
    out=[]
    # Explicit current inference row: future label unobserved, only features.
    current=panel.loc[panel.date.eq(day)].head(1)
    if current.empty:raise ValueError('No as-of features')
    for h in HORIZONS:
        past=_asof_train(panel,sessions,day,h,protocol)
        if len(past)<protocol.min_train_sessions:
            out.append({'horizon':h,'status':'INSUFFICIENT_TRAINING_HISTORY','forecast':None})
            continue
        pred=_fit_predict(past,current,protocol)
        out.append({'horizon':h,'status':'RETROSPECTIVE_RESEARCH_ONLY','forecast':pred,
                    'train_last_date':str(past.date.max().date()),
                    'train_last_label_available_at':past.label_available_at.max().isoformat(),
                    'train_sessions':len(past)})
    return {'asof_session':str(day.date()),'status':'RETROSPECTIVE_RESEARCH_ONLY',
            'model_version':'l1-e01e02e03-v3-'+hashlib.sha256(json.dumps(protocol.__dict__,sort_keys=True).encode()).hexdigest()[:16],
            'research_only':True,'trade_eligible':False,'horizons':out}
