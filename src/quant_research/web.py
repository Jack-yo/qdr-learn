"""Loopback-only real-data console. No broker APIs or arbitrary command execution."""
import argparse
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import threading
import hashlib
from urllib.parse import unquote, urlsplit,parse_qs

from .data.store import duckdb
from .policy import SYMBOLS
from .policy import PolicyError
from .data.bundle import load_real_bundle


PRIVATE_OUTPUTS = {"pytest-tmp", "ops_backups", "ops_restore"}


def allowed_artifact(root, target):
    """Legacy/synthetic and unmanifested artifacts are never served by the product."""
    try:
        target = target.resolve()
        if not target.is_relative_to((root/'outputs').resolve()) or not target.is_file():
            return False
        if PRIVATE_OUTPUTS.intersection(target.relative_to((root/'outputs').resolve()).parts):
            return False
        for parent in (target.parent, *target.parents):
            if not parent.is_relative_to((root/'outputs').resolve()): break
            manifest = parent/'manifest.json'
            if manifest.is_file():
                data=json.loads(manifest.read_text(encoding='utf-8'))
                if str(data.get('source','')).upper() not in {'YAHOO','ALPACA','FRENCH','SEC'}: return False
                if any('SYNTH' in str(x).upper() for x in data.get('flags',[])): return False
                expected=data.get('artifacts_sha256',{}).get(target.relative_to(parent).as_posix())
                return bool(expected) and hashlib.sha256(target.read_bytes()).hexdigest()==expected
    except (ValueError,OSError,json.JSONDecodeError):
        pass
    return False


