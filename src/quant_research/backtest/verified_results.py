"""G10 read-only evidence-gated display for *completed real* historical replays.

Never produces modeled fills or P&L. Missing or unverifiable runs are hidden,
with a specific error when an explicitly selected run fails verification.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import UUID

from quant_research.policy import PolicyError

RUN_STATUS = 'MODELED_HISTORICAL_FILLS_NOT_BROKER_ORDERS'
_RUN = re.compile(r'[0-9a-fA-F-]{36}\Z')
_SCENARIO = re.compile(r'h(?:1|3|5)_cost_(?:5|10|20|50)bps\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')


def _allowed_run(root, run_id):
    try:
        if not _RUN.fullmatch(run_id) or str(UUID(run_id)) != run_id:
            raise ValueError()
    except (TypeError, ValueError):
        raise PolicyError('BACKTEST_RUN_ID_INVALID', 'Expected a canonical UUID from the real run archive') from None
    folder = (Path(root).resolve() / 'outputs' / 'system' / run_id).resolve()
    if not folder.is_relative_to((Path(root).resolve()/'outputs'/'system').resolve()):
        raise PolicyError('BACKTEST_PATH_REJECTED', 'Outside the approved real-run archive')
    return folder


def _manifest(root, run_id):
    folder = _allowed_run(root, run_id)
    try:
        meta = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    except (ValueError, OSError):
        raise PolicyError('BACKTEST_MANIFEST_UNAVAILABLE', 'Verified run manifest not found') from None
    if (not isinstance(meta, dict) or meta.get('run_id') != run_id
            or meta.get('stage') != 'P5'
            or meta.get('status') != RUN_STATUS
            or str(meta.get('source')).upper() != 'ALPACA'
            or meta.get('mode') != 'strict'
            or meta.get('research_grade') is not True
            or meta.get('historical_decision_eligible') is not True
            or meta.get('real_orders_enabled') is not False
            or meta.get('sealed_test_used') is not False
            or not isinstance(meta.get('model_archive_sha256'),str)
            or not _SHA.fullmatch(meta['model_archive_sha256'])
            or not isinstance(meta.get('data_snapshot_sha256'),str)
            or not _SHA.fullmatch(meta['data_snapshot_sha256'])
            or 'SYNTH' in '|'.join(str(v) for v in meta.get('flags',[])).upper()):
        raise PolicyError('BACKTEST_RUN_NOT_VERIFIED','Run does not have strict real-source PIT research acceptance')
    hashes = meta.get('artifacts_sha256')
    if not isinstance(hashes,dict):
        raise PolicyError('BACKTEST_DIGEST_MISSING','Backtest artifact manifest lacks digests')
    for name in ('backtest_metrics.csv', 'report.html'):
        if name not in hashes:
            raise PolicyError('BACKTEST_DIGEST_MISSING','Required report/metrics SHA256 absent',[name])
    return folder,meta


def _file(folder, meta, name, max_bytes=20*1024*1024):
    if (not isinstance(name,str) or '/' in name or '\\' in name or name.startswith('.')
            or name not in meta['artifacts_sha256']):
        raise PolicyError('BACKTEST_ARTIFACT_REJECTED','Run artifact is not an approved hashed file')
    digest = meta['artifacts_sha256'][name]
    if not isinstance(digest,str) or not _SHA.fullmatch(digest):
        raise PolicyError('BACKTEST_DIGEST_INVALID','Invalid file digest')
    path=(folder / name).resolve()
    if not path.is_relative_to(folder) or not path.is_file() or path.stat().st_size > max_bytes:
        raise PolicyError('BACKTEST_FILE_UNAVAILABLE','Real report file missing or over size limit',[name])
    raw=path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise PolicyError('BACKTEST_FILE_CHANGED','Real report bytes do not match frozen SHA256',[name])
    return raw


def _csv(folder,meta,name,limit=2000):
    try:
        rows=list(csv.DictReader(_file(folder,meta,name).decode('utf-8-sig').splitlines()))
    except (UnicodeError,csv.Error):
        raise PolicyError('BACKTEST_CSV_INVALID','Verified result cannot be read as CSV') from None
    if len(rows)>500000:
        raise PolicyError('BACKTEST_ROWS_TOO_MANY','Source-backed result exceeds viewer safety limit')
    return rows[-limit:]


def verified_backtest(root,run_id,scenario=None):
    folder,meta=_manifest(root,run_id)
    metrics=_csv(folder,meta,'backtest_metrics.csv',limit=100)
    if not metrics or any(x.get('status') != RUN_STATUS for x in metrics):
        raise PolicyError('BACKTEST_METRICS_NOT_ACCEPTED','Every scenario needs an accepted real-data modeled-fill status')
    if (len(set(x['scenario'] for x in metrics)) != len(metrics)
            or not all(_SCENARIO.fullmatch(str(row.get('scenario'))) for row in metrics)):
        raise PolicyError('BACKTEST_SCENARIOS_INVALID','Unrecognized metrics scenario')
    if scenario and (not _SCENARIO.fullmatch(scenario) or scenario not in {x['scenario'] for x in metrics}):
        raise PolicyError('BACKTEST_SCENARIO_NOT_FOUND','Requested cost/horizon scenario is not in this run')
    chosen = scenario or metrics[0]['scenario']
    curve = _csv(folder,meta,chosen+'_curve.csv',limit=1500)
    trades = _csv(folder,meta,chosen+'_trades.csv',limit=500)
    return {
        'status':RUN_STATUS, 'run_id':run_id, 'source':'ALPACA',
        'strategy_version_id':meta.get('strategy_version_id'),
        'data_snapshot_sha256':meta['data_snapshot_sha256'],
        'model_archive_sha256':meta['model_archive_sha256'],
        'data_cutoff_utc':meta.get('data_cutoff_utc'),
        'scenarios':metrics,'selected_scenario':chosen,
        'curve_rows':curve,'trade_rows':trades,
        'curve_display_limit':1500,'trade_display_limit':500,
        'report_path':'outputs/system/'+run_id+'/report.html',
        'modeled_fills_not_real_broker_executions':True,
        'real_orders_enabled':False,'sealed_test_used':False,
    }


def list_verified_backtests(root,limit=15):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise PolicyError('BACKTEST_QUERY_INVALID','Result list limit must be 1–50')
    folder=Path(root).resolve()/'outputs/system'
    if not folder.is_dir():
        return {'status':'BLOCKED','code':'NO_ACCEPTED_REAL_BACKTEST','results':[],
                'real_orders_enabled':False}
    results=[]
    for path in sorted(folder.glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:500]:
        if len(results)>=limit:break
        try:
            _,meta=_manifest(root,path.parent.name)
            # Don't offer corrupted outputs as available; verify key metrics.
            _file(path.parent,meta,'backtest_metrics.csv')
        except (OSError,PolicyError):
            continue
        results.append({'run_id':meta['run_id'],'status':meta['status'],
                        'created_at_utc':meta.get('created_at_utc'),
                        'data_snapshot_sha256':meta['data_snapshot_sha256'],
                        'strategy_version_id':meta.get('strategy_version_id'),
                        'real_orders_enabled':False})
    return {'status':'VERIFIED_REAL_BACKTEST_LIST' if results else 'BLOCKED',
            'code':None if results else 'NO_ACCEPTED_REAL_BACKTEST',
            'results':results,'real_orders_enabled':False}
