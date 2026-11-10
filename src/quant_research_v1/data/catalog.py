"""Categorized operational inventory. Legacy data never becomes a formal input by discovery."""
from datetime import datetime, timezone
import csv
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .http import atomic_write
from .store import duckdb
from quant_research.policy import PolicyError


DATASETS = {
    'market_prices': ('行情原价','data/real_v21.duckdb','prices_daily','ALPACA SIP raw','daily','OBSERVATION_ONLY'),
    'yahoo_research_prices': ('Yahoo探索研究价格','data/research.duckdb','prices_daily','YAHOO split-adjusted','on_demand','EXPLORATORY_ONLY_NOT_RAW_NOT_PIT'),
    'corporate_actions': ('公司行为','data/managed/corporate_actions/events.duckdb','corporate_event_versions','ALPACA','daily','EVENT_EVIDENCE_NOT_ACCEPTED_LEDGER'),
    'sec_filings': ('SEC申报索引','data/g3_evidence.duckdb','filing_index_versions','SEC','weekly','INDEX_EVIDENCE_ONLY'),
    'sec_candidates': ('SEC财务候选','data/g3_evidence.duckdb','financial_candidates','SEC','weekly','NOT_HISTORICAL_PIT'),
    'classic_factors': ('经典因子','data/managed/classic_factors/factors.duckdb','factor_returns','KEN_FRENCH','weekly','ATTRIBUTION_ONLY'),
}
MISSING = {
    'historical_securities': ('历史证券与股票池','历史成分、永久标识、退市证券及结算尚未核验','取得可追溯历史证券主档后单独验收'),
    'pit_fundamentals': ('PIT财务与行业','候选财务不具备完整历史公告/原稿/行业证据','核验原申报值、接受时点与身份映射'),
    'eligible_models': ('模型与预测','当前SIP模型输入资格尚未开放','数据能力验收后重跑并冻结样本外模型'),
    'paper_ledger': ('前向模拟账本','尚无合格模型、事件账本及冻结决策快照','满足前向准入后从真实开始日逐日登记'),
}


def cache_inventory(root):
    rows=[]
    for folder in (root/'data/raw/receipts',root/'data/raw/yahoo/receipts'):
        for path in sorted(folder.glob('*.json')):
            try:
                d=json.loads(path.read_text(encoding='utf-8'));digest=d.get('sha256','')
                url=d.get('url','');request=d.get('request',{})
                category = ('market_prices' if '/stocks/bars' in url else 'corporate_actions' if '/corporate-actions' in url
                    else 'sec' if 'sec.gov' in url else 'classic_factors' if 'dartmouth.edu' in url
                    else 'yahoo_exploratory' if request.get('provider')=='yfinance' else 'issuer_documents')
                valid=len(digest)==64 and all(c in '0123456789abcdef' for c in digest)
                body=root/'data/raw/objects'/digest if valid else None
                verified=bool(body and body.is_file() and hashlib.sha256(body.read_bytes()).hexdigest()==digest)
                rows.append({'category':category,'source_url':url or request.get('provider'), 'raw_sha256':digest,
                    'retrieved_at_utc':d.get('fetched_at'),'hash_verified':verified,
                    'receipt_path':path.relative_to(root).as_posix(), 'object_path':body.relative_to(root).as_posix() if body else None})
            except (ValueError,OSError):
                rows.append({'category':'UNCLASSIFIED','receipt_path':path.relative_to(root).as_posix(),'hash_verified':False})
    return rows


