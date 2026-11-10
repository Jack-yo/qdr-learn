"""Single-writer, restartable real-source maintenance; never runs models or trades."""
from datetime import datetime,timezone,timedelta
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID,uuid4

import yaml

from quant_research.clock import TradingClock
from quant_research.policy import PolicyError
from quant_research.data.catalog import write_catalog
from quant_research.data.http import HttpCache,atomic_write
from quant_research.data.providers.alpaca import AlpacaProvider
from quant_research.data.providers.actions import ActionProvider
from quant_research.data.providers.french import FrenchProvider
from quant_research.data.event_store import put_events
from quant_research.data.store import Warehouse,duckdb
from quant_research.data.quality import audit
from quant_research.data.pipeline import month_ranges
from .operation_lock import operation_lock


def resolve_end(clock,end):
    if end!='auto':clock.signal(end);return end
    now=datetime.now(timezone.utc)
    eligible=[s for s in clock.calendar.sessions if clock.close(s)+timedelta(minutes=20)<=now]
    if not eligible:raise ValueError('No completed delayed-SIP session')
    return str(eligible[-1].date())


def price_start(database,settings,end,full,clock):
    start=settings['start']
    if full or not database.is_file():return start
    with duckdb.connect(str(database),read_only=True) as db:
        rows=db.execute("SELECT symbol,max(date) FROM prices_daily WHERE source='ALPACA' AND feed='sip' AND adjustment_basis='raw' GROUP BY symbol").fetchall()
    dates=dict(rows)
    if any(s not in dates for s in settings['symbols']):return start
    latest=min(dates[s] for s in settings['symbols'])
    sessions=clock.calendar.sessions
    import pandas as pd
    anchor=min(pd.Timestamp(latest),pd.Timestamp(end))
    i=sessions.get_loc(anchor);offset=settings['overlap_sessions']
    if type(offset) is not int or not 1<=offset<=252:raise ValueError('Overlap must be 1..252 sessions')
    return max(start,str(sessions[max(0,i-offset+1)].date()))


