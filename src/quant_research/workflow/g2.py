"""G2 bounded real evidence audit. Never enables execution or invents holdings."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import html
import json
from uuid import uuid4
from pathlib import Path

from quant_research.clock import TradingClock
from quant_research.data.http import HttpCache
from quant_research.data.providers.actions import ActionProvider
from quant_research.data.providers.alpaca import AlpacaProvider
from quant_research.data.event_store import put_events
from quant_research.data.store import Warehouse
from quant_research.data.event_review import review
from quant_research.data.identity_evidence import rename_candidates

CASES=[('AAPL_SPLIT_DIVIDEND',['AAPL'],'2020-08-01','2020-09-30'),
       ('GE_REVERSE',['GE'],'2021-07-01','2021-08-31'),
       ('META_RENAME',['FB','META'],'2022-05-01','2022-07-31'),
       ('TWTR_ACQUISITION',['TWTR'],'2022-10-01','2022-11-30')]
SOURCES={
 'APPLE':'https://www.apple.com/newsroom/2020/07/apple-reports-third-quarter-results/',
 'GE':'https://www.ge.com/news/press-releases/ge-completes-one-for-eight-reverse-stock-split',
 'NASDAQ_META':'https://www.nasdaqtrader.com/TraderNews.aspx'}


def execute(args):
    output=args.output/str(uuid4());output.mkdir(parents=True)
    http=HttpCache(args.data_dir/'raw',offline=args.offline)
    result={'stage':'G2','run_id':output.name,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
            'source':'ALPACA','status':'EVIDENCE_AUDIT_PENDING','real_orders_enabled':False,
            'research_grade':False,'execution_ready':False,'cases':[],'external_sources':[],
            'identity_status':'UNVERIFIED_NO_PERMANENT_MASTER','universe_status':'HISTORICAL_MEMBERSHIP_MISSING',
            'delisting_settlement_status':'NOT_ACCEPTED','source_version_kind':'current_revised_snapshot'}
    package=Path(__file__).resolve().parents[1]
    result['code_sha256']=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest()
    result['config_sha256']=hashlib.sha256(json.dumps(CASES,sort_keys=True).encode()).hexdigest()
    all_events=[]
    for name,symbols,start,end in CASES:
        item={'case':name,'symbols':symbols,'process_date_start':start,'process_date_end':end}
        try:
            provider=ActionProvider(http,limit=1)
            events=provider.events(symbols,start,end)
            item.update(status='EVENTS_RETRIEVED' if events else 'BLOCKED_NO_EVENTS',events=len(events),pages=provider.pages,
                        types=dict(Counter(e['event_type'] for e in events)),inserted_versions=put_events(args.db,events,args.data_dir/'raw'))
            all_events.extend(events)
        except (ValueError,OSError) as exc:
            item.update(status='BLOCKED',error_code=getattr(exc,'code',type(exc).__name__),reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        result['cases'].append(item)
    result['raw_bar_cases']=[]
    for symbols,start,end in [(['AAPL'],'2020-08-28','2020-09-01'),(['GE'],'2021-07-30','2021-08-03'),
                              (['FB','META'],'2022-06-08','2022-06-10'),(['ABNB'],'2020-12-07','2020-12-15'),
                              (['TWTR'],'2022-10-24','2022-11-02')]:
        item={'symbols':symbols,'start':start,'end':end}
        try:
            provider=AlpacaProvider(TradingClock(),http,'sip',page_limit=2)
            bars=provider.bars(symbols,start,end)
            with Warehouse(args.db) as db: inserted=db.put_prices(bars,TradingClock())
            item.update(status='REAL_BARS_RETRIEVED' if bars else 'BLOCKED_NO_BARS',rows=len(bars),pages=provider.last_page_count,
                        inserted=inserted,raw_sha256=sorted({b.raw_sha256 for b in bars}),
                        observed_first={s:min((str(b.date) for b in bars if b.symbol==s),default=None) for s in symbols})
        except (ValueError,OSError) as exc:
            item.update(status='BLOCKED',error_code=getattr(exc,'code',type(exc).__name__),
                        reason=str(exc)[:500] if isinstance(exc,ValueError) else type(exc).__name__)
        result['raw_bar_cases'].append(item)
    for name,url in SOURCES.items():
        try:
            raw=http.get(url,{'id':'ECA2022-125'} if name=='NASDAQ_META' else {},headers={'User-Agent':'QuantResearch/2.1 EvidenceAudit'})
            result['external_sources'].append({'name':name,'url':url,'status':'RETRIEVED_PENDING_CONTENT_REVIEW',
                'raw_sha256':raw.sha256,'bytes':len(raw.body),'retrieved_at_utc':raw.fetched_at.isoformat()})
        except (ValueError,OSError) as exc:
            result['external_sources'].append({'name':name,'url':url,'status':'BLOCKED','error_code':getattr(exc,'code',type(exc).__name__)})
    (output/'events.json').write_text(json.dumps(all_events,ensure_ascii=False,indent=2),encoding='utf-8')
    result['review']=review(all_events,result['external_sources'],args.data_dir/'raw')
    identities=rename_candidates(all_events,result['review'])
    (output/'identity_candidates.json').write_text(json.dumps(identities,indent=2),encoding='utf-8')
    result['rename_evidence_rows']=len(identities)
    result['events_sha256']=hashlib.sha256((output/'events.json').read_bytes()).hexdigest()
    result['data_sha256']=hashlib.sha256(json.dumps({'events':result['events_sha256'],'bars':result['raw_bar_cases'],
        'sources':result['external_sources']},sort_keys=True).encode()).hexdigest()
    result['status']='REAL_EVIDENCE_COLLECTED_G2_NOT_ACCEPTED' if all_events else 'DATA_SOURCE_BLOCKED'
    (output/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    page='<!doctype html><meta charset="utf-8"><title>G2真实事件证据审计</title><h1>G2真实事件证据审计</h1><p>观察样本不是历史股票池。事件来自当前版本；获取成功不等于身份/PIT/结算已验收。不产生持仓、成交或收益。</p><pre>'+html.escape(json.dumps(result,indent=2,ensure_ascii=False))+'</pre>'
    (output/'report.html').write_text(page,encoding='utf-8')
    result['artifacts_sha256']={name:hashlib.sha256((output/name).read_bytes()).hexdigest() for name in ('events.json','report.html','identity_candidates.json')}
    (output/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'output':str(output.resolve()),'events':len(all_events),'status':result['status']}),flush=True)
    return 4