def inspect_database(root,key,spec):
    name,relative,table,source,cadence,use=spec
    result={'dataset_id':key,'name':name,'path':relative,'table':table,'source':source,'cadence':cadence,
            'use_policy':use,'status':'BLOCKED','rows':None,'latest_rows':None,'first_date':None,'last_date':None,
            'missing_reason':None,'real_orders_enabled':False}
    path=root/relative
    if not path.is_file():
        result['missing_reason']='DATASET_NOT_COLLECTED';return result
    try:
        with duckdb.connect(str(path),read_only=True) as db:
            db.execute("SET TimeZone='UTC'")
            present={r[0] for r in db.execute('SHOW TABLES').fetchall()}
            if table not in present:
                result['missing_reason']='EXPECTED_TABLE_MISSING';return result
            result['rows']=db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            if not result['rows']:
                result['missing_reason']='EMPTY_DATASET';return result
            if key=='market_prices':
                sources=db.execute('SELECT DISTINCT source,feed,adjustment_basis FROM prices_daily').fetchall()
                if sources!=[('ALPACA','sip','raw')]:
                    result['missing_reason']='UNEXPECTED_SOURCE_IN_PRIMARY_STORE';return result
                row=db.execute('SELECT count(DISTINCT (symbol,date)),min(date),max(date),count(DISTINCT symbol) FROM prices_daily').fetchone()
                result.update(latest_rows=row[0],first_date=str(row[1]) if row[1] else None,last_date=str(row[2]) if row[2] else None,symbols=row[3])
            elif key=='yahoo_research_prices':
                row=db.execute("""SELECT count(*),count(DISTINCT (symbol,date)),min(date),max(date),count(DISTINCT symbol)
                    FROM prices_daily WHERE source='YAHOO' AND feed='yahoo' AND adjustment_basis='yahoo_split_adjusted'
                    AND date>='2017-01-01' AND date<='2024-12-31'""").fetchone()
                result.update(rows=row[0],latest_rows=row[1],first_date=str(row[2]) if row[2] else None,
                              last_date=str(row[3]) if row[3] else None,symbols=row[4],
                              scope='SOURCE_FILTERED_EXPLORATORY_WINDOW_2017_2024_NOT_WHOLE_DATABASE')
                result['market_research_outputs'] = 'outputs/market_research'
                result['alpha_research_outputs'] = 'outputs/alpha_research'
            elif key=='corporate_actions':
                row=db.execute('SELECT count(DISTINCT event_id),min(observed_at),max(observed_at) FROM corporate_event_versions').fetchone()
                result.update(latest_rows=row[0],first_observed_utc=str(row[1]),last_observed_utc=str(row[2]))
            elif key=='classic_factors':
                result['derived_outputs']='outputs/styles'
                result['latest_observation_pointer']='data/managed/classic_factors/monitor_latest_observation.json'
                if db.execute("SELECT count(*) FROM factor_returns WHERE source<>'KEN_FRENCH' OR use_policy<>'ATTRIBUTION_ONLY'").fetchone()[0]:
                    result['missing_reason']='UNEXPECTED_FACTOR_SOURCE_OR_POLICY';return result
                row=db.execute('SELECT count(DISTINCT (date,factor_name)),min(date),max(date) FROM factor_returns').fetchone()
                result.update(latest_rows=row[0],first_date=str(row[1]) if row[1] else None,last_date=str(row[2]) if row[2] else None)
            elif key=='sec_candidates':
                result['eligible_rows']=db.execute('SELECT count(*) FROM financial_candidates WHERE decision_eligible').fetchone()[0]
                if result['eligible_rows']:
                    result['missing_reason']='UNACCEPTED_PIT_PROMOTION';return result
            result['status']='COLLECTED_RESTRICTED_USE' if result['rows'] else 'BLOCKED'
            if not result['rows']:result['missing_reason']='EMPTY_DATASET'
    except Exception as exc:
        result['missing_reason']='READ_FAILED_'+type(exc).__name__
    return result


