"""L1 complete offline research runner and read-only UI artifact gateway.

No external data fetching is performed here. Only externally supplied raw inputs
with dated availability may be analyzed. No output is granted trading eligibility.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import pandas as pd
import numpy as np
from quant_research.research.l1_observatory import compute_l1_observations,scan_l1_anomalies,aware_utc
from quant_research.research.l1_features import add_l1_features,domain_status,REGISTRY,scan_all_l1_anomalies
from quant_research.research.l1_models import (L1Protocol,run_l1_oos,score_l1_oos,
    forecast_l1_research,HORIZONS)

_DIGEST=re.compile('[a-f0-9]{64}\\Z')

class L1Blocked(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(code)


def _json(value):
    def default(o):
        if isinstance(o,(np.integer,)):return int(o)
        if isinstance(o,(np.floating,)):return float(o)
        if isinstance(o,(pd.Timestamp,datetime)):return o.isoformat()
        raise TypeError(type(o).__name__)
    return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,default=default)


def _read(path):
    p=Path(path)
    if not p.is_file():raise FileNotFoundError(str(p))
    if p.suffix=='.csv':return pd.read_csv(p)
    if p.suffix=='.parquet':return pd.read_parquet(p)
    raise ValueError('Only CSV/Parquet raw inputs supported')


def _serializable(frame):
    # CSV is deliberately transparent and optional Parquet dependency not needed.
    x=frame.copy()
    for col in x.select_dtypes(include=['datetime64[ns, UTC]','datetime64[ns]']).columns:
        x[col]=x[col].astype(str)
    for col in x:
        if x[col].map(lambda v:isinstance(v,(list,dict))).any():
            x[col]=x[col].map(lambda v:_json(v) if isinstance(v,(list,dict)) else v)
    return x


def feature_coverage_report(audit):
    """Summarize observed records without asserting provider or PIT qualification."""
    records=[]
    for feature, domain in REGISTRY.items():
        rows=audit.loc[audit.feature.eq(feature)].sort_values('date')
        observed=rows.loc[rows.status.eq('OBSERVED')]
        n=len(rows)
        sources=sorted(set(observed.source.dropna().astype(str)))
        records.append({'feature_id':feature,'domain':domain,
            'source':', '.join(sources) if sources else None,'frequency':'daily',
            'start_date':observed.date.min() if len(observed) else None,
            'end_date':observed.date.max() if len(observed) else None,
            'available_at':observed.available_at.max() if len(observed) else None,
            'coverage_ratio':len(observed)/n if n else 0.0,
            'missing_rate':(n-len(observed))/n if n else 1.0,
            'PIT_status':'NOT_INDEPENDENTLY_VERIFIED','research_eligible':False,
            'blocked_reason':'SOURCE_AND_HISTORICAL_PIT_NOT_INDEPENDENTLY_VERIFIED' if len(observed) else 'NO_OBSERVED_VALUES'})
    return pd.DataFrame(records)


def validate_research_calendar(cutoffs):
    """Require consecutive XNYS sessions and actual close-to-entry cutoffs."""
    from quant_research.clock import TradingClock
    if {'date','decision_cutoff_utc'}-set(cutoffs) or cutoffs.empty:
        raise ValueError('L1_CALENDAR_MISSING')
    dates=pd.to_datetime(cutoffs.date,errors='raise')
    if (dates.isna().any() or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all()
            or dates.duplicated().any() or not dates.is_monotonic_increasing):
        raise ValueError('L1_CALENDAR_INVALID')
    clock=TradingClock()
    sessions=pd.DatetimeIndex([clock.session(str(day.date())) for day in dates])
    expected=clock.calendar.sessions_in_range(sessions[0],sessions[-1])
    if not sessions.equals(expected):
        raise ValueError('L1_CALENDAR_INCOMPLETE')
    times=aware_utc(cutoffs.decision_cutoff_utc,'decision cutoff')
    now=pd.Timestamp.now(tz='UTC')
    for day,cutoff in zip(sessions,times):
        position=clock.calendar.sessions.get_loc(day)
        if position+1>=len(clock.calendar.sessions):
            raise ValueError('L1_CALENDAR_NEXT_SESSION_MISSING')
        next_open=clock.calendar.session_open(clock.calendar.sessions[position+1])
        if not pd.Timestamp(clock.close(day))<=cutoff<next_open or cutoff>now:
            raise ValueError('L1_CUTOFF_OUTSIDE_SESSION_WINDOW')


def build_l1_research(*,bars,cutoffs,output,universe=None,optional=None,raw_measurements=None,
                      protocol:L1Protocol=L1Protocol(),evaluation_start=None):
    """Implement all three research experiments; fail closed if no valid data."""
    paths={'bars':Path(bars),'cutoffs':Path(cutoffs)}
    if universe:paths['universe']=Path(universe)
    if optional:paths['optional']=Path(optional)
    if raw_measurements:paths['raw_measurements']=Path(raw_measurements)
    raw={k:_read(v) for k,v in paths.items()}
    validate_research_calendar(raw['cutoffs'])
    obs,coverage=compute_l1_observations(raw['bars'],raw['cutoffs'],raw.get('universe'))
    additional=raw.get('optional')
    if 'raw_measurements' in raw:
        from quant_research.research.l1_derived_sources import raw_packets_to_optional
        measured=raw_packets_to_optional(raw['raw_measurements'],raw['cutoffs'],obs)
        if additional is not None:additional=pd.concat([additional,measured],ignore_index=True)
        else:additional=measured
    feat,audit=add_l1_features(obs,raw['bars'],raw['cutoffs'],additional,universe=raw.get('universe'))
    anomalies=scan_all_l1_anomalies(feat)
    oos=run_l1_oos(raw['bars'],feat,raw['cutoffs'],protocol,evaluation_start=evaluation_start)
    metrics=score_l1_oos(oos,protocol)
    # Fitting at the most recent as-of is RETROSPECTIVE_RESEARCH_ONLY,
    # explicitly not a frozen real-time forecast.
    inferred=forecast_l1_research(raw['bars'],feat,raw['cutoffs'],protocol)
    root=Path(output)
    if root.exists():raise FileExistsError('Research output exists; no archive overwrite')
    root.mkdir(parents=True,exist_ok=False)
    outputs={'observations.csv':obs,'features.csv':feat,'coverage.csv':coverage,
             'feature_coverage.csv':feature_coverage_report(audit),
             'feature_audit.csv':audit,'anomalies.csv':anomalies,
             'oos_predictions.csv':oos,'oos_metrics.csv':metrics}
    hashes={}
    for name,frame in outputs.items():
        path=root/name; _serializable(frame).to_csv(path,index=False)
        hashes[name]=sha256(path.read_bytes()).hexdigest()
    inferred_path=root/'research_inference.json'
    inferred_path.write_text(_json(inferred),encoding='utf-8')
    hashes[inferred_path.name]=sha256(inferred_path.read_bytes()).hexdigest()
    manifest={'kind':'L1_RESEARCH_COMPLETE_V1','schema':'qdr.l1.market.v1',
        'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'asof_session':str(pd.Timestamp(feat.date.max()).date()),
        'model_version':inferred['model_version'],
        'registered_dimensions':12,'registered_features':len(REGISTRY),
        'observed_rows':len(obs),'oos_rows':len(oos),'oos_horizons':sorted(set(oos.horizon.astype(int))) if len(oos) else [],
        'source_snapshot_sha256':sha256(_json({k:sha256(v.read_bytes()).hexdigest() for k,v in paths.items()}).encode()).hexdigest(),
        'inputs_sha256':{k:sha256(v.read_bytes()).hexdigest() for k,v in paths.items()},
        'outputs_sha256':hashes,'source_independently_attested':False,
        'historical_pit_verified':False,'predictive_evidence_admitted':False,
        'execution_eligible':False,'real_orders_enabled':False,
        'status':'RETROSPECTIVE_RESEARCH_ONLY',
        'notice':'Model implementation and retrospective OOS research; NOT a live frozen prediction or trade signal.'}
    (root/'manifest.json').write_text(_json(manifest),encoding='utf-8')
    return manifest


def _verified_artifact(path):
    f=path/'manifest.json'
    if not f.is_file():raise L1Blocked('L1_NO_RESEARCH_ARCHIVE')
    manifest=json.loads(f.read_text(encoding='utf-8'))
    if manifest.get('kind')!='L1_RESEARCH_COMPLETE_V1' or manifest.get('execution_eligible') is not False or manifest.get('status')!='RETROSPECTIVE_RESEARCH_ONLY':
        raise L1Blocked('L1_INVALID_RESEARCH_SCOPE')
    for name,digest in manifest.get('outputs_sha256',{}).items():
        if not name or '/' in name or '\\' in name or name.startswith('.') or not _DIGEST.fullmatch(str(digest)) or not (path/name).is_file() or sha256((path/name).read_bytes()).hexdigest()!=digest:
            raise L1Blocked('L1_ARTIFACT_HASH_MISMATCH')
    needed={'features.csv','feature_audit.csv','anomalies.csv','oos_predictions.csv','oos_metrics.csv','research_inference.json'}
    if not needed<=set(manifest.get('outputs_sha256',{})):
        raise L1Blocked('L1_INCOMPLETE_RESEARCH_ARCHIVE')
    return manifest


def _latest(root):
    base=Path(root)/'outputs/l1_research'
    if not base.is_dir():raise L1Blocked('L1_NO_RESEARCH_ARCHIVE')
    folders=[p for p in base.iterdir() if p.is_dir() and (p/'manifest.json').is_file()]
    if not folders:raise L1Blocked('L1_NO_RESEARCH_ARCHIVE')
    folder=max(folders,key=lambda p:(p/'manifest.json').stat().st_mtime)
    return folder,_verified_artifact(folder)


def _recent_audit(root,asof=None):
    folder,manifest=_latest(root)
    features=pd.read_csv(folder/'features.csv',parse_dates=['date'])
    audit=pd.read_csv(folder/'feature_audit.csv',parse_dates=['date'])
    day=pd.Timestamp(asof or manifest['asof_session'])
    if day not in set(features.date):raise L1Blocked('L1_ASOF_NOT_FOUND')
    return folder,manifest,day,features,audit


def observations_for_api(root,asof=None):
    try:
        folder,m,day,feat,audit=_recent_audit(root,asof)
    except L1Blocked as exc:
        if exc.code!='L1_NO_RESEARCH_ARCHIVE':
            raise
        from quant_research.workflow.l1_current_observation import current_observation_for_api
        from quant_research.policy import PolicyError
        root=Path(root).resolve()
        try:
            return current_observation_for_api(root/'data/real_v21.duckdb',asof=asof,
                                               raw_root=root/'data/raw',symbols=['SPY'])
        except (PolicyError,ValueError,OSError) as error:
            raise L1Blocked(getattr(error,'code','L1_CURRENT_OBSERVATION_UNAVAILABLE')) from error
    row=feat.loc[feat.date.eq(day)].iloc[0]
    domains=domain_status(feat,audit,asof=day)
    relevant=audit.loc[audit.date.eq(day)].set_index('feature')
    detail=[]
    for feature,dimension in REGISTRY.items():
        audit_row=relevant.loc[feature] if feature in relevant.index else None
        status='MISSING' if audit_row is None else str(audit_row.status)
        raw=row.get(feature)
        value=float(raw) if pd.notna(raw) and status=='OBSERVED' else None
        detail.append({'id':feature,'domain':dimension,'status':status,'value':value,
                       'source':None if audit_row is None else str(audit_row.source),
                       'available_at':None if audit_row is None else str(audit_row.available_at),
                       'reason':'NOT_AVAILABLE' if audit_row is None else str(audit_row.reason),
                       'research_only':True})
    fields=['market_return_1','market_return_5','market_vol_20','breadth_up_share','market_vol_ratio']
    drivers=[]
    for col in fields:
        x=row.get(col)
        if pd.notna(x):drivers.append({'label':col,'value':float(x),'unit':'fraction','status':'OBSERVED',
                                      'delta':None,'oos_increment':None})
    return {'schema':'qdr.l1.market.v1','status':'OBSERVATION_ONLY','asof_session':str(day.date()),
            'knowledge_cutoff_utc':str(row.decision_cutoff_utc),
            'source_snapshot_sha256':m['source_snapshot_sha256'],
            'model_version':m['model_version'],'domains':domains,'drivers':drivers,
            'features':detail,
            'feature_rows':len(feat),'historical_pit_verified':False,
            'current_prediction_eligible':False,'forecast':None}


def anomalies_for_api(root,asof=None):
    folder,m,day,feat,audit=_recent_audit(root,asof)
    rows=pd.read_csv(folder/'anomalies.csv')
    if len(rows):rows=rows.loc[pd.to_datetime(rows.date).le(day)].tail(60)
    items=[]
    for v in rows.to_dict(orient='records'):
        items.append({k:(None if pd.isna(x) else x) for k,x in v.items()})
    return {'status':'OBSERVATION_ONLY','asof_session':str(day.date()),'anomalies':items}


def validation_for_api(root):
    folder,m=_latest(root)
    metrics=pd.read_csv(folder/'oos_metrics.csv')
    rows=[]
    for v in metrics.to_dict(orient='records'):
        rows.append({k:(None if isinstance(x,float) and not np.isfinite(x) else x) for k,x in v.items()})
    return {'status':'RETROSPECTIVE_RESEARCH_ONLY','model_version':m['model_version'],
            'dataset_pit_attested':False,'model_admitted':False,'metrics':rows}


def replay_for_api(root,asof,horizon):
    if int(horizon) not in HORIZONS:raise L1Blocked('L1_INVALID_HORIZON')
    folder,m,day,feat,audit=_recent_audit(root,asof)
    rows=pd.read_csv(folder/'oos_predictions.csv')
    if rows.empty:return {'status':'NO_OOS_PREDICTION','asof_session':str(day.date()),'horizon':int(horizon),'prediction':None}
    f=rows.loc[pd.to_datetime(rows.date).eq(day)&rows.horizon.eq(int(horizon))]
    if len(f)!=1:return {'status':'NO_OOS_PREDICTION','asof_session':str(day.date()),'horizon':int(horizon),'prediction':None}
    v=f.iloc[0]
    required=('e03_expected_return','target_return','e01_rv_model','target_forward_rv')
    if any(not np.isfinite(pd.to_numeric(v.get(key),errors='coerce')) for key in required):
        return {'status':'INSUFFICIENT_OUTCOME_DATA','asof_session':str(day.date()),
                'horizon':int(horizon),'prediction':None}
    return {'status':'RETROSPECTIVE_RESEARCH_ONLY','asof_session':str(day.date()),'horizon':int(horizon),
            'prediction':{'expected_return':float(v.e03_expected_return),
                          'actual_return':float(v.target_return),
                          'forecast_rv':float(v.e01_rv_model),'actual_rv':float(v.target_forward_rv),
                          'target_first_touch':str(v.target_first_touch),
                          'research_only':True}}


def market_overview_for_api(root,horizon,asof=None):
    if int(horizon) not in HORIZONS:raise L1Blocked('L1_INVALID_HORIZON')
    observation=observations_for_api(root,asof)
    observation['forecast']=None
    observation['horizon']=int(horizon)
    if observation['status']=='CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION':
        return observation
    from quant_research.workflow.l1_forward import latest_forward_for_api
    sealed=latest_forward_for_api(root,observation['asof_session'],int(horizon))
    if sealed is not None:
        observation.update(sealed)
        observation['domains']=observations_for_api(root,asof)['domains']
        observation['drivers']=observations_for_api(root,asof)['drivers']
        observation['features']=observations_for_api(root,asof)['features']
    return observation


def main(argv=None):
    p=argparse.ArgumentParser(description='L1 12-domain research, OOS and replay artifacts')
    p.add_argument('--bars',required=True,type=Path);p.add_argument('--cutoffs',required=True,type=Path)
    p.add_argument('--universe',type=Path);p.add_argument('--optional',type=Path)
    p.add_argument('--raw-measurements',type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--evaluation-start')
    p.add_argument('--minimum-training-sessions',type=int,default=252)
    p.add_argument('--calibration-sessions',type=int,default=84)
    p.add_argument('--refit-every',type=int,default=1,
                   help='Evaluate every Nth session; default 1 evaluates each eligible session')
    args=p.parse_args(argv)
    protocol=L1Protocol(min_train_sessions=args.minimum_training_sessions,
        calibration_sessions=args.calibration_sessions,refit_every=args.refit_every)
    result=build_l1_research(bars=args.bars,cutoffs=args.cutoffs,universe=args.universe,
        optional=args.optional,raw_measurements=args.raw_measurements,output=args.output,protocol=protocol,
        evaluation_start=args.evaluation_start)
    print(_json({'status':result['status'],'observed_rows':result['observed_rows'],
        'oos_rows':result['oos_rows'],'predictive_evidence_admitted':False}))

if __name__=='__main__':main()
