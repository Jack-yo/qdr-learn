"""Immutable L1 forward research prediction archive, not broker execution.

The source adapter must supply actually available PIT inputs. This boundary
checks real clock time, source hash, outcome absence and model evidence. It
never upgrades self-declared vendor PIT to independent verification.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import pandas as pd
from quant_research.research.l1_models import forecast_l1_research,L1Protocol,HORIZONS

_SHA=re.compile('[0-9a-f]{64}\\Z')


def _canonical(x):return json.dumps(x,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':'))


def freeze_l1_research(*,bars,observations,cutoffs,output_root,
                       source_snapshot_sha256,asof,now_utc=None,
                       protocol:L1Protocol=L1Protocol(),clock=None):
    """Freeze T after its decision cutoff but before T+1 entry.

    `now_utc` injection is for isolated deterministic tests; user-facing CLI
    must use wall clock. The time condition cannot certify provider PIT itself.
    """
    if not isinstance(source_snapshot_sha256,str) or not _SHA.fullmatch(source_snapshot_sha256):
        raise ValueError('Verified-format source SHA256 required')
    if clock is None:
        from quant_research.clock import TradingClock
        clock=TradingClock()
    day=pd.Timestamp(asof).date().isoformat()
    signal=pd.Timestamp(clock.signal(day)).tz_convert('UTC')
    first_entry=pd.Timestamp(clock.window(day,1).entry_time).tz_convert('UTC')
    now=pd.Timestamp(now_utc or datetime.now(timezone.utc)).tz_convert('UTC')
    if not signal<=now<first_entry:raise ValueError('OUTSIDE_REAL_FORWARD_FREEZE_WINDOW')
    current_cutoff=cutoffs.loc[pd.to_datetime(cutoffs.date).eq(pd.Timestamp(day)), 'decision_cutoff_utc']
    if len(current_cutoff)!=1 or pd.isna(current_cutoff.iloc[0]):
        raise ValueError('Missing asof decision cutoff')
    cutoff=pd.Timestamp(current_cutoff.iloc[0])
    if cutoff.tzinfo is None:
        raise ValueError('ASOF_CUTOFF_NAIVE')
    cutoff=cutoff.tz_convert('UTC')
    if not signal<=cutoff<=now or cutoff>=first_entry:
        raise ValueError('ASOF_CUTOFF_OUTSIDE_FREEZE_WINDOW')
    observed=observations.loc[pd.to_datetime(observations.date).eq(pd.Timestamp(day))]
    if len(observed)!=1 or bool(observed.iloc[0].get('forecast_eligible')) is not False:
        raise ValueError('Unqualified or missing observation status')
    if pd.to_datetime(bars.date).max()!=pd.Timestamp(day):
        raise ValueError('Future or older-date bars cannot be used for a forward freeze')
    raw=bars.loc[pd.to_datetime(bars.date).eq(pd.Timestamp(day))]
    if raw.empty or (pd.to_datetime(raw.available_at,utc=True)>cutoff).any():
        raise ValueError('Late/absent asof bars')
    inference=forecast_l1_research(bars,observations,cutoffs,protocol,asof=day)
    if inference['asof_session']!=day:raise ValueError('Inference is not as-of T')
    rows=[]
    for entry in inference['horizons']:
        if entry['status']!='RETROSPECTIVE_RESEARCH_ONLY' or not entry['forecast']:
            raise ValueError('INCOMPLETE_L1_MODEL_FOR_FREEZE')
        h=entry['horizon']; f=entry['forecast']
        quant=f['e03_quantiles']; prob=f['e02_probs']
        if not all(pd.notna(q) for q in quant) or list(quant)!=sorted(quant):
            raise ValueError('Invalid prediction distribution')
        rows.append({'horizon':h,'expected_return':f['e03_expected_return'],
             'p_up':f['e03_p_up_unverified'],'p_downside':f['e03_p_downside_unverified'],
             'quantiles':quant,'predicted_annualized_rv':f['e01_rv_model'],
             'probability_calibration_status':'NOT_CALIBRATED_RESEARCH_ONLY',
             'downside_threshold':-protocol.lower_barrier,
             'first_passage':None if prob is None else {
                'up_first':prob['UP'],'down_first':prob['DOWN'],'neither':prob['NEITHER'],
                'up_threshold':protocol.upper_barrier,'down_threshold':-protocol.lower_barrier},
             'first_passage_calibration_status':f['e02_status'],
             'train_last_date':entry['train_last_date'],'train_sessions':entry['train_sessions']})
    payload={'schema':'qdr.l1.market.v1','status':'FROZEN_FORWARD_RESEARCH_ONLY',
        'asof_session':day,'knowledge_cutoff_utc':cutoff.isoformat(),
        'entry_at_utc':first_entry.isoformat(),'frozen_at_utc':now.isoformat(),
        'source_snapshot_sha256':source_snapshot_sha256,
        'model_version':inference['model_version'],
        'research_only':True,'source_independently_attested':False,
        'historical_pit_verified':False,'model_admitted':False,
        'real_orders_enabled':False,'forecasts':rows}
    digest=sha256(_canonical(payload).encode()).hexdigest()
    folder=Path(output_root)/'outputs/l1_frozen'/day/digest[:16]
    if folder.exists():
        loaded=read_l1_frozen(output_root,day,digest[:16])
        if loaded!=payload:raise FileExistsError('Existing forecast hash collision')
        return payload
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'forecast.json').write_text(_canonical(payload),encoding='utf8')
    manifest={'kind':'L1_FROZEN_FORWARD_RESEARCH_V1','asof_session':day,
              'forecast_sha256':sha256((folder/'forecast.json').read_bytes()).hexdigest(),
              'identity':digest[:16],'real_orders_enabled':False,'model_admitted':False}
    (folder/'manifest.json').write_text(_canonical(manifest),encoding='utf8')
    return payload


def read_l1_frozen(root,asof,identity):
    if not re.fullmatch(r'[0-9a-f]{16}',str(identity)):raise ValueError('Invalid archive ID')
    folder=Path(root)/'outputs/l1_frozen'/str(asof)/identity
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    data_bytes=(folder/'forecast.json').read_bytes()
    if (manifest.get('kind')!='L1_FROZEN_FORWARD_RESEARCH_V1' or
        manifest.get('identity')!=identity or manifest.get('asof_session')!=str(asof) or
        manifest.get('model_admitted') is not False or manifest.get('real_orders_enabled') is not False or
        manifest.get('forecast_sha256')!=sha256(data_bytes).hexdigest()):
        raise ValueError('FROZEN_RESEARCH_ARCHIVE_INVALID')
    payload=json.loads(data_bytes)
    if sha256(_canonical(payload).encode()).hexdigest()[:16]!=identity:
        raise ValueError('FROZEN_RESEARCH_IDENTITY_MISMATCH')
    if payload.get('status')!='FROZEN_FORWARD_RESEARCH_ONLY' or payload.get('asof_session')!=str(asof) or payload.get('model_admitted') is not False:
        raise ValueError('INVALID_FORECAST_SCOPE')
    for row in payload.get('forecasts',[]):
        q=row.get('quantiles',[])
        if len(q)!=5 or q!=sorted(q):raise ValueError('INVALID_FORECAST_QUANTILES')
        p=row.get('first_passage')
        if p is not None and (any(not 0<=p[key]<=1 for key in ('up_first','down_first','neither')) or abs(p['up_first']+p['down_first']+p['neither']-1)>1e-6):
            raise ValueError('INVALID_FIRST_PASSAGE_PROBABILITIES')
    return payload


def latest_forward_for_api(root,asof,horizon):
    folder=Path(root)/'outputs/l1_frozen'/str(asof)
    if not folder.is_dir():return None
    archives=[read_l1_frozen(root,asof,p.name) for p in folder.iterdir() if p.is_dir()]
    for payload in sorted(archives,key=lambda item:pd.Timestamp(item['frozen_at_utc']),reverse=True):
        for h in payload['forecasts']:
            if h['horizon']==horizon:
                return {**{k:v for k,v in payload.items() if k!='forecasts'},'forecast':h}
    return None


def main(argv=None):
    """Production clocked research-only freeze. No historical replay flag."""
    import argparse
    from quant_research.workflow.l1_runtime import _read
    from quant_research.research.l1_observatory import compute_l1_observations
    from quant_research.research.l1_features import add_l1_features
    from quant_research.research.l1_derived_sources import raw_packets_to_optional
    p=argparse.ArgumentParser(description='Freeze L1 forward research at actual T cutoff; never broker orders')
    p.add_argument('--bars',type=Path,required=True)
    p.add_argument('--cutoffs',type=Path,required=True)
    p.add_argument('--universe',type=Path)
    p.add_argument('--optional',type=Path)
    p.add_argument('--raw-measurements',type=Path)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--asof',required=True)
    p.add_argument('--source-snapshot-sha256',required=True)
    a=p.parse_args(argv)
    bars=_read(a.bars);cutoffs=_read(a.cutoffs)
    universe=_read(a.universe) if a.universe else None
    obs,_=compute_l1_observations(bars,cutoffs,universe)
    optional=_read(a.optional) if a.optional else None
    if a.raw_measurements:
        derived=raw_packets_to_optional(_read(a.raw_measurements),cutoffs,obs)
        optional=derived if optional is None else pd.concat([optional,derived],ignore_index=True)
    features,_=add_l1_features(obs,bars,cutoffs,optional,universe=universe)
    from quant_research.clock import TradingClock
    result=freeze_l1_research(bars=bars,observations=features,cutoffs=cutoffs,
        output_root=a.root,source_snapshot_sha256=a.source_snapshot_sha256,
        asof=a.asof,clock=TradingClock())
    print(_canonical({'status':result['status'],'asof_session':result['asof_session'],
                      'model_version':result['model_version'],'trade_eligible':False}))

if __name__=='__main__':main()