def build_catalog(root):
    root=Path(root).resolve()
    datasets=[inspect_database(root,key,spec) for key,spec in DATASETS.items()]
    datasets.extend({'dataset_id':key,'name':name,'status':'BLOCKED','rows':None,'missing_reason':reason,
                     'repair':repair,'path':None,'cadence':'EVIDENCE_DEPENDENT','use_policy':'UNAVAILABLE'}
                    for key,(name,reason,repair) in MISSING.items())
    registry=root/'data/managed/factor_lab/registry.sqlite3'
    lab={'dataset_id':'factor_lab','name':'因子定义与独立研究实验','path':'data/managed/factor_lab/registry.sqlite3',
         'source':'REAL_SOURCE_RECORDED_PER_EXPERIMENT','cadence':'on_demand','use_policy':'RETROSPECTIVE_EXPLORATORY_ONLY',
         'status':'NOT_CREATED','rows':None,'missing_reason':'CREATE_FACTOR_VERSION_FIRST','derived_outputs':'outputs/factor_lab'}
    if registry.is_file():
        db=sqlite3.connect(registry.as_uri()+'?mode=ro',uri=True)
        try:
            versions=db.execute('SELECT count(*) FROM factor_versions').fetchone()[0]
            counts=dict(db.execute('SELECT status,count(*) FROM experiments GROUP BY status').fetchall())
            lab.update(status='RESEARCH_REGISTRY_AVAILABLE',rows=sum(counts.values()),factor_versions=versions,
                       experiment_status_counts=counts,missing_reason=None)
        except sqlite3.Error:lab.update(status='BLOCKED',missing_reason='RESEARCH_REGISTRY_READ_FAILED')
        finally:db.close()
    datasets.append(lab)
    from .close_snapshot import STORE as snapshot_store, read_snapshot
    captures = root / snapshot_store
    snapshot_entry = {
        'dataset_id': 'close_snapshots', 'name': '开盘前冻结行情观察',
        'path': snapshot_store.as_posix(), 'source': 'ALPACA SIP raw',
        'cadence': 'on_demand', 'use_policy': 'OBSERVATION_ONLY',
        'status': 'NOT_CREATED', 'rows': None, 'missing_reason': 'NO_CLOSE_SNAPSHOT',
    }
    if captures.is_file():
        try:
            latest = read_snapshot(root)
            with closing(sqlite3.connect(captures.as_uri() + '?mode=ro', uri=True)) as database:
                count = database.execute('SELECT count(*) FROM snapshots').fetchone()[0]
            snapshot_entry.update(status='OBSERVATION_FROZEN', rows=count,
                                  last_date=latest['session_date_et'],
                                  latest_capture_sha256=latest['capture_sha256'], missing_reason=None)
        except (PolicyError, sqlite3.Error, ValueError, KeyError, OSError) as exc:
            snapshot_entry.update(status='BLOCKED', missing_reason=getattr(exc, 'code', type(exc).__name__))
    datasets.append(snapshot_entry)
    from quant_research.research.strategy import STORE as strategy_store, StrategyRegistry
    strategies = {
        'dataset_id': 'strategies', 'name': '策略草稿与冻结版本',
        'path': strategy_store.as_posix(), 'source': 'VERIFIED_FACTOR_DEPENDENCIES',
        'cadence': 'on_demand', 'use_policy': 'CONFIGURATION_AND_PREFLIGHT_ONLY',
        'status': 'NOT_CREATED', 'rows': None, 'missing_reason': 'NO_STRATEGY_VERSION',
        'derived_outputs': 'outputs/strategy_preflight',
    }
    try:
        versions = StrategyRegistry(root).versions()
        if versions:
            strategies.update(status='STRATEGY_VERSIONS_AVAILABLE', rows=len(versions), missing_reason=None,
                              frozen_versions=sum(item['status'] == 'FROZEN' for item in versions))
    except (PolicyError, sqlite3.Error, ValueError, OSError) as exc:
        strategies.update(status='BLOCKED', missing_reason=getattr(exc, 'code', type(exc).__name__))
    datasets.append(strategies)
    from quant_research.workflow.daily_observation import OUTPUT as observations_output, latest_report
    observations = {
        'dataset_id': 'daily_observations', 'name': '每日行情观察报告',
        'path': observations_output.as_posix(), 'source': 'ALPACA SIP raw',
        'cadence': 'on_demand', 'use_policy': 'OBSERVATION_ONLY',
        'status': 'NOT_CREATED', 'rows': None, 'missing_reason': 'DAILY_OBSERVATION_NOT_FOUND',
    }
    try:
        latest = latest_report(root)
        observations.update(status=latest['status'], last_date=latest['session_date_et'],
                            rows=sum(1 for _ in (root / observations_output).glob('*/manifest.json')),
                            latest_report=latest['artifacts']['report.html'],
                            latest_capture_sha256=latest['capture_sha256'], missing_reason=None)
    except PolicyError as exc:
        if exc.code != 'DAILY_OBSERVATION_NOT_FOUND':
            observations.update(status='BLOCKED', missing_reason=exc.code)
    except (ValueError, KeyError, OSError) as exc:
        observations.update(status='BLOCKED', missing_reason=type(exc).__name__)
    datasets.append(observations)
    active={str((root/spec[1]).resolve()) for spec in DATASETS.values()}
    excluded=[{'path':p.relative_to(root).as_posix(),'status':'LEGACY_OR_MIXED_STORE_NOT_FORMAL_INPUT'}
              for p in sorted((root/'data').glob('*.duckdb')) if str(p.resolve()) not in active]
    cache=cache_inventory(root)
    return {'created_at_utc':datetime.now(timezone.utc).isoformat(),'policy':'REAL_ONLY','datasets':datasets,
            'cache_receipts':len(cache),'cache_hash_failures':sum(not r['hash_verified'] for r in cache),
            'excluded_stores':excluded,'cache_index':cache,'historical_universe_available':False,
            'research_grade':False,'execution_ready':False,'real_orders_enabled':False}