def execute(args):
    root=Path.cwd().resolve();config=yaml.safe_load(args.config.read_text(encoding='utf-8'))
    if config.get('version')!=1 or config['prices']['source']!='alpaca' or config['prices']['feed']!='sip':
        raise ValueError('Only reviewed Alpaca SIP maintenance profile supported')
    groups=args.groups.split(',') if args.groups else config['cadence'][args.cadence]
    if len(groups)!=len(set(groups)) or set(groups)-{'prices','actions','french','sec'}:raise ValueError('Invalid maintenance groups')
    clock=TradingClock();end=resolve_end(clock,args.end)
    run_id = str(UUID(args.run_id)) if getattr(args, "run_id", None) else str(uuid4())
    with operation_lock(root, "maintenance", "maintenance", run_id) as ownership:
        output=root/'outputs/maintenance'/run_id;output.mkdir(parents=True)
        result={'run_id':output.name,'created_at_utc':datetime.now(timezone.utc).isoformat(),'end':end,'offline':args.offline,
                'config_sha256':hashlib.sha256(args.config.read_bytes()).hexdigest(),'tasks':[],
                'status':'RUNNING','operation_token':ownership['token'],'recovered_lock':ownership['recovered_lock'],
                'policy':'REAL_ONLY','research_grade':False,'execution_ready':False,'real_orders_enabled':False}
        package=Path(__file__).resolve().parents[1]
        result['code_sha256']=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest()
        http=HttpCache(root/'data/raw',offline=args.offline,refresh=not args.offline)
        atomic_write(output/'manifest.json',json.dumps(result,indent=2,ensure_ascii=False).encode())
        for group in groups:
            item={'group':group,'source':{'prices':'ALPACA','actions':'ALPACA','french':'KEN_FRENCH','sec':'SEC'}[group],
                  'status':'RUNNING'};result['tasks'].append(item)
            atomic_write(output/'manifest.json',json.dumps(result,indent=2,ensure_ascii=False).encode())
            try:
                if group=='prices':
                    db=root/'data/real_v21.duckdb';start=price_start(db,config['prices'],end,args.full,clock)
                    count=0
                    with Warehouse(db) as store:
                        provider=AlpacaProvider(clock,http,'sip')
                        for first,last in month_ranges(start,end):
                            count+=store.put_prices(provider.bars(config['prices']['symbols'],first,last),clock)
                        report=audit(store,clock,config['prices']['symbols'],start,end,'ALPACA','sip')
                    (output/'prices_audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                    item.update(status='UPDATED' if report['coverage_complete'] else 'BLOCKED',inserted_rows=count,
                                start=start,rows=report['rows'],missing_sessions=report['missing_sessions'],database='data/real_v21.duckdb')
                elif group=='actions':
                    provider=ActionProvider(http);events=provider.events(config['prices']['symbols'],config['actions']['start'],end)
                    db=root/'data/managed/corporate_actions/events.duckdb'
                    count=put_events(db,events,root/'data/raw')
                    folder=root/'data/managed/corporate_actions/snapshots';folder.mkdir(parents=True,exist_ok=True)
                    raw=json.dumps(events,sort_keys=True,ensure_ascii=False).encode();digest=hashlib.sha256(raw).hexdigest()
                    atomic_write(folder/(digest+'.json'),raw)
                    item.update(status='UPDATED',rows=len(events),inserted_rows=count,pages=provider.pages,
                                database=db.relative_to(root).as_posix(),snapshot_sha256=digest,use_policy='EVENT_EVIDENCE_NOT_ACCEPTED_LEDGER')
                elif group=='french':
                    db=root/'data/managed/classic_factors/factors.duckdb';counts={};added=0
                    with Warehouse(db) as store:
                        for dataset in config['french']['datasets']:
                            records=FrenchProvider(http).factors(dataset);counts[dataset]=len(records)
                            added+=store.insert_rows('factor_returns',[r.model_dump() for r in records])
                    item.update(status='UPDATED',datasets=counts,inserted_rows=added,database=db.relative_to(root).as_posix(),use_policy='ATTRIBUTION_ONLY')
                    # The same maintenance process owns the lock; the factor write connection is closed.
                    try:
                        from quant_research.workflow.styles import execute as style_execute
                        code=style_execute(SimpleNamespace(asof=None,cutoff=None,mode='observation',start='2017-01-03',output=root/'outputs/styles'))
                        item['style_monitor_status']='GENERATED' if code==0 else 'PARTIAL_DATA_BLOCKED'
                    except Exception as exc:
                        item['style_monitor_status']='BLOCKED'
                        item['style_monitor_error']=getattr(exc,'code',type(exc).__name__)
                else:
                    # Reuse source verification and the isolated candidate store; no PIT promotion.
                    if config['sec']['ciks']!=['320193','789019']:raise ValueError('SEC candidate pipeline currently validates AAPL/MSFT scope only')
                    from quant_research.workflow.sec_audit import execute as sec_execute
                    sec_args=SimpleNamespace(output=output/'sec',data_dir=root/'data',db=root/'data/g3_evidence.duckdb',offline=args.offline)
                    sec_execute(sec_args)
                    path=next((output/'sec').glob('*/manifest.json'));manifest=json.loads(path.read_text())
                    ok=all(c['status']=='INDEX_AND_CANDIDATES_VERIFIED_PIT_BLOCKED' for c in manifest['companies'])
                    item.update(status='UPDATED' if ok else 'BLOCKED',rows=manifest['filing_rows'],candidates=manifest['fact_candidate_rows'],
                                database='data/g3_evidence.duckdb',evidence_manifest=path.relative_to(root).as_posix(),use_policy='NOT_HISTORICAL_PIT')
            except Exception as exc:
                # Keep the next independent source running; no message may contain credential values.
                item.update(status='BLOCKED',code=getattr(exc,'code',type(exc).__name__))
            atomic_write(output/'manifest.json',json.dumps(result,indent=2,ensure_ascii=False).encode())
            print(json.dumps(item,ensure_ascii=False),flush=True)
        catalog,_=write_catalog(root,maintenance_owner=True)
        result.update(status='MAINTAINED' if all(t['status']=='UPDATED' for t in result['tasks']) else 'PARTIAL_BLOCKED',
                      catalog_snapshot=catalog.relative_to(root).as_posix(),finished_at_utc=datetime.now(timezone.utc).isoformat())
        result['artifacts_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.json') if p.name!='manifest.json'}
        atomic_write(output/'manifest.json',json.dumps(result,indent=2,ensure_ascii=False).encode())
        print(json.dumps({'output':str(output),'status':result['status'],'catalog':str(catalog)}),flush=True)
        return 0 if result['status']=='MAINTAINED' else 4