def market_research(root, horizon, asof=None):
    """Read the latest complete retrospective study from its verified artifacts."""
    import pandas as pd

    folder = root / 'outputs/market_research'
    manifests = sorted(folder.glob('*/manifest.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding='utf-8'))
        if manifest.get('workflow') != 'train-market' or manifest.get('status') != 'DESCRIPTIVE_CURRENT_VINTAGE_ONLY':
            continue
        if (manifest.get('source') != 'yahoo' or manifest.get('mode') != 'retrospective'
                or manifest.get('sealed_test_used') is not False
                or manifest.get('historical_decision_eligible') is not False
                or manifest.get('run_id') != path.parent.name
                or not date.fromisoformat(manifest['asof_date_et']) < date(2025, 1, 1)):
            raise PolicyError('MARKET_STUDY_SCOPE_REJECTED', 'Market study scope failed verification')
        required = ['market_summary.json', 'market_predictions.parquet', 'market_style_states.parquet',
                    'market_predictions.csv', 'training_folds.csv', 'report.html']
        if not all(allowed_artifact(root, path.parent / name) for name in required):
            raise PolicyError('MARKET_STUDY_ARTIFACT_CORRUPT', 'Market study artifact SHA256 mismatch')
        if asof and not manifest['experiment']['start'] <= asof <= manifest['asof_date_et']:
            raise PolicyError('DATE_OUTSIDE_MARKET_STUDY', 'Requested date is outside the completed study')
        summary = json.loads((path.parent / required[0]).read_text(encoding='utf-8'))
        predictions = pd.read_parquet(path.parent / required[1], filters=[('horizon', '==', horizon)])
        states = pd.read_parquet(path.parent / required[2])
        if asof:
            predictions = predictions.loc[predictions.date.eq(pd.Timestamp(asof))]
            states = states.loc[states.date.eq(pd.Timestamp(asof))]
        # The research UI needs the actual historical features, not inferred
        # values or simulated illustrations. Expose only vetted market and
        # tradeable-ETF style observation columns from the verified artifact.
        state_fields = ['date', 'market_state', 'state_available_at']
        state_fields += [field for field in (
            'market_return_1', 'market_return_5', 'market_return_20',
            'market_vol_5', 'market_vol_20', 'market_vol_ratio',
            'market_concentration_5', 'market_credit_5',
            'market_sector_dispersion', 'market_sector_mean_correlation',
            'market_breadth_etf_proxy',
            'style_small_relative_return_5d', 'style_small_relative_return_20d',
            'style_value_relative_return_5d', 'style_value_relative_return_20d',
            'style_momentum_relative_return_5d', 'style_momentum_relative_return_20d',
            'style_quality_relative_return_5d', 'style_quality_relative_return_20d',
            'style_low_vol_relative_return_5d', 'style_low_vol_relative_return_20d',
        ) if field in states]
        return {
            'status': manifest['status'], 'horizon': horizon, 'requested_date': asof,
            'manifest': {name: manifest[name] for name in (
                'run_id', 'source', 'asof_date_et', 'source_snapshot_sha256', 'source_provenance',
                'data_cutoff_utc', 'experiment', 'adjustment_basis', 'historical_decision_eligible',
                'market_model_usage', 'prediction_rows', 'sealed_test_used')},
            'predictions': json.loads(predictions.sort_values('date').tail(1).to_json(orient='records', date_format='iso')),
            'states': json.loads(states[state_fields].tail(1).to_json(orient='records', date_format='iso')),
            'state_history': json.loads(states[state_fields].tail(126).to_json(orient='records', date_format='iso')),
            'state_history_scope': 'RETROSPECTIVE_CURRENT_VINTAGE_NOT_PIT_NOT_FORWARD',
            'summary': {key: [row for row in rows if row['horizon'] == horizon] for key, rows in summary.items()},
            'artifacts': {name: (path.parent / name).relative_to(root).as_posix() for name in required[3:]},
        }
    raise PolicyError('NO_COMPLETED_MARKET_STUDY', 'Run the Yahoo retrospective market study first')


def feature_evidence(root, dataset):
    """Display matching, hashed audit evidence; this never changes bundle capabilities."""
    if dataset.get('source')!='ALPACA':
        return {'status':'BLOCKED','code':'FEATURE_EVIDENCE_SOURCE_UNSUPPORTED'}
    paths = sorted((root/'outputs/feature_prices').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('raw_snapshot_sha256')!=dataset['snapshot_sha256'] or data.get('anchor_date_et')!=dataset['asof_date_et']:
                continue
            if not data.get('generated_at_utc'):
                continue
            if datetime.fromisoformat(data['generated_at_utc'])>datetime.fromisoformat(dataset['knowledge_cutoff_utc']):
                continue
            required = {'comparison.json','precision.json','issuer_checks.json','feature_prices.parquet','vendor_split_reference.parquet'}
            if not required<=set(data.get('artifacts_sha256',{})):
                continue
            if not all(allowed_artifact(root,path.parent/name) for name in required):
                return {'status':'BLOCKED','code':'FEATURE_EVIDENCE_ARTIFACT_HASH_MISMATCH'}
            comparison=json.loads((path.parent/'comparison.json').read_text(encoding='utf-8'))
            precision=json.loads((path.parent/'precision.json').read_text(encoding='utf-8'))
            issuer=json.loads((path.parent/'issuer_checks.json').read_text(encoding='utf-8'))
            return {'status':data['status'],'run_id':data['run_id'],'generated_at_utc':data['generated_at_utc'],
                    'basis':data['adjustment_basis'],'strict_reference_status':comparison['status'],
                    'rows_compared':comparison['rows_compared'],'issuer_matched':issuer['matched_splits'],
                    'issuer_requested':issuer['requested_splits'],
                    'issuer_unverified_symbols':[c['symbol'] for c in issuer['checks'] if c['status']!='CASE_FIELDS_MATCH'],
                    'empirical_quantizer_mismatches':{k:v['binary64_floor_x100_plus_half_div100_mismatches'] for k,v in precision['checks'].items()},
                    'vendor_rounding_guaranteed':False,'execution_enabled':False,
                    'comparison_path':(path.parent/'comparison.json').relative_to(root).as_posix(),
                    'issuer_path':(path.parent/'issuer_checks.json').relative_to(root).as_posix()}
        except (KeyError,ValueError,OSError):
            return {'status':'BLOCKED','code':'FEATURE_EVIDENCE_INVALID'}
    return {'status':'BLOCKED','code':'NO_MATCHING_FEATURE_EVIDENCE','message':'No verified evidence matches this raw snapshot, anchor and cutoff'}


def snapshot(root,source='alpaca',database=None,asof=None,cutoff=None):
    if (root/'data/catalog/.maintenance.lock').is_file():
        return {'busy':True,'status':'DATA_MAINTENANCE_RUNNING','real_orders_enabled':False,'execution_enabled':False}
    database = database or root / ('data/real_v21.duckdb' if source=='alpaca' else 'data/research.duckdb')
    result = {"source": "YAHOO_REAL_CURRENT_VINTAGE", "real_orders_enabled": False,
              "execution_enabled": False, "prices": [], "reports": [],
              "limitations": ["当前20只ETF列表不是历史PIT股票池", "缺少退市证券和永久证券映射",
                              "Yahoo价格为拆股调整口径，不能作原始成交价", "SEC快照不是历史PIT基本面",
                              "2025起最终测试期封存；页面只展示同期及过去观察值"]}
    result['limitations']=['当前显式ETF列表不是历史PIT股票池','永久身份、退市和完整公司行为仍未验收','raw价格的跨期收益需要公司行为调整，缺失时显示N/A','SEC财务候选不具备PIT资格','旧 baseline 的 2025+ 封存仅约束旧实验；V4 可使用最新合格数据']
    if database.exists():
        try:
            bundle=load_real_bundle(database,source,asof,cutoff,raw_root=root/'data/raw')
            bundle.require('observation')
            frame=bundle.prices
            import pandas as pd
            day=pd.Timestamp(bundle.metadata['asof_date_et'])
            latest=frame.loc[pd.to_datetime(frame.date).eq(day)]
            result['source']=bundle.metadata['source']
            result['dataset']=bundle.metadata;result['capabilities']=bundle.capabilities
            result['feature_evidence']=feature_evidence(root,bundle.metadata)
            result.update(run_id=None,data_cutoff_utc=bundle.metadata['knowledge_cutoff_utc'],
                asof_date_et=bundle.metadata['asof_date_et'],model_version=None,
                source_provenance=bundle.metadata['source_provenance'],
                data_quality_flags=['CURRENT_VINTAGE_NOT_HISTORICAL_PIT','EXPLICIT_CURRENT_PROXY_LIST'])
            for row in latest.itertuples():
                result['prices'].append({'symbol':row.symbol,'date':str(pd.Timestamp(row.date).date()),'close':row.close,
                    'volume':row.volume,'return20':None,'basis':row.adjustment_basis,'available_at':row.available_at.isoformat(),
                    'sessions':int(frame.symbol.eq(row.symbol).sum())})
        except PolicyError as exc:
            result['error']=exc.payload()
    output_dirs = (folder for folder in (root / "outputs").glob("*")
                   if folder.is_dir() and folder.name not in PRIVATE_OUTPUTS)
    reports = (path for folder in output_dirs for path in folder.rglob("report.html"))
    for report in sorted(reports, key=lambda p:p.stat().st_mtime, reverse=True)[:40]:
        if allowed_artifact(root,report):
            result["reports"].append({"path":report.relative_to(root).as_posix(), "run":report.parent.name})
    result['policy']='REAL_ONLY'
    result['status']='OBSERVATION_ONLY' if result['prices'] else 'NOT_READY'
    if not result['prices']: result['source']=None
    return result


def action_commands(action,source='yahoo',database=None):
    if action=='asset-universe':
        return [['assets-sync','--endpoint','paper','--env-file','.env']]
    if action=='style-report':return [['style-report']]
    if action=='close-snapshot':return [['close-snapshot']]
    if action == 'daily-observation' or (action == 'daily' and source == 'alpaca'):
        return [['daily-observation']]
    if action=='market-research-yahoo':
        return [['train-market', '--source', 'yahoo', '--mode', 'retrospective',
                 '--db', 'data/research.duckdb', '--output', 'outputs/market_research']]
    if action == 'alpha-research-yahoo':
        return [['train', '--source', 'yahoo', '--mode', 'retrospective',
                 '--db', 'data/research.duckdb', '--output', 'outputs/alpha_research']]
    if action=='maintain-daily':
        if source!='alpaca':raise ValueError('Daily maintenance uses the reviewed Alpaca profile')
        return [['maintain-data','--cadence','daily','--env-file','.env']]
    database=database or ('data/real_v21.duckdb' if source=='alpaca' else 'data/research.duckdb')
    common = ["--source", source, "--db", str(database), "--output", "outputs/real"]
    if action == 'acceptance' and source == 'alpaca':
        return [['bundle-audit','--source',source,'--db',str(database)]]
    if action == "acceptance":
        return [["real-acceptance", "--db", "data/research.duckdb", "--output", "outputs/real_acceptance"]]
    if action in {"market-model", "alpha-model"}:
        return [["train-market" if action == "market-model" else "train", *common, "--mode", "retrospective"]]
    if action == "refresh":
        # End is a completed exchange session, not the workstation's local date.
        from .workflow.daily import resolve_day
        from .models.settings import load_settings
        from .clock import TradingClock
        end = resolve_day("auto", load_settings(Path("configs/experiments/baseline.yaml")), TradingClock())
        return [["ingest", *common, "--symbols", ",".join(SYMBOLS), "--start", "2017-01-03", "--end", end, "--refresh",
                 *(['--feed','sip','--env-file','.env'] if source=='alpaca' else [])]]
    if action == "market":
        return [["market-report", *common, "--mode", "retrospective"]]
    if action == "factors":
        return [["factor-report", *common, "--mode", "retrospective"]]
    if action == "daily":
        return [["daily-report", *common, "--mode", "retrospective", "--asof", "auto"]]
    raise ValueError("Unknown action")


class Console:
    def __init__(self, root,source='alpaca',database=None):
        self.root = root.resolve()
        self.source,self.database=source,database or self.root/('data/real_v21.duckdb' if source=='alpaca' else 'data/research.duckdb')
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job = {"status": "IDLE"}

    def start_experiment(self,identifier):
        from .research.factor_lab import Registry,valid_id
        identifier=valid_id(identifier)
        if (self.root/'data/catalog/.maintenance.lock').is_file():raise PolicyError('DATA_MAINTENANCE_RUNNING','Data maintenance is running')
        experiment=Registry(self.root).experiment(identifier)
        if experiment['status']!='CREATED':raise PolicyError('EXPERIMENT_FINALIZED','Create a new experiment to preserve prior results')
        if not self.lock.acquire(blocking=False):return False
        self.job={'status':'RUNNING','action':'factor-experiment','experiment_id':identifier,
                  'started_at':datetime.now(timezone.utc).isoformat(),'log_path':f'outputs/factor_lab/jobs/{identifier}.log'}
        threading.Thread(target=self.run_experiment,args=(identifier,),daemon=True).start()
        return True

    def run_experiment(self,identifier):
        log=self.root/self.job['log_path'];log.parent.mkdir(parents=True,exist_ok=True)
        try:
            with log.open('w',encoding='utf-8') as stream:
                code=subprocess.run([sys.executable,'-m','quant_research.cli','factor-lab-run','--experiment-id',identifier],
                    cwd=self.root,stdout=stream,stderr=subprocess.STDOUT,timeout=3600,shell=False).returncode
            self.job={**self.job,'status':'COMPLETED' if code==0 else 'DATA_BLOCKED_NO_ADVICE' if code==4 else 'FAILED','exit_codes':[code]}
        except Exception as exc:self.job={**self.job,'status':'FAILED','error':type(exc).__name__}
        finally:self.lock.release()

    def start(self, action):
        if (self.root/'data/catalog/.maintenance.lock').is_file():
            raise PolicyError('DATA_MAINTENANCE_RUNNING','Data maintenance is running; no concurrent workflow allowed')
        if action not in {"refresh", "market", "factors", "daily", "daily-observation", "acceptance", "market-model", "alpha-model", "maintain-daily", "style-report", "market-research-yahoo", "alpha-research-yahoo", "close-snapshot", "asset-universe"}:
            raise ValueError("Unknown action")
        if self.lock.locked():return False
        if action in {'market','factors','market-model','alpha-model'}:
            bundle=load_real_bundle(self.database,self.source,raw_root=self.root/'data/raw')
            bundle.require('exploratory_price_factors')
        if not self.lock.acquire(blocking=False):
            return False
        self.job = {"status":"RUNNING", "action":action, "started_at":datetime.now(timezone.utc).isoformat()}
        threading.Thread(target=self.run, args=(action,), daemon=True).start()
        return True

    def run(self, action):
        log = self.root / "outputs/real/console.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log.open("w", encoding="utf-8") as stream:
                codes = []
                for command in action_commands(action,self.source,self.database):
                    if action == 'acceptance':
                        command=['bundle-audit','--source',self.source,'--db',str(self.database)]
                    code = subprocess.run([sys.executable, "-m", "quant_research.cli", *command], cwd=self.root,
                                          stdout=stream, stderr=subprocess.STDOUT, timeout=21600 if action=="acceptance" else 3600, shell=False).returncode
                    codes.append(code)
                    if code: break
            status = "COMPLETED" if codes[-1] == 0 else ("DATA_BLOCKED_NO_ADVICE" if codes[-1] == 4 else "FAILED")
            self.job = {**self.job, "status":status, "exit_codes":codes}
        except Exception as exc:
            self.job = {**self.job, "status":"FAILED", "error":type(exc).__name__}
        finally:
            self.lock.release()


def handler(console):
    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, mime="application/json; charset=utf-8"):
            if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self):
            return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

        def do_GET(self):
            if not self.allowed(): return self.send(403, {"error":"Invalid host"})
            path = unquote(urlsplit(self.path).path)
            if path in {"/","/studio"}:
                html = Path(__file__).with_name("v4_shell.html").read_text(encoding="utf-8").replace("__TOKEN__", console.token)
                return self.send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            # Retired duplicate workspaces keep their old bookmarks, but no
            # longer instantiate the separate legacy UI.
            if path in {"/overview", "/market", "/styles"}:
                target={"/overview":"overview", "/market":"market",
                        "/styles":"style"}[path]
                self.send_response(302)
                self.send_header("Location", "/studio#" + target)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            # Advanced workflows not yet migrated (factor version editing,
            # strategy freeze/preflight, verified backtests, ledger and data
            # maintenance) retain their actual tools until feature parity.
            if path in {"/factors","/strategies","/backtests",
                        "/signals","/paper","/data"}:
                html = Path(__file__).with_name('app_shell.html').read_text(encoding='utf-8').replace('__TOKEN__', console.token)
                return self.send(200, html.encode('utf-8'), 'text/html; charset=utf-8')
            if path in {'/assets/studio.css','/assets/studio.js',
                        '/assets/v4_ui_core.js','/assets/v4_ui_pages_a.js',
                        '/assets/v4_ui_pages_b.js','/assets/v4_ui_pages_c.js',
                        '/assets/v4_ui_fidelity.js',
                        '/assets/v4_ui_market_v2.js', '/assets/v4_ui_market_v2.css',
                         '/assets/v4_ui_market_v3.js', '/assets/v4_ui_market_v3.css',
                         '/assets/v4_ui_light.css', '/assets/v4_ui_warehouse.js', '/assets/v4_ui_warehouse.css', '/assets/v4_ui_theme.js'}:
                asset = Path(__file__).with_name('assets') / path.rsplit('/',1)[1]
                content_type = 'text/css; charset=utf-8' if path.endswith('.css') else 'text/javascript; charset=utf-8'
                return self.send(200, asset.read_bytes(), content_type)
            if path in {'/api/v1/data/universe/asof', '/api/v1/data/universe/history',
                        '/api/v1/data/universe/resolve'}:
                from .data.forward_universe import asof_directory, observation_changes, resolve_symbols
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(v)!=1 for v in query.values()):
                        raise ValueError('Repeated universe query parameters')
                    params={key:values[0] for key,values in query.items()}
                    if path.endswith('/asof'):
                        if set(params)-{'asof','q','state','limit','offset'}:
                            raise ValueError('Unexpected asof parameter')
                        result=asof_directory(console.root,asof_utc=params.get('asof') or None,
                            q=params.get('q',''),state=params.get('state','candidate'),
                            limit=int(params.get('limit','30')),offset=int(params.get('offset','0')))
                    elif path.endswith('/history'):
                        if set(params)-{'limit'}:
                            raise ValueError('Unexpected history parameter')
                        result=observation_changes(console.root,limit=int(params.get('limit','30')))
                    else:
                        if set(params)-{'symbols','asof'} or not params.get('symbols'):
                            raise ValueError('Symbols required')
                        result=resolve_symbols(console.root,params['symbols'].split(','),
                                               asof_utc=params.get('asof') or None)
                    return self.send(200,result)
                except PolicyError as exc:
                    return self.send(409,exc.payload())
                except (ValueError,TypeError):
                    return self.send(400,{'status':'BLOCKED','code':'UNIVERSE_QUERY_INVALID'})
            if path == '/api/v1/data/actions/pages':
                from .data.action_pages import audit_action_pages
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if (set(q)-{'symbols','start','end','page_size','max_pages','asof'}
                            or any(len(v)!=1 for v in q.values())
                            or not {'symbols','start','end'} <= set(q)):
                        raise ValueError('Explicit exact archived source query required')
                    p={k:v[0] for k,v in q.items()}
                    return self.send(200,audit_action_pages(console.root,
                        symbols=p['symbols'].split(','),start=p['start'],end=p['end'],
                        page_size=int(p.get('page_size','1000')),
                        max_pages=int(p.get('max_pages','100')),asof_utc=p.get('asof') or None))
                except PolicyError as exc:return self.send(409,exc.payload())
                except (ValueError,TypeError):return self.send(400,{'status':'BLOCKED','code':'ACTION_PAGE_QUERY_INVALID'})
            if path == '/api/v1/backtests/verified':
                from .backtest.verified_results import list_verified_backtests,verified_backtest
                q=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if set(q)-{'run_id','scenario','limit'} or any(len(v)!=1 for v in q.values()):
                        raise ValueError('Invalid result filters')
                    p={k:v[0] for k,v in q.items()}
                    if p.get('run_id'):
                        if 'limit' in p:raise ValueError('Only run/scenario on detail')
                        return self.send(200,verified_backtest(console.root,p['run_id'],p.get('scenario')))
                    if p.get('scenario'):raise ValueError('Scenario requires run id')
                    return self.send(200,list_verified_backtests(console.root,limit=int(p.get('limit','15'))))
                except PolicyError as exc:return self.send(409,exc.payload())
                except (TypeError,ValueError):return self.send(400,{'status':'BLOCKED','code':'BACKTEST_QUERY_INVALID'})
            if path.startswith('/api/v1/strategies/') and path.endswith('/four-layers'):
                from .research.four_layers import evaluate_four_layers
                try:
                    if urlsplit(self.path).query:raise ValueError('Unexpected four-layer query')
                    identifier=path.removeprefix('/api/v1/strategies/').removesuffix('/four-layers')
                    return self.send(200,evaluate_four_layers(console.root,identifier))
                except PolicyError as exc:return self.send(409,exc.payload())
                except (ValueError,KeyError,OSError,sqlite3.Error):
                    return self.send(409,{'status':'BLOCKED','code':'G9_REAL_RESEARCH_EVIDENCE_INVALID'})
            if path == '/api/v1/data/actions/audit':
                from .data.action_audit import audit_events
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if set(query)-{'asof','symbol','database','limit','offset'} or any(len(v)!=1 for v in query.values()):
                        raise ValueError('Unapproved event audit parameters')
                    p={k:v[0] for k,v in query.items()}
                    result=audit_events(console.root,asof_utc=p.get('asof') or None,
                         symbol=p.get('symbol',''),database=p.get('database','all'),
                         limit=int(p.get('limit','30')),offset=int(p.get('offset','0')))
                    return self.send(200,result)
                except PolicyError as exc:
                    return self.send(409,exc.payload())
                except (ValueError,TypeError):
                    return self.send(400,{'status':'BLOCKED','code':'ACTION_AUDIT_QUERY_INVALID'})
            if path == '/api/v1/data/assets':
                from .data.assets import inventory
                try:
                    query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                    if set(query) - {'q','status','tradable','limit','offset'} or any(len(v)!=1 for v in query.values()):
                        raise ValueError('Unexpected asset query parameter')
                    values={k:v[0] for k,v in query.items()}
                    return self.send(200, inventory(console.root, q=values.get('q',''),
                        status=values.get('status','all'), tradable=values.get('tradable','all'),
                        limit=int(values.get('limit','30')),offset=int(values.get('offset','0'))))
                except PolicyError as exc:return self.send(409,exc.payload())
                except (ValueError,TypeError):return self.send(400,{'status':'BLOCKED','code':'ASSET_QUERY_INVALID'})
            if path == '/api/v1/research/readiness':
                from .workflow.research_readiness import research_readiness
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) - {'asof'} or any(len(v) != 1 for v in query.values()):
                    return self.send(400, {'status':'BLOCKED', 'code':'READINESS_QUERY_INVALID'})
                try:
                    result = research_readiness(console.root, db=console.database,
                                                asof=query.get('asof',[None])[0])
                    return self.send(200, result)
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (OSError, ValueError):
                    return self.send(409, {'status':'BLOCKED', 'code':'READINESS_LOCAL_EVIDENCE_UNAVAILABLE'})
            if path == '/api/v1/v4/freshness':
                if urlsplit(self.path).query:
                    return self.send(400, {'status':'BLOCKED','code':'FRESHNESS_QUERY_INVALID'})
                from .workflow.v4_freshness import current_v4_freshness
                try:
                    return self.send(200, current_v4_freshness(console.root))
                except (OSError, ValueError, duckdb.Error):
                    return self.send(409, {'status':'BLOCKED','code':'FRESHNESS_EVIDENCE_UNAVAILABLE'})
            if path == '/api/v1/signals/frozen':
                from .workflow.frozen_decisions import inspect_frozen_decision
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if set(query)-{'session'} or any(len(v)!=1 for v in query.values()):
                    return self.send(400,{'status':'BLOCKED','code':'FROZEN_QUERY_INVALID'})
                try:
                    data=inspect_frozen_decision(console.root,session=query.get('session',[None])[0],
                                                 db=console.database)
                    return self.send(200,data)
                except PolicyError as exc:
                    return self.send(409,exc.payload())
                except (OSError,ValueError,KeyError):
                    return self.send(409,{'status':'BLOCKED','code':'FROZEN_LOCAL_EVIDENCE_UNAVAILABLE'})
            if path == '/api/v1/signals':
                from .workflow.daily_observation import latest_report
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if query and (set(query) != {'asof'} or len(query['asof']) != 1):
                    return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_OBSERVATION_QUERY'})
                asof = query['asof'][0] if query else None
                if asof is not None:
                    try:
                        if date.fromisoformat(asof).isoformat() != asof:
                            raise ValueError('Expected ISO date')
                    except ValueError:
                        return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_OBSERVATION_QUERY'})
                try:
                    return self.send(200, latest_report(console.root, asof))
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (ValueError, KeyError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'DAILY_OBSERVATION_INVALID'})
            if path == '/api/v1/v4/forward-scorecard':
                from .workflow.v4_forward_scorecard import score_prospective_research
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if set(query)-{'minimum_sessions','baseline_sessions'} or any(
                        len(v)!=1 for v in query.values()):
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_FORWARD_SCORECARD_QUERY'})
                try:
                    minimum=int(query.get('minimum_sessions',['60'])[0])
                    lookback=int(query.get('baseline_sessions',['20'])[0])
                    if not 10<=minimum<=10000 or not 5<=lookback<=1000:
                        raise ValueError('Unsupported scorecard sample gate')
                except (ValueError,TypeError):
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_FORWARD_SCORECARD_QUERY'})
                try:
                    return self.send(200,score_prospective_research(
                        console.root,minimum_sessions=minimum,
                        baseline_sessions=lookback))
                except (OSError,KeyError,ValueError,TypeError):
                    return self.send(409,{'status':'BLOCKED','code':'FORWARD_SCORECARD_EVIDENCE_UNAVAILABLE'})
            if path == '/api/v1/v4/outcomes' or path.startswith('/api/v1/v4/outcomes/'):
                from .workflow.v4_plan_outcomes import (
                    latest_research_outcomes, read_research_outcomes)
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_OUTCOME_QUERY'})
                try:
                    if path == '/api/v1/v4/outcomes':
                        return self.send(200,latest_research_outcomes(console.root,limit=15))
                    parts=path.removeprefix('/api/v1/v4/outcomes/').split('/')
                    if len(parts)!=2:
                        raise ValueError('Invalid outcome reference')
                    return self.send(200,read_research_outcomes(console.root,parts[0],parts[1]))
                except FileNotFoundError:
                    return self.send(404,{'status':'BLOCKED','code':'RESEARCH_OUTCOME_NOT_FOUND'})
                except (OSError,ValueError,KeyError,TypeError):
                    return self.send(409,{'status':'BLOCKED','code':'RESEARCH_OUTCOME_UNVERIFIED'})
            if path == '/api/v1/v4/plans' or path.startswith('/api/v1/v4/plans/'):
                from .workflow.v4_candidate_bridge import (
                    latest_indicative_reviews, read_indicative_review)
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_RESEARCH_PLAN_QUERY'})
                try:
                    if path == '/api/v1/v4/plans':
                        return self.send(200,latest_indicative_reviews(console.root,limit=15))
                    parts=path.removeprefix('/api/v1/v4/plans/').split('/')
                    if len(parts)!=2:
                        raise ValueError('Invalid plan key')
                    return self.send(200,read_indicative_review(console.root,parts[0],parts[1]))
                except FileNotFoundError:
                    return self.send(404,{'status':'BLOCKED','code':'RESEARCH_PLAN_NOT_FOUND'})
                except (ValueError,KeyError,OSError,TypeError):
                    return self.send(409,{'status':'BLOCKED','code':'RESEARCH_PLAN_UNVERIFIED'})
            if path == '/api/v1/v4/forecasts' or path.startswith('/api/v1/v4/forecasts/'):
                from .research.v4_forecast_archive import (
                    latest_forward_research, read_research_forecast)
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'UNEXPECTED_FORECAST_QUERY'})
                try:
                    if path == '/api/v1/v4/forecasts':
                        return self.send(200,{'status':'FORWARD_RESEARCH_ARCHIVE_ONLY',
                            'records':latest_forward_research(console.root,limit=5),
                            'real_orders_enabled':False})
                    parts=path.removeprefix('/api/v1/v4/forecasts/').split('/')
                    if len(parts)!=2:
                        raise ValueError('Forecast route needs date and identity')
                    item=read_research_forecast(console.root,parts[0],parts[1],include_rows=True)
                    if item['manifest']['forecast_rows']>20000:
                        raise ValueError('Forecast exceeds browser display quota')
                    # Return the top studied D candidates per horizon rather than
                    # truncating the first 200 stored rows, which would hide the
                    # D variant behind earlier A/B/C model rows.
                    studied=item['forecasts'].loc[item['forecasts'].model_variant.eq('D')].copy()
                    studied=studied.sort_values(['horizon','expected_gross_trade_return'],
                                                ascending=[True,False],na_position='last')
                    studied=studied.groupby('horizon',sort=True).head(40)
                    item['forecasts']=json.loads(studied.to_json(orient='records',date_format='iso'))
                    item['model_cards']=json.loads(item['model_cards'].head(200).to_json(
                        orient='records',date_format='iso'))
                    return self.send(200,item)
                except FileNotFoundError:
                    return self.send(404,{'status':'BLOCKED','code':'FORECAST_ARCHIVE_NOT_FOUND'})
                except (ValueError,OSError,KeyError,TypeError):
                    return self.send(409,{'status':'BLOCKED',
                        'code':'FORECAST_ARCHIVE_INVALID_OR_UNVERIFIED'})
            if path == '/api/v1/v4/daily':
                from .workflow.v4_daily import latest_v4_daily
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'UNEXPECTED_DAILY_QUERY'})
                try:
                    return self.send(200,latest_v4_daily(console.root,limit=5))
                except (ValueError,OSError):
                    return self.send(409,{'status':'BLOCKED','code':'V4_DAILY_ARCHIVE_UNREADABLE'})
            if path == '/api/v1/v4/research/runs' or path.startswith('/api/v1/v4/research/runs/'):
                from .research.v4_artifacts import list_research_runs, read_research_run
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'UNEXPECTED_RESEARCH_QUERY'})
                try:
                    if path == '/api/v1/v4/research/runs':
                        return self.send(200,{'status':'RESEARCH_ARCHIVE_INDEX',
                                              'runs':list_research_runs(console.root),
                                              'real_orders_enabled':False})
                    run_id=path.removeprefix('/api/v1/v4/research/runs/')
                    if not run_id or '/' in run_id:
                        raise ValueError('Invalid research archive path')
                    data=read_research_run(console.root,run_id)
                    import pandas as pd
                    for name in ('folds','metrics','increment_vs_alpha_only','alpha_ranking'):
                        data[name]=json.loads(data[name].head(200).to_json(orient='records',date_format='iso'))
                    return self.send(200,data)
                except FileNotFoundError:
                    return self.send(404,{'status':'BLOCKED','code':'RESEARCH_RUN_NOT_FOUND'})
                except (ValueError,OSError,KeyError,TypeError):
                    return self.send(409,{'status':'BLOCKED','code':'RESEARCH_RUN_INVALID_OR_UNVERIFIED'})
            if path == '/api/v1/paper/timeline':
                from .workflow.paper_timeline import paper_timeline
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if set(query)-{'limit'} or any(len(v)!=1 for v in query.values()):
                    return self.send(400,{'status':'BLOCKED','code':'PAPER_TIMELINE_QUERY_INVALID'})
                try:
                    limit=int(query.get('limit',['20'])[0])
                    return self.send(200,paper_timeline(console.root,limit=limit))
                except (ValueError,TypeError):
                    return self.send(400,{'status':'BLOCKED','code':'PAPER_TIMELINE_QUERY_INVALID'})
                except PolicyError as exc:
                    return self.send(409,exc.payload())
            if path == '/api/v1/paper':
                from .workflow.forward_observations import inventory
                return self.send(200, inventory(console.root))
            if path == '/api/v1/paper/risk':
                from .backtest.paper import account_summary
                from .models.settings import load_settings
                from .risk.portfolio import assess_paper_concentration, RiskPolicy
                try:
                    config = load_settings(console.root/'configs/experiments/baseline.yaml')
                    account = account_summary(console.root/'data/paper.sqlite3',config)
                    policy = RiskPolicy(max_stock_weight=config.max_stock_weight,
                                        max_sector_weight=config.max_sector_weight,
                                        max_gross_weight=config.max_total_weight)
                    return self.send(200, assess_paper_concentration(account,policy))
                except (OSError,ValueError,KeyError):
                    return self.send(409, {'status':'BLOCKED','code':'PAPER_RISK_CONFIG_INVALID'})
            if path == '/api/v1/paper/account':
                from .backtest.paper import account_summary
                from .models.settings import load_settings
                try:
                    config=load_settings(console.root/'configs/experiments/baseline.yaml')
                    return self.send(200,account_summary(console.root/'data/paper.sqlite3',config))
                except (OSError,ValueError,KeyError):
                    return self.send(409,{'status':'BLOCKED','code':'PAPER_CONFIG_MISSING'})
            if path in ('/api/v1/l1/v3/latest',
                        '/api/v1/l1/v3/overview',
                        '/api/v1/l1/v3/status'):
                # Read-only browser contract: NEVER download years of bars,
                # train an estimator, freeze research, or call Alpaca in GET.
                if urlsplit(self.path).query:
                    return self.send(400,{'schema':'qdr.l1.probability.v3',
                        'status':'BLOCKED','code':'V3_QUERY_NOT_ALLOWED_READ_ONLY'})
                from .workflow.l1_v3_pipeline import (
                    latest_frozen,current_pipeline_status)
                from .data.l1_light_sources import SourceUnavailable
                try:
                    if path.endswith('/status'):
                        return self.send(200,current_pipeline_status(console.root))
                    return self.send(200,latest_frozen(console.root))
                except SourceUnavailable as exc:
                    return self.send(409,{'schema':'qdr.l1.probability.v3',
                        'status':'BLOCKED','code':exc.code})
                except (ValueError,OSError,KeyError,TypeError):
                    return self.send(409,{'schema':'qdr.l1.probability.v3',
                        'status':'BLOCKED','code':'V3_FROZEN_RESEARCH_INVALID'})
            if path == '/api/v1/l1/v3/outcomes':
                from .workflow.l1_v3_outcomes import recent_v3_outcomes
                from .workflow.l1_v3_scorecard import forward_scorecard
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_QUERY'})
                try:
                    return self.send(200,{'schema':'qdr.l1.v3.outcomes',
                        'status':'RESEARCH_SETTLEMENT_ONLY',
                        'records':recent_v3_outcomes(console.root,limit=30),
                        'forward_scorecard':forward_scorecard(console.root),
                        'real_orders_enabled':False})
                except (ValueError,OSError,TypeError):
                    return self.send(409,{'status':'BLOCKED',
                                          'code':'V3_OUTCOME_ARCHIVE_UNAVAILABLE'})
            if path == '/api/v1/l1/v3/history':
                from .workflow.l1_v3 import recent_research_snapshots
                if urlsplit(self.path).query:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_QUERY'})
                try:
                    return self.send(200,{'schema':'qdr.l1.v3.history',
                        'status':'RESEARCH_ARCHIVE_ONLY',
                        'records':recent_research_snapshots(console.root,limit=15)})
                except (ValueError,OSError,TypeError):
                    return self.send(409,{'status':'BLOCKED','code':'V3_ARCHIVE_UNAVAILABLE'})
            if path == '/api/v1/l1/v2/official':
                from .data.l1_official_sources import scan_official_l1
                q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(q) - {'refresh'} or any(len(v) != 1 for v in q.values()) or q.get('refresh', ['0'])[0] not in ('0','1'):
                    return self.send(400, {'schema':'qdr.l1.official.v1',
                                           'status':'BLOCKED','code':'INVALID_QUERY'})
                try:
                    data=scan_official_l1(console.root,
                        refresh=q.get('refresh', ['0'])[0] == '1')
                    try:
                        from .workflow.l1_market_ingest import persist_public_scan
                        data["persistence"]=persist_public_scan(console.root,data,scan_kind="official")
                    except Exception as exc:
                        data["persistence"]={"status":"FAILED","code":type(exc).__name__}
                    return self.send(200,data)
                except (ValueError, OSError, TypeError):
                    return self.send(409, {'schema':'qdr.l1.official.v1',
                                           'status':'BLOCKED','code':'OFFICIAL_DATA_INVALID'})
            if path == '/api/v1/l1/v2/extended':
                from .data.l1_public_extended import scan_extended_public
                q = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(q)-{'refresh'} or any(len(v)!=1 for v in q.values()) or q.get('refresh',['0'])[0] not in ('0','1'):
                    return self.send(400,{'schema':'qdr.l1.extended.v1',
                                          'status':'BLOCKED','code':'INVALID_QUERY'})
                try:
                    data=scan_extended_public(console.root,
                        refresh=q.get('refresh',['0'])[0]=='1')
                    try:
                        from .workflow.l1_market_ingest import persist_public_scan
                        data["persistence"]=persist_public_scan(console.root,data,scan_kind="extended")
                    except Exception as exc:
                        data["persistence"]={"status":"FAILED","code":type(exc).__name__}
                    return self.send(200,data)
                except (ValueError,OSError,TypeError,KeyError):
                    return self.send(409,{'schema':'qdr.l1.extended.v1',
                                          'status':'BLOCKED','code':'EXTENDED_PUBLIC_DATA_INVALID'})
            if path == '/api/v1/l1/v2/overview':
                from .workflow.l1_v2 import current_l1_v2
                from .data.l1_light_sources import SourceUnavailable
                params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(params)-{'horizon','refresh'} or any(len(v)!=1 for v in params.values()):
                    return self.send(400,{'schema':'qdr.l1.v2','status':'BLOCKED','code':'INVALID_QUERY'})
                if params.get('horizon',['3'])[0] not in ('1','3','5') or params.get('refresh',['0'])[0] not in ('0','1'):
                    return self.send(400,{'schema':'qdr.l1.v2','status':'BLOCKED','code':'INVALID_QUERY'})
                try:
                    data=current_l1_v2(console.root,refresh=params.get('refresh',['0'])[0]=='1')
                    try:
                        from .workflow.l1_market_ingest import persist_l1_v2
                        data["persistence"]=persist_l1_v2(console.root,data)
                    except Exception as exc:
                        data["persistence"]={"status":"FAILED","code":type(exc).__name__}
                    return self.send(200,data)
                except SourceUnavailable as exc:
                    return self.send(409,{'schema':'qdr.l1.v2','status':'BLOCKED','code':exc.code})
                except (ValueError, OSError, KeyError, TypeError):
                    return self.send(409,{'schema':'qdr.l1.v2','status':'BLOCKED','code':'L1_V2_DATA_INVALID'})
            if path == '/api/v1/l1/market-data/coverage':
                from .workflow.l1_market_ingest import market_data_snapshot
                from datetime import date as date_cls
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query)-{'asof'} or any(len(v)!=1 for v in query.values()):
                    return self.send(400,{'schema':'qdr.l1.market_data_snapshot.v1',
                                          'status':'BLOCKED','code':'INVALID_QUERY'})
                asof=query.get('asof',[None])[0]
                try:
                    if asof is not None and date_cls.fromisoformat(asof).isoformat()!=asof:
                        raise ValueError("Invalid asof")
                    return self.send(200,market_data_snapshot(console.root,asof=asof))
                except (ValueError,OSError,KeyError,TypeError):
                    return self.send(409,{'schema':'qdr.l1.market_data_snapshot.v1',
                                          'status':'BLOCKED','code':'MARKET_DATA_SNAPSHOT_INVALID'})
            if path.startswith('/api/v1/l1/'):
                from .workflow.l1_runtime import (
                    L1Blocked, market_overview_for_api, observations_for_api,
                    anomalies_for_api, validation_for_api, replay_for_api,
                )
                from datetime import date as date_cls
                routes = {'/api/v1/l1/market/overview', '/api/v1/l1/observations',
                          '/api/v1/l1/anomalies', '/api/v1/l1/validation',
                          '/api/v1/l1/replay'}
                if path not in routes:
                    return self.send(404, {'status':'BLOCKED','code':'L1_ROUTE_NOT_FOUND'})
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                fields = {'asof','horizon'} if path == '/api/v1/l1/replay' else (
                    {'horizon','asof'} if path == '/api/v1/l1/market/overview' else (
                    {'asof'} if path in {'/api/v1/l1/observations','/api/v1/l1/anomalies'} else set()))
                if set(query)-fields or any(len(v)!=1 for v in query.values()):
                    return self.send(400, {'status':'BLOCKED','code':'L1_QUERY_INVALID'})
                asof = query.get('asof',[None])[0]
                try:
                    if asof is not None and (date_cls.fromisoformat(asof).isoformat()!=asof):
                        raise ValueError('Invalid asof')
                    horizon = query.get('horizon',['3'])[0]
                    if path in {'/api/v1/l1/market/overview','/api/v1/l1/replay'} and horizon not in {'1','3','5'}:
                        raise ValueError('Invalid horizon')
                except (ValueError,TypeError):
                    return self.send(400, {'status':'BLOCKED','code':'L1_QUERY_INVALID'})
                try:
                    if path == '/api/v1/l1/market/overview':
                        payload = market_overview_for_api(console.root,int(horizon),asof)
                    elif path == '/api/v1/l1/observations':
                        payload = observations_for_api(console.root,asof)
                    elif path == '/api/v1/l1/anomalies':
                        payload = anomalies_for_api(console.root,asof)
                    elif path == '/api/v1/l1/validation':
                        payload = validation_for_api(console.root)
                    else:
                        if asof is None:raise ValueError('Replay requires an asof')
                        payload = replay_for_api(console.root,asof,int(horizon))
                    return self.send(200,payload)
                except L1Blocked as exc:
                    return self.send(409, {'status':'BLOCKED','code':exc.code})
                except (ValueError,OSError,KeyError):
                    return self.send(409, {'status':'BLOCKED','code':'L1_RESEARCH_ARTIFACT_INVALID'})
            if path == '/api/v1/market/research':
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) - {'asof', 'horizon'} or any(len(values) != 1 for values in query.values()):
                    return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_MARKET_QUERY'})
                horizon = query.get('horizon', ['1'])[0]
                asof = query.get('asof', [None])[0]
                try:
                    if horizon not in {'1', '3', '5'}:
                        raise ValueError('Unsupported horizon')
                    if asof is not None and (date.fromisoformat(asof).isoformat() != asof or asof >= '2025-01-01'):
                        raise ValueError('Unsupported study date')
                except ValueError:
                    return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_MARKET_QUERY'})
                try:
                    return self.send(200, market_research(console.root, int(horizon), asof))
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (ValueError, KeyError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'MARKET_STUDY_ARTIFACT_INVALID'})
            if path == '/api/v1/strategies':
                from .research.factor_lab import Registry
                from .research.strategy import StrategyRegistry
                try:
                    factors = Registry(console.root)
                    experiments = factors.experiments() if factors.path.is_file() else []
                    versions = {item['id']: item for item in factors.factors()} if experiments else {}
                    return self.send(200, {
                        'strategies': StrategyRegistry(console.root).versions(),
                        'factor_experiments': [
                            {'id': item['id'], 'factor_name': versions[item['factor_version_id']]['name'],
                             'factor_version': versions[item['factor_version_id']]['version']}
                            for item in experiments if item['status'] == 'COMPLETED' and item['config']['source'] == 'yahoo'
                        ],
                    })
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (sqlite3.Error, ValueError, KeyError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'STRATEGY_REGISTRY_INVALID'})
            if path.startswith('/api/v1/strategies/') and path.endswith('/composite'):
                from .research.composite import compute_composite
                try:
                    if urlsplit(self.path).query:
                        return self.send(400, {'status':'BLOCKED','code':'UNSUPPORTED_COMPOSITE_QUERY'})
                    identifier = path.removeprefix('/api/v1/strategies/').removesuffix('/composite')
                    return self.send(200, compute_composite(console.root, identifier))
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (ValueError, KeyError, OSError, sqlite3.Error):
                    return self.send(409, {'status':'BLOCKED','code':'COMPOSITE_RESEARCH_EVIDENCE_INVALID'})
            if path.startswith('/api/v1/strategies/') and path.endswith('/preflight'):
                from .research.strategy import StrategyRegistry
                try:
                    identifier = path.removeprefix('/api/v1/strategies/').removesuffix('/preflight')
                    strategy = StrategyRegistry(console.root).get(identifier)
                    folder = console.root / 'outputs/strategy_preflight'
                    for manifest_path in sorted(folder.glob('*/manifest.json'), key=lambda p: p.stat().st_mtime, reverse=True):
                        meta = json.loads(manifest_path.read_text(encoding='utf-8'))
                        if (meta.get('workflow') != 'strategy-preflight'
                                or meta.get('strategy_version_id') != strategy['id']
                                or meta.get('strategy_config_sha256') != strategy['config_sha256']):
                            continue
                        evidence = manifest_path.parent / 'eligibility.json'
                        report_path = manifest_path.parent / 'report.html'
                        if not all(allowed_artifact(console.root, file) for file in (evidence, report_path)):
                            raise PolicyError('PREFLIGHT_ARTIFACT_CORRUPT', 'Preflight report failed SHA256 verification')
                        data = json.loads(evidence.read_text(encoding='utf-8'))
                        return self.send(200, {**data,
                            'report_path': report_path.relative_to(console.root).as_posix(),
                            'evidence_path': evidence.relative_to(console.root).as_posix(),
                        })
                    raise PolicyError('NO_PREFLIGHT_REPORT', 'No eligibility report exists for this strategy')
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (sqlite3.Error, ValueError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'PREFLIGHT_EVIDENCE_INVALID'})
            if path == '/api/v1/alpha/research':
                directory = console.root / 'outputs/alpha_research'
                for report_path in sorted(directory.glob('*/report.html'), key=lambda p: p.stat().st_mtime, reverse=True):
                    if not allowed_artifact(console.root, report_path):
                        continue
                    evidence = json.loads((report_path.parent / 'manifest.json').read_text(encoding='utf-8'))
                    if (evidence.get('source') != 'yahoo' or not evidence.get('source_provenance')
                            or evidence.get('status') != 'RETROSPECTIVE_MODEL_STUDY_NOT_TRADING'
                            or evidence.get('sealed_test_used') is not False
                            or evidence.get('decision_eligible_rows') != 0):
                        continue
                    return self.send(200, {
                        'run_id': evidence['run_id'], 'source': evidence['source'],
                        'prediction_rows': evidence['prediction_rows'], 'status': evidence['status'],
                        'report_path': report_path.relative_to(console.root).as_posix(),
                    })
                return self.send(409, {'status': 'BLOCKED', 'code': 'NO_COMPLETED_ALPHA_STUDY'})
            if path.startswith('/api/v1/factor-lab/'):
                try:
                    from .research.factor_lab import Registry
                    from .workflow.factor_lab import preview,result,compare
                    registry=Registry(console.root);query=parse_qs(urlsplit(self.path).query)
                    if any(len(v)!=1 for v in query.values()):raise ValueError('Repeated parameters')
                    if path=='/api/v1/factor-lab/library' and not query:
                        return self.send(200,{'factor_versions':registry.factors(),'experiments':registry.experiments(),
                            'templates':['reversal','momentum','volatility'],'policy':'REAL_ONLY','execution_ready':False})
                    if path=='/api/v1/factor-lab/preview' and set(query)=={'version_id','source'}:
                        return self.send(200,preview(console.root,query['version_id'][0],query['source'][0]))
                    if path=='/api/v1/factor-lab/compare' and set(query)=={'left','right'}:
                        return self.send(200,compare(console.root,query['left'][0],query['right'][0]))
                    if path.startswith('/api/v1/factor-lab/experiments/') and not query:
                        return self.send(200,result(console.root,path.removeprefix('/api/v1/factor-lab/experiments/')))
                    raise ValueError('Invalid factor-lab route or parameters')
                except PolicyError as exc:return self.send(409,exc.payload())
                except ValueError:return self.send(400,{'status':'BLOCKED','code':'INVALID_FACTOR_LAB_REQUEST'})
                except Exception as exc:return self.send(503,{'status':'BLOCKED','code':type(exc).__name__})
            if path=='/api/v1/jobs/current':return self.send(200,console.job)
            if path == '/api/v1/l2/styles/overview':
                try:
                    query=parse_qs(urlsplit(self.path).query)
                    if set(query)-{'asof','cutoff','start'} or any(len(v)!=1 for v in query.values()):
                        raise ValueError('Invalid L2 style query')
                    asof=query.get('asof',[None])[0]
                    cutoff=datetime.fromisoformat(query['cutoff'][0]) if 'cutoff' in query else None
                    start=query.get('start',['2017-01-03'])[0]
                    if asof is not None and date.fromisoformat(asof).isoformat()!=asof:
                        raise ValueError('Invalid L2 asof date')
                    from .workflow.l2_styles import calculate
                    return self.send(200,calculate(console.root,asof=asof,cutoff=cutoff,start=start))
                except PolicyError as exc:return self.send(409,exc.payload())
                except ValueError as exc:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_L2_STYLE_REQUEST','detail':str(exc)})
                except Exception as exc:return self.send(503,{'status':'BLOCKED','code':type(exc).__name__})
            if path in {'/api/v1/styles','/api/v1/styles/export.csv'}:
                try:
                    query=parse_qs(urlsplit(self.path).query)
                    if set(query)-{'asof','cutoff','mode'} or any(len(v)!=1 for v in query.values()):raise ValueError('Invalid style query')
                    from .workflow.styles import calculate
                    cutoff=datetime.fromisoformat(query['cutoff'][0]) if 'cutoff' in query else None
                    _,summary,_,data=calculate(console.root,query.get('asof',[None])[0],cutoff,query.get('mode',['observation'])[0])
                    if path.endswith('.csv'):
                        for k in ('source','asof_date_et','data_cutoff_utc','snapshot_sha256','eligibility'):summary[k]=data[k]
                        return self.send(200,summary.to_csv(index=False).encode('utf-8-sig'),'text/csv; charset=utf-8')
                    return self.send(200,data)
                except PolicyError as exc:return self.send(409,exc.payload())
                except ValueError:return self.send(400,{'status':'BLOCKED','code':'INVALID_STYLE_REQUEST'})
                except Exception as exc:return self.send(503,{'status':'BLOCKED','code':type(exc).__name__})
            if path=='/api/v1/jobs/current/log':
                log=(console.root/console.job.get('log_path','outputs/real/console.log')).resolve()
                if not log.is_relative_to((console.root/'outputs').resolve()):return self.send(404,{'status':'NOT_FOUND'})
                if console.job.get('status')=='IDLE' or not log.is_file():
                    return self.send(404,{'status':'NOT_READY','code':'NO_CURRENT_JOB_LOG'})
                return self.send(200,log.read_bytes(),'text/plain; charset=utf-8')
            if path == '/api/v1/data/close-snapshots':
                from .data.close_snapshot import read_snapshot
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if query and (set(query) != {'asof'} or len(query['asof']) != 1):
                    return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_CLOSE_SNAPSHOT_QUERY'})
                asof = query['asof'][0] if query else None
                if asof is not None:
                    try:
                        if date.fromisoformat(asof).isoformat() != asof:
                            raise ValueError('Expected ISO date')
                    except ValueError:
                        return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_CLOSE_SNAPSHOT_QUERY'})
                try:
                    return self.send(200, read_snapshot(console.root, asof))
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except (sqlite3.Error, ValueError, KeyError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'CLOSE_SNAPSHOT_INVALID'})
            if path.startswith('/api/v1/warehouse'):
                from .data.warehouse_observability import (
                    overview as warehouse_overview, dataset_detail as warehouse_dataset_detail,
                    preview_dataset as warehouse_preview_dataset, maintenance_runs as warehouse_runs,
                )
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                try:
                    if any(len(values)!=1 for values in query.values()):
                        raise ValueError('Repeated warehouse query parameters')
                    params={key:values[0] for key,values in query.items()}
                    if path == '/api/v1/warehouse/overview':
                        if params: raise ValueError('Unexpected warehouse overview parameter')
                        return self.send(200,warehouse_overview(console.root))
                    if path == '/api/v1/warehouse/runs':
                        if set(params)-{'limit'}: raise ValueError('Unexpected maintenance run parameter')
                        return self.send(200,warehouse_runs(console.root,limit=int(params.get('limit','20'))))
                    prefix='/api/v1/warehouse/datasets/'
                    if path.startswith(prefix):
                        parts=path[len(prefix):].split('/')
                        if not parts[0] or len(parts)>2 or (len(parts)==2 and parts[1]!='preview'):
                            return self.send(404,{'status':'NOT_FOUND','code':'WAREHOUSE_ROUTE_NOT_FOUND'})
                        dataset_id=parts[0]
                        if len(parts)==1:
                            if params: raise ValueError('Dataset detail does not accept query parameters')
                            return self.send(200,warehouse_dataset_detail(console.root,dataset_id))
                        allowed={'q','start','end','symbol','dimension','limit','offset'}
                        if set(params)-allowed: raise ValueError('Unexpected preview parameter')
                        return self.send(200,warehouse_preview_dataset(
                            console.root,dataset_id,q=params.get('q',''),
                            start=params.get('start') or None,end=params.get('end') or None,
                            symbol=params.get('symbol') or None,dimension=params.get('dimension') or None,
                            limit=int(params.get('limit','25')),offset=int(params.get('offset','0'))))
                    return self.send(404,{'status':'NOT_FOUND','code':'WAREHOUSE_ROUTE_NOT_FOUND'})
                except PolicyError as exc:
                    return self.send(409,exc.payload())
                except KeyError:
                    return self.send(404,{'status':'NOT_FOUND','code':'WAREHOUSE_DATASET_NOT_FOUND'})
                except (ValueError,TypeError):
                    return self.send(400,{'status':'BLOCKED','code':'WAREHOUSE_QUERY_INVALID'})
                except Exception as exc:
                    return self.send(503,{'status':'BLOCKED','code':'WAREHOUSE_READ_FAILED',
                                          'error_type':type(exc).__name__})
            if path.startswith('/api/v1/data/catalog'):
                from .data.catalog import catalog_artifact
                names={'/api/v1/data/catalog':'catalog.json','/api/v1/data/catalog/datasets.csv':'datasets.csv',
                       '/api/v1/data/catalog/cache_index.csv':'cache_index.csv','/api/v1/data/catalog/excluded_stores.csv':'excluded_stores.csv'}
                if path not in names:return self.send(404,{'status':'NOT_FOUND'})
                try:
                    body=catalog_artifact(console.root,names[path])
                    if names[path]=='catalog.json':
                        data=json.loads(body);data.pop('cache_index',None)
                        return self.send(200,data)
                    return self.send(200,body,'text/csv; charset=utf-8')
                except PolicyError as exc:return self.send(409,exc.payload())
                except (ValueError,OSError,KeyError):return self.send(409,{'status':'BLOCKED','code':'CATALOG_INVALID'})
            if path in {"/api/status","/api/v1/system/status","/api/v1/data/quality","/api/v1/market"}:
                try:
                    query=parse_qs(urlsplit(self.path).query)
                    if set(query)-{'asof','cutoff'} or any(len(values)!=1 for values in query.values()):
                        raise ValueError('Only single asof/cutoff parameters are accepted')
                    cutoff=datetime.fromisoformat(query['cutoff'][0]) if 'cutoff' in query else None
                    data = snapshot(console.root,console.source,console.database,query.get('asof',[None])[0],cutoff) if not console.lock.locked() else {"busy":True}
                    if path=='/api/v1/market':
                        data.update(predictions=[],model_status='BLOCKED_HISTORICAL_MODEL_EVIDENCE',model_version=None)
                    return self.send(200, {**data, "job":console.job})
                except PolicyError as exc:
                    return self.send(409,exc.payload())
                except ValueError:
                    return self.send(400,{'status':'BLOCKED','code':'INVALID_REQUEST','message':'Invalid observation date or timezone-aware cutoff'})
                except Exception as exc:
                    return self.send(503, {"error":type(exc).__name__, "job":console.job})
            target = (console.root / path.lstrip("/")).resolve()
            output = (console.root / "outputs").resolve()
            if allowed_artifact(console.root,target) and target.suffix in {".html", ".csv", ".json", ".log", ".svg"}:
                mime = {".html":"text/html; charset=utf-8", ".svg":"image/svg+xml", ".log":"text/plain; charset=utf-8", ".csv":"text/csv; charset=utf-8"}.get(target.suffix, "application/json")
                return self.send(200, target.read_bytes(), mime)
            self.send(404, {"error":"Not found"})

        def do_POST(self):
            if not self.allowed() or self.headers.get("X-Console-Token") != console.token:
                return self.send(403, {"error":"Invalid token or host"})
            path=urlsplit(self.path).path
            if path == '/api/v1/strategies' or path.startswith('/api/v1/strategies/'):
                from .research.strategy import StrategyRegistry
                from .workflow.strategy_preflight import preflight
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= length <= 32768:
                        raise ValueError('Invalid strategy request size')
                    payload = json.loads(self.rfile.read(length)) if length else {}
                    if not isinstance(payload, dict):
                        raise ValueError('Expected object')
                    registry = StrategyRegistry(console.root)
                    if path == '/api/v1/strategies':
                        return self.send(201, registry.create(payload))
                    parts = path.removeprefix('/api/v1/strategies/').split('/')
                    if payload or len(parts) != 2:
                        raise ValueError('Invalid strategy operation')
                    identifier, operation = parts
                    if operation == 'validate':
                        return self.send(200, registry.validate(identifier))
                    if operation == 'freeze':
                        return self.send(200, registry.freeze(identifier))
                    if operation == 'preflight':
                        if not console.lock.acquire(blocking=False):
                            raise PolicyError('CONSOLE_BUSY', 'Wait for the current task to finish')
                        try:
                            return self.send(200, preflight(console.root, identifier))
                        finally:
                            console.lock.release()
                    raise ValueError('Invalid strategy operation')
                except PolicyError as exc:
                    return self.send(409, exc.payload())
                except ValueError:
                    return self.send(400, {'status': 'BLOCKED', 'code': 'INVALID_STRATEGY_REQUEST'})
                except (sqlite3.Error, KeyError, OSError):
                    return self.send(409, {'status': 'BLOCKED', 'code': 'STRATEGY_EVIDENCE_UNAVAILABLE'})
            if path.startswith('/api/v1/factor-lab/'):
                try:
                    from .research.factor_lab import Registry
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<=size<=32768:raise ValueError('Request body exceeds limit')
                    body=json.loads(self.rfile.read(size)) if size else {}
                    if not isinstance(body,dict):raise ValueError('Object body required')
                    registry=Registry(console.root)
                    if path=='/api/v1/factor-lab/factors':return self.send(201,registry.create_factor(body))
                    if path=='/api/v1/factor-lab/experiments':return self.send(201,registry.create_experiment(body))
                    if path.startswith('/api/v1/factor-lab/experiments/') and path.endswith('/run') and not body:
                        identifier=path.removeprefix('/api/v1/factor-lab/experiments/').removesuffix('/run')
                        started=console.start_experiment(identifier)
                        return self.send(202 if started else 409,console.job)
                    raise ValueError('Invalid factor-lab operation')
                except PolicyError as exc:return self.send(409,exc.payload())
                except ValueError:return self.send(400,{'status':'BLOCKED','code':'INVALID_FACTOR_LAB_REQUEST'})
            action = urlsplit(self.path).path.removeprefix("/api/run/")
            try:
                started = console.start(action)
                self.send(202 if started else 409, console.job)
            except PolicyError as exc:
                self.send(409,exc.payload())
            except ValueError:
                self.send(400, {"error":"Unknown action"})
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument('--source',choices=['alpaca','yahoo'],default='alpaca')
    parser.add_argument('--db',type=Path)
    args = parser.parse_args(argv)
    root = Path.cwd()
    if not (root / "configs/sources.yaml").is_file():
        parser.error("Start from project root")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(Console(root,args.source,args.db)))
    print(f"Real-data console: http://127.0.0.1:{server.server_port} (Ctrl+C stops)", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == "__main__":
    main()