def write_catalog(root,maintenance_owner=False):
    root=Path(root).resolve()
    if not maintenance_owner and (root/'data/catalog/.maintenance.lock').is_file():
        raise PolicyError('DATA_MAINTENANCE_RUNNING','Maintenance owns the catalog writer')
    data=build_catalog(root)
    base=root/'data/catalog';output=base/'snapshots'/str(uuid4());output.mkdir(parents=True)
    for name,rows in [('datasets',data['datasets']),('cache_index',data['cache_index']),('excluded_stores',data['excluded_stores'])]:
        columns=sorted({c for row in rows for c in row})
        with (output/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(rows)
    (output/'catalog.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    for dataset in data['datasets']:
        # Category landing files point to authoritative stores; no silent relocation or duplicate DB.
        atomic_write(root/'data/managed'/dataset['dataset_id']/'dataset.json',
                     json.dumps({**dataset,'catalog_snapshot':output.relative_to(root).as_posix()},indent=2,ensure_ascii=False).encode())
    pointer={'created_at_utc':data['created_at_utc'],'snapshot_dir':output.relative_to(root).as_posix(),
             'artifacts_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}}
    atomic_write(base/'latest.json',json.dumps(pointer,indent=2).encode())
    return output,data


def catalog_artifact(root,name='catalog.json'):
    root=Path(root).resolve();base=root/'data/catalog'
    if name not in {'catalog.json','datasets.csv','cache_index.csv','excluded_stores.csv'}:
        raise ValueError('Unknown catalog export')
    if (base/'.maintenance.lock').is_file():
        raise PolicyError('DATA_MAINTENANCE_RUNNING','Catalog is being maintained')
    if not (base/'latest.json').is_file():
        raise PolicyError('NO_DATA_CATALOG','Run data-catalog or maintain-data first')
    pointer=json.loads((base/'latest.json').read_text(encoding='utf-8'))
    folder=(root/pointer['snapshot_dir']).resolve()
    if not folder.is_relative_to((base/'snapshots').resolve()):
        raise PolicyError('CATALOG_PATH_REJECTED','Catalog snapshot must stay inside its directory')
    for filename in ('catalog.json','datasets.csv','cache_index.csv','excluded_stores.csv'):
        path=folder/filename
        if not path.resolve().is_relative_to(folder) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=pointer['artifacts_sha256'].get(filename):
            raise PolicyError('CATALOG_HASH_MISMATCH','Catalog artifacts failed SHA256 verification')
    return (folder/name).read_bytes()
