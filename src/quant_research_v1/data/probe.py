"""Read-only provider proof. Never claims an entitlement from documentation."""
from datetime import datetime,timezone
import json
import os
import re
from pathlib import Path

from quant_research.clock import TradingClock
from .http import HttpCache,DataUnavailable
from .providers.alpaca import AlpacaProvider
from .providers.sec import SECProvider


def execute(args):
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    proof={'provider':args.provider,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
           'plan_verified':False,'status':'DATA_SOURCE_BLOCKED','real_records_processed':0,
           'evidence':[],'missing_evidence':[],'real_orders_enabled':False}
    http=HttpCache(args.data_dir/'raw',offline=args.offline,refresh=not args.offline)
    try:
        if args.provider=='alpaca':
            if not args.offline and not all(os.environ.get(k) for k in ('ALPACA_API_KEY','ALPACA_SECRET_KEY')):
                raise DataUnavailable('Configure ALPACA_API_KEY and ALPACA_SECRET_KEY locally; do not send keys in chat','MISSING_CREDENTIALS')
            provider=AlpacaProvider(TradingClock(),http,feed='sip',page_limit=2)
            # Short, explicit entitlement samples; not a full-history coverage claim.
            for start,end in [('2017-01-03','2017-01-06'),('2020-08-28','2020-09-01'),('2024-11-29','2024-11-29')]:
                records=provider.bars(['SPY','AAPL'],start,end)
                proof['real_records_processed']+=len(records)
                proof['evidence'].append({'start':start,'end':end,'feed':'sip','adjustment':'raw','rows':len(records),'pages':provider.last_page_count,'raw_sha256':sorted({r.raw_sha256 for r in records})})
            headers={'APCA-API-KEY-ID':os.environ.get('ALPACA_API_KEY',''),'APCA-API-SECRET-KEY':os.environ.get('ALPACA_SECRET_KEY','')}
            action=http.get('https://data.alpaca.markets/v1/corporate-actions',
                {'symbols':'AAPL','start':'2020-08-01','end':'2020-09-30','limit':1000},headers=headers)
            payload=json.loads(action.body)
            proof['evidence'].append({'endpoint_kind':'corporate_actions','raw_sha256':action.sha256,
                'response_keys':sorted(payload.keys()),'historical_completeness':'UNVERIFIED'})
            proof['status']='SAMPLE_ACCESS_VERIFIED_FULL_COVERAGE_PENDING'
            proof['missing_evidence']=['20-symbol full coverage','corporate-actions entitlement','latest complete session','delisted/identity cases']
        else:
            provider=SECProvider(http)
            snapshots=provider.snapshots('320193')
            for item in snapshots:
                proof['evidence'].append({'endpoint_kind':item['kind'],'cik':item['cik'],'raw_sha256':item['raw_sha256'],'retrieved_at_utc':item['fetched_at'].isoformat(),'grade':'CURRENT_SNAPSHOT_NOT_PIT'})
                proof['real_records_processed']+=1
            proof['status']='SNAPSHOT_ACCESS_VERIFIED_PIT_PENDING'
            proof['missing_evidence']=['original filings','historical submissions pagination','accepted-time validation','historical facts/industry']
            submission=next(x for x in snapshots if x['kind']=='submissions')['payload']
            headers={'User-Agent':provider.user_agent,'Accept':'application/json'}
            older=submission.get('filings',{}).get('files',[])
            if older:
                name=older[0]['name']
                if not re.fullmatch(r'CIK[0-9]+-submissions-[0-9]+\.json',name):
                    raise DataUnavailable('Unexpected historical submissions filename')
                raw=http.get('https://data.sec.gov/submissions/'+name,headers=headers)
                history=json.loads(raw.body)
                proof['evidence'].append({'endpoint_kind':'historical_submissions','raw_sha256':raw.sha256,'records':len(history.get('accessionNumber',[]))})
            recent=submission['filings']['recent']
            candidates=[i for i,f in enumerate(recent['form']) if f=='10-K' and recent['filingDate'][i]<'2025-01-01']
            if candidates:
                i=candidates[0];accession=recent['accessionNumber'][i];document=recent['primaryDocument'][i]
                if not re.fullmatch(r'[0-9-]+',accession) or '/' in document or '..' in document:
                    raise DataUnavailable('Unexpected filing path')
                url=f'https://www.sec.gov/Archives/edgar/data/320193/{accession.replace("-","")}/{document}'
                raw=http.get(url,headers=headers)
                proof['evidence'].append({'endpoint_kind':'original_10K','accession':accession,'endpoint':url,'raw_sha256':raw.sha256,'bytes':len(raw.body),'accepted_time_status':'UNVERIFIED_NOT_PIT'})
            proof['status']='SEC_SOURCE_ACCESS_VERIFIED_PIT_PENDING'
    except (DataUnavailable,OSError,ValueError) as exc:
        proof['error_code']=getattr(exc,'code','SOURCE_VALIDATION_FAILED')
        proof['error']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
    (output/f'{args.provider}_provider_proof.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)
    return 4 if proof['status']=='DATA_SOURCE_BLOCKED' else 0
