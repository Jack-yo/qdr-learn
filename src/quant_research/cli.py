"""Daily US equity research and local paper simulation. Real orders are disabled."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import logging
import platform
from pathlib import Path
import time
from uuid import uuid4

from .clock import TradingClock
from .contracts import Observation, require_asof
from .policy import SYMBOLS, PolicyError, require_real_source


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def load_local_credentials(path):
    import os
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
        key,value=line.split('=',1)
        if key.strip() in ('ALPACA_API_KEY','ALPACA_SECRET_KEY'):
            os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    labrun=commands.add_parser('factor-lab-run',help='Run one frozen real-data exploratory factor experiment')
    labrun.add_argument('--experiment-id',required=True)
    labcreate=commands.add_parser('factor-lab-create',help='Create an immutable template version and an unrun experiment')
    labcreate.add_argument('--definition',type=Path,required=True)
    labcreate.add_argument('--source',choices=['yahoo','alpaca'],required=True)
    styles=commands.add_parser('style-report',help='Source-reconciled French monitoring; descriptive only, never trades')
    styles.add_argument('--asof')
    styles.add_argument('--cutoff')
    styles.add_argument('--mode',choices=['observation','research'],default='observation')
    styles.add_argument('--start',default='2017-01-03')
    styles.add_argument('--output',type=Path,default=Path('outputs/styles'))
    commands.add_parser('data-catalog',help='Build a categorized real-data inventory and hash-verified cache index')
    close_snapshot=commands.add_parser('close-snapshot',help='Freeze verified local SIP observations before the next open')
    close_snapshot.add_argument('--asof',help='XNYS session; defaults to the latest ready session')
    observation = commands.add_parser('daily-observation', help='Report verified frozen SIP observations')
    observation.add_argument('--asof', help='Read an exact archived session; defaults to the latest ready session')
    commands.add_parser('paper-status', help='Inspect forward evidence without opening a paper account')
    daily_ops = commands.add_parser('daily-ops', help='Run the reviewed SIP daily sequence inside the actual close window')
    daily_ops.add_argument('--offline', action='store_true')
    daily_ops.add_argument('--env-file', type=Path)
    commands.add_parser('ops-backup', help='Copy reviewed operational inputs into a verified local backup')
    ops_restore = commands.add_parser('ops-restore', help='Recover a backup into a new isolated directory')
    ops_restore.add_argument('--backup-id', required=True)
    assets_sync=commands.add_parser('assets-sync',help='Archive actual read-only Alpaca current US equity/ETF asset metadata, not historical PIT')
    assets_sync.add_argument('--endpoint',choices=['paper','live'],default='paper')
    assets_sync.add_argument('--offline',action='store_true',help='Verify existing real snapshot only; never create a new observation')
    assets_sync.add_argument('--env-file',type=Path,help='Optional local credentials file; do not commit')
    assets_status=commands.add_parser('assets-status',help='Verify and inspect latest source-hashed current asset directory')
    assets_status.add_argument('--q',default='')
    assets_status.add_argument('--status',choices=['all','active','inactive'],default='all')
    assets_status.add_argument('--tradable',choices=['all','true','false'],default='all')
    assets_status.add_argument('--limit',type=int,default=30)
    assets_status.add_argument('--offset',type=int,default=0)
    strategy_preflight=commands.add_parser('strategy-preflight',help='Check strict backtest evidence for a frozen version')
    strategy_preflight.add_argument('--strategy-version',required=True)
    maintain=commands.add_parser('maintain-data',help='Maintain classified free real datasets; never trains or trades')
    maintain.add_argument('--config',type=Path,default=Path('configs/data_maintenance.yaml'))
    maintain.add_argument('--cadence',choices=['daily','weekly'],default='daily')
    maintain.add_argument('--groups',help='Explicit subset: prices,actions,french,sec')
    maintain.add_argument('--end',default='auto')
    maintain.add_argument('--full',action='store_true',help='Replay/backfill configured history rather than overlapping recent prices')
    maintain.add_argument('--offline',action='store_true')
    maintain.add_argument('--env-file',type=Path)
    feature_prices=commands.add_parser('feature-price-audit',help='Audit split-only features against real SIP reference; never enables execution')
    feature_prices.add_argument('--env-file',type=Path)
    feature_prices.add_argument('--offline',action='store_true')
    feature_prices.add_argument('--issuer-documents',action='store_true',help='Also verify reviewed public issuer PDF cases')
    feature_prices.add_argument('--db',type=Path,default=Path('data/real_v21.duckdb'))
    feature_prices.add_argument('--data-dir',type=Path,default=Path('data'))
    feature_prices.add_argument('--start',default='2017-01-03')
    feature_prices.add_argument('--asof')
    feature_prices.add_argument('--cutoff')
    feature_prices.add_argument('--action-start',default='2016-01-01')
    feature_prices.add_argument('--action-end',required=True,help='Explicit action process-date coverage end')
    feature_prices.add_argument('--output',type=Path,default=Path('outputs/feature_prices'))
    bundle=commands.add_parser('bundle-audit',help='Verify a real snapshot and report capability-specific blockers')
    bundle.add_argument('--source',choices=['alpaca','yahoo'],default='alpaca')
    bundle.add_argument('--db',type=Path,default=Path('data/real_v21.duckdb'))
    bundle.add_argument('--data-dir',type=Path,default=Path('data'))
    bundle.add_argument('--asof')
    bundle.add_argument('--cutoff',help='Timezone-aware knowledge cutoff, independent of observation date')
    bundle.add_argument('--output',type=Path,default=Path('outputs/g4'))
    sec=commands.add_parser('sec-audit',help='SEC full-history index and candidate facts; PIT remains gated')
    sec.add_argument('--offline',action='store_true')
    sec.add_argument('--data-dir',type=Path,default=Path('data'))
    sec.add_argument('--db',type=Path,default=Path('data/g3_evidence.duckdb'))
    sec.add_argument('--output',type=Path,default=Path('outputs/g3'))
    g2=commands.add_parser('g2-audit',help='Collect real corporate-event/identity cases; never enables execution')
    g2.add_argument('--env-file',type=Path)
    g2.add_argument('--offline',action='store_true')
    g2.add_argument('--data-dir',type=Path,default=Path('data'))
    g2.add_argument('--db',type=Path,default=Path('data/g2_evidence.duckdb'))
    g2.add_argument('--output',type=Path,default=Path('outputs/g2'))
    probe=commands.add_parser("provider-probe",help="Read-only real entitlement probe; never creates an account")
    probe.add_argument('--provider',choices=['alpaca','sec'],required=True)
    probe.add_argument('--offline',action='store_true')
    probe.add_argument('--env-file',type=Path,help='Explicit local Alpaca credential file; values never logged')
    probe.add_argument('--data-dir',type=Path,default=Path('data'))
    probe.add_argument('--output',type=Path,default=Path('outputs/g1'))
    acceptance = commands.add_parser("real-acceptance",help="Offline P1-P6 free real-data evidence; preserves research blockers")
    acceptance.add_argument("--db",type=Path,default=Path("data/research.duckdb"))
    acceptance.add_argument("--output",type=Path,default=Path("outputs/real_acceptance"))
    for name in ("ingest", "ingest-french", "ingest-sec", "data-audit"):
        item = commands.add_parser(name, help=f"P1 {name}: versioned data, no trading")
        item.add_argument("--db", type=Path, default=Path("data/research.duckdb"))
        item.add_argument("--data-dir", type=Path, default=Path("data"))
        item.add_argument("--output", type=Path, default=Path("outputs/ingestion"))
        item.add_argument("--sources-config", type=Path, default=Path("configs/sources.yaml"))
        item.add_argument("--offline", action="store_true", help="Use verified cache only; fail on cache miss")
        item.add_argument("--refresh", action="store_true", help="Fetch a new source vintage, retaining old raw responses")
        if name in ("ingest", "data-audit"):
            item.add_argument("--source", choices=["alpaca", "yahoo"], default="alpaca")
            item.add_argument("--feed", choices=["iex", "sip"], default="iex")
            item.add_argument("--symbols", default=",".join(SYMBOLS))
            item.add_argument("--start", required=True)
            item.add_argument("--end", required=True)
        if name == "ingest":
            item.add_argument('--env-file',type=Path)
            item.add_argument("--repair-gaps", action="store_true", help="One live retry pass for missing session dates")
        elif name == "ingest-french":
            item.add_argument("--datasets", default="ff5,momentum,reversal")
        elif name == "ingest-sec":
            item.add_argument("--ciks", default="320193,789019", help="Comma-separated CIKs (default Apple, Microsoft)")
        elif name == "data-audit":
            item.add_argument("--asof", help="Historical completed session: exclude data first observed later")
    for name in ("features","factor-report"):
        item = commands.add_parser(name,help="P2 causal factors and development-only diagnostics")
        item.add_argument("--source",choices=["yahoo","alpaca"],default="yahoo")
        item.add_argument("--mode",choices=["strict","retrospective"],default="strict")
        item.add_argument("--experiment",type=Path,default=Path("configs/experiments/p2_factors.yaml"))
        item.add_argument("--db",type=Path,default=Path("data/research.duckdb"))
        item.add_argument("--output",type=Path,default=Path("outputs/research"))
        item.add_argument("--start")
        item.add_argument("--end")
        item.add_argument("--asof",required=name=="features")
        item.add_argument("--horizons",default="1,3,5")
    for name in ("market-report","train-market","train","backtest","daily-report","paper-step","paper-replay","run-all","scheduled-run"):
        item = commands.add_parser(name,help="P3-P6 research/paper workflow, never real orders")
        item.add_argument("--source",choices=["yahoo","alpaca"],default="yahoo")
        item.add_argument("--mode",choices=["strict","retrospective"],default="strict")
        item.add_argument("--experiment",type=Path,default=Path("configs/experiments/baseline.yaml"))
        item.add_argument("--db",type=Path,default=Path("data/research.duckdb"))
        item.add_argument("--output",type=Path,default=Path("outputs/system"))
        item.add_argument("--asof")
        item.add_argument("--training-run",type=Path)
        item.add_argument("--state-db",type=Path,default=Path("data/paper.sqlite3"))
        item.add_argument("--symbols",help="Comma-separated explicit real research symbols, including SPY; does not imply a PIT historical universe")
    args = parser.parse_args(argv)
    try:
        if getattr(args,'env_file',None) and not getattr(args,'offline',False):
            if args.command != 'assets-sync' or args.env_file.is_file():
                load_local_credentials(args.env_file)
        if args.command=='factor-lab-create':
            from .research.factor_lab import Registry
            registry=Registry(Path.cwd());version=registry.create_factor(json.loads(args.definition.read_text(encoding='utf-8')))
            experiment=registry.create_experiment({'factor_version_id':version['id'],'source':args.source})
            print(json.dumps({'factor_version':version,'experiment':experiment},ensure_ascii=False))
            return 0
        if args.command=='factor-lab-run':
            from .workflow.factor_lab import run
            record=run(Path.cwd(),args.experiment_id)
            print(json.dumps(record,ensure_ascii=False))
            return 0 if record['status']=='COMPLETED' else 4
        if args.command=='style-report':
            from .workflow.styles import execute
            return execute(args)
        if args.command=='data-catalog':
            from .data.catalog import write_catalog
            output,data=write_catalog(Path.cwd())
            print(json.dumps({'output':str(output),'datasets':len(data['datasets']),'cache_hash_failures':data['cache_hash_failures']}))
            return 0 if not data['cache_hash_failures'] else 4
        if args.command=='close-snapshot':
            from .data.close_snapshot import execute
            return execute(args)
        if args.command == 'daily-observation':
            from .workflow.daily_observation import execute
            return execute(args)
        if args.command == 'paper-status':
            from .workflow.forward_observations import inventory
            print(json.dumps(inventory(Path.cwd())))
            return 0
        if args.command == 'daily-ops':
            from .workflow.daily_ops import execute
            return execute(args)
        if args.command in ('ops-backup', 'ops-restore'):
            from .workflow.ops_backup import execute
            return execute(args)
        if args.command in ('assets-sync','assets-status'):
            from .data.assets import inventory, sync
            if args.command=='assets-sync':
                result=sync(Path.cwd(),endpoint=args.endpoint,offline=args.offline)
            else:
                result=inventory(Path.cwd(),q=args.q,status=args.status,tradable=args.tradable,
                                 limit=args.limit,offset=args.offset)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='strategy-preflight':
            from .workflow.strategy_preflight import execute
            return execute(args)
        if args.command=='maintain-data':
            from .workflow.maintenance import execute
            return execute(args)
        if args.command=='feature-price-audit':
            from .workflow.feature_price_audit import execute
            return execute(args)
        if args.command=='bundle-audit':
            from .workflow.bundle_audit import execute
            return execute(args)
        if args.command=='sec-audit':
            from .workflow.sec_audit import execute
            return execute(args)
        if args.command in ("provider-probe","g2-audit"):
            if args.command=='g2-audit':
                from .workflow.g2 import execute
            else:
                from .data.probe import execute
            return execute(args)
        elif args.command == "real-acceptance":
            from .real_acceptance import run
            return run(args.db,args.output)
        elif args.command in ("features","factor-report"):
            from .research.pipeline import execute
            return execute(args)
        elif args.command in ("market-report","train-market"):
            from .workflow.market import execute
            return execute(args)
        elif args.command=="train":
            from .workflow.train import execute
            return execute(args)
        elif args.command=="backtest":
            from .workflow.backtest import execute
            return execute(args)
        elif args.command in ("daily-report","paper-step","paper-replay","run-all","scheduled-run"):
            from .workflow.daily import execute
            return execute(args)
        else:
            from .data.pipeline import execute
            return execute(args)
    except PolicyError as exc:
        print(json.dumps(exc.payload(),ensure_ascii=False))
        return 4
    except (ValueError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())