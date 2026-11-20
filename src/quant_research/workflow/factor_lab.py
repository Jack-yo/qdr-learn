"""Real current-vintage factor experiments; no market-store writes or execution."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.features.context import make_context
from quant_research.features.engine import compute_features
from quant_research.policy import PolicyError
from quant_research.reports.factors import render_report
from quant_research.research.evaluate import evaluate
from quant_research.research.experiment import Experiment,load_experiment
from quant_research.research.factor_lab import Registry,FactorSpec,template_factor,fingerprint,valid_id
from quant_research.research.labels import make_labels


def inputs(root,source,cutoff=None,symbols=None):
    if source not in ('yahoo','alpaca'):raise ValueError('Explicit reviewed price source required')
    if (root/'data/catalog/.maintenance.lock').is_file():raise PolicyError('DATA_MAINTENANCE_RUNNING','Data maintenance is running')
    database=root/('data/research.duckdb' if source=='yahoo' else 'data/real_v21.duckdb')
    bundle=load_real_bundle(database,source,'2024-12-31',cutoff,start='2017-01-01',symbols=symbols,raw_root=root/'data/raw')
    bundle.require('exploratory_price_factors')
    bundle.require('observation')
    return bundle


def preview(root,version_id,source,data_root=None,symbols=None):
    registry=Registry(root);version=registry.factor(version_id);spec=FactorSpec.model_validate(version['config'])
    bundle=inputs(Path(data_root or root),source,symbols=symbols);clock=TradingClock()
    context=make_context(bundle.prices,clock,'SPY','2017-01-01','2024-12-31')
    factor=template_factor(spec,version['config_sha256'])
    features=compute_features(context,clock,[factor],'retrospective',['SPY','HYG','LQD'])
    sample=features.sort_values(['date','security_id']).tail(10).copy()
    sample['symbol']=sample.security_id.map(context.symbols)
    sample['close']=[context.close.loc[d,s] for d,s in zip(sample.date,sample.security_id)]
    shifted=context.close.shift(spec.window)
    sample['reference_close']=[shifted.loc[d,s] for d,s in zip(sample.date,sample.security_id)]
    sample['value_before_direction']=sample.value/spec.direction
    return {'status':'RETROSPECTIVE_PREVIEW_ONLY','factor_version':version,'source':bundle.metadata['source'],
            'source_provenance':bundle.metadata['source_provenance'],'data_snapshot_sha256':bundle.metadata['snapshot_sha256'],
            'asof_date_et':'2024-12-31','data_cutoff_utc':bundle.metadata['knowledge_cutoff_utc'],
            'adjustment_basis':bundle.prices.adjustment_basis.iloc[0],'formula':factor.definition,
            'rows':json.loads(sample.to_json(orient='records',date_format='iso')),
            'research_grade':False,'execution_ready':False,'historical_decision_eligible':False,
            'data_quality_flags':[
                'CURRENT_VINTAGE_NOT_HISTORICAL_PIT',
                ('EXPLICIT_CURRENT_ETF_LIST' if set(bundle.metadata['symbols'])==set(SYMBOLS)
                 else 'EXPLICIT_CUSTOM_SECURITY_LIST'),
                'NOT_EXECUTION_LABELS'
            ]}


def run(root,experiment_id,data_root=None):
    root=Path(root).resolve();registry=Registry(root);experiment=registry.experiment(experiment_id)
    if experiment['status']!='CREATED':return experiment
    if not registry.claim(experiment_id):raise PolicyError('EXPERIMENT_ALREADY_CLAIMED','Experiment is already running or finalized')
    config=experiment['config'];output=root/'outputs/factor_lab'/valid_id(experiment_id)
    manifest={'run_id':experiment_id,'experiment_id':experiment_id,'source':config['source'].upper(),
        'created_at_utc':experiment['created_at_utc'],'data_cutoff_utc':config['knowledge_cutoff_utc'],
        'asof_date_et':'2024-12-31','mode':'retrospective','status':'RUNNING','config_sha256':experiment['config_sha256'],
        'model_version':None,'research_grade':False,'execution_ready':False,'real_orders_enabled':False,
        'historical_decision_eligible':False,'sealed_test_used':False,'performance':None}
    try:
        output.mkdir(parents=True,exist_ok=False)
        (output/'config.json').write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
        if config['protocol']!='factor-lab-descriptive-v1' or config['mode']!='retrospective' or config['validation_end']!='2024-12-31':
            raise PolicyError('EXPERIMENT_PROTOCOL_REJECTED','Experiment must preserve the frozen development protocol')
        protocol=Experiment.model_validate(config['research_protocol'])
        # The embedded protocol is authoritative; no reload of a mutable current config.
        version=registry.factor(config['factor_version_id'])
        if version['config_sha256']!=config['factor_config_sha256']:raise PolicyError('FACTOR_VERSION_CHANGED','Frozen factor definition mismatch')
        spec=FactorSpec.model_validate(version['config']);factor=template_factor(spec,version['config_sha256'])
        bundle=inputs(Path(data_root or root),config['source'],datetime.fromisoformat(config['knowledge_cutoff_utc']),config.get('symbols'))
        context=make_context(bundle.prices,TradingClock(),protocol.benchmark,'2017-01-01','2024-12-31')
        features=compute_features(context,TradingClock(),[factor],'retrospective',protocol.exclude_symbols)
        if not features.value.notna().any():raise PolicyError('NO_FACTOR_VALUES','No valid factor values in the verified sample')
        basis=bundle.prices.adjustment_basis.iloc[0]
        labels=make_labels(context,TradingClock(),protocol.horizons,basis,protocol.exclude_symbols)
        results=evaluate(features,labels,context,protocol)
        features.to_parquet(output/'features.parquet',index=False);labels.to_parquet(output/'labels.parquet',index=False)
        for name,frame in results.items():
            frame.to_parquet(output/(name+'.parquet'),index=False)
            if name not in ('daily_ic','daily_groups'):frame.to_csv(output/(name+'.csv'),index=False)
        package=Path(__file__).resolve().parents[1]
        symbols=list(bundle.metadata['symbols'])
        default_proxy=set(symbols)==set(SYMBOLS)
        universe_version=('EXPLICIT_CURRENT_ETF_LIST_NOT_PIT' if default_proxy
                          else 'EXPLICIT_CUSTOM_SECURITY_LIST_NOT_HISTORICAL_PIT')
        scope_flag=('ETF_PROXY_NOT_EQUITY_ALPHA' if default_proxy
                    else 'CUSTOM_SECURITY_LIST_NOT_HISTORICAL_PIT')
        manifest.update(status='RETROSPECTIVE_EXPLORATORY_ONLY',source_provenance=bundle.metadata['source_provenance'],
            data_sha256=bundle.metadata['snapshot_sha256'],input_rows=bundle.metadata['rows'],
            factor_version=version,formula=factor.definition,experiment=protocol.model_dump(mode='json'),
            feature_rows=len(features),feature_nonnull=int(features.value.notna().sum()),
            decision_eligible_features=int(features.decision_eligible.sum()),label_rows=len(labels),
            formal_raw_label_count=int(labels.forward_return.notna().sum()),proxy_label_count=int(labels.proxy_forward_return.notna().sum()),
            adjustment_basis=basis,flags=['EXPLORATORY',scope_flag,'CURRENT_VINTAGE_NOT_HISTORICAL_PIT','NOT_RAW_EXECUTION_PRICE'],
            universe_version=universe_version,symbols=symbols,
            code_sha256=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest())
        manifest['data_quality_flags']=manifest['flags'].copy()
        results['summary']['exposure_status']='PIT_SECTOR_SIZE_UNAVAILABLE_STYLE_LINK_NOT_EVALUATED'
        # Re-export the corrected scope statement; no unimplemented exposure values are invented.
        results['summary'].to_parquet(output/'summary.parquet',index=False);results['summary'].to_csv(output/'summary.csv',index=False)
        render_report(output,manifest,results)
        payload={**manifest,'summary':json.loads(results['summary'].to_json(orient='records'))}
        (output/'result.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        manifest['artifacts_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
        (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        registry.finish(experiment_id,'COMPLETED',output.relative_to(root).as_posix())
    except Exception as exc:
        error=exc.payload() if isinstance(exc,PolicyError) else {'status':'FAILED','code':type(exc).__name__,'message':'Experiment failed; no substitute results generated'}
        manifest.update(status='BLOCKED' if isinstance(exc,PolicyError) else 'FAILED',error=error)
        if output.is_dir() and not (output/'manifest.json').exists():
            (output/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
        registry.finish(experiment_id,manifest['status'],output.relative_to(root).as_posix(),error)
    return registry.experiment(experiment_id)


def result(root,experiment_id):
    root=Path(root).resolve();item=Registry(root).experiment(experiment_id)
    if item['status']!='COMPLETED':return {'experiment':item,'status':item['status'],'error':item['error']}
    folder=root/'outputs/factor_lab'/valid_id(experiment_id)
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if not {'result.json', 'report.html'} <= set(manifest.get('artifacts_sha256', {})):
        raise PolicyError('EXPERIMENT_ARTIFACT_CORRUPT','Experiment manifest is missing required artifact hashes')
    for name,digest in manifest['artifacts_sha256'].items():
        path=(folder/name).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise PolicyError('EXPERIMENT_ARTIFACT_CORRUPT','Experiment artifact SHA256 mismatch')
    rolling=[]
    if 'daily_ic.parquet' in manifest['artifacts_sha256']:
        daily=pd.read_parquet(folder/'daily_ic.parquet')
        required={'date','partition','horizon','rank_ic'}
        if not required.issubset(daily.columns):
            raise PolicyError('EXPERIMENT_ARTIFACT_CORRUPT','Daily IC artifact is missing required columns')
        daily=daily.loc[daily.partition.eq('validation') & daily.horizon.eq(3),['date','rank_ic']].copy()
        daily['date']=pd.to_datetime(daily['date'],errors='raise')
        if daily['date'].duplicated().any():
            raise PolicyError('EXPERIMENT_ARTIFACT_CORRUPT','Daily IC contains duplicate validation dates')
        daily=daily.sort_values('date')
        daily['rolling_ic_20']=daily['rank_ic'].rolling(20,min_periods=20).mean()
        rolling=json.loads(daily.to_json(orient='records',date_format='iso',double_precision=15))
    return {'experiment':item,'status':'COMPLETED','result':json.loads((folder/'result.json').read_text(encoding='utf-8')),
            'rolling_ic_h3':rolling,'report_path':(folder/'report.html').relative_to(root).as_posix()}


def compare(root,left,right):
    a,b=result(root,left),result(root,right)
    if a['status']!='COMPLETED' or b['status']!='COMPLETED':raise PolicyError('COMPARISON_NOT_READY','Both experiments must have verified completed artifacts')
    x,y=a['result'],b['result']
    if any(x[k]!=y[k] for k in ('source','data_sha256','adjustment_basis','experiment')):
        raise PolicyError('INCOMPARABLE_EXPERIMENTS','Comparison requires identical source snapshot and evaluation protocol')
    columns=['partition','horizon','rank_ic_mean','label_pair_coverage','daily_ic_count']
    frame=pd.DataFrame(x['summary'])[columns].merge(pd.DataFrame(y['summary'])[columns],on=['partition','horizon'],suffixes=('_left','_right'),validate='one_to_one')
    frame['delta_rank_ic']=frame.rank_ic_mean_right-frame.rank_ic_mean_left
    return {'status':'DESCRIPTIVE_COMPARISON_ONLY','left':left,'right':right,'source':x['source'],
            'data_sha256':x['data_sha256'],'rows':json.loads(frame.to_json(orient='records')),
            'research_grade':False,'execution_ready':False,'multiple_testing_adjusted':False}
