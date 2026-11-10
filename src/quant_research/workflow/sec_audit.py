"""G3 index/fact provenance audit; source timestamps remain untrusted until verified."""
from collections import Counter
from datetime import datetime,timezone
import hashlib
import html
import json
from pathlib import Path
from uuid import uuid4

from quant_research.data.http import HttpCache
from quant_research.data.providers.sec import SECProvider
from quant_research.data.filing_candidates import fact_candidates
from quant_research.data.filing_store import put_candidates


def execute(args):
    output=args.output/str(uuid4());output.mkdir(parents=True)
    provider=SECProvider(HttpCache(args.data_dir/'raw',offline=args.offline))
    result={'stage':'G3','run_id':output.name,'source':'SEC','created_at_utc':datetime.now(timezone.utc).isoformat(),
            'research_grade':False,'execution_ready':False,'real_orders_enabled':False,
            'status':'PIT_PUBLICATION_BLOCKED','filing_start':'2017-01-01','filing_end':'2024-12-31','companies':[]}
    filings,facts=[],[]
    for cik in ('320193','789019'):
        item={'cik':cik}
        try:
            snapshots=provider.snapshots(cik)
            submission=next(s for s in snapshots if s['kind']=='submissions')
            companyfacts=next(s for s in snapshots if s['kind']=='companyfacts')
            history=provider.filing_history(submission)
            candidates=fact_candidates(companyfacts,history)
            filings.extend(history);facts.extend(candidates)
            item.update(status='INDEX_AND_CANDIDATES_VERIFIED_PIT_BLOCKED',filing_rows=len(history),fact_candidates=len(candidates),
                form_counts=dict(Counter(f['form'] for f in history)),history_pages=provider.history_page_evidence,
                current_sic=submission['payload'].get('sic'),sic_scope='CURRENT_SNAPSHOT_NOT_HISTORICAL',
                sic_source_hash=submission['raw_sha256'],historical_sic_eligible=False,
                facts_source_hash=companyfacts['raw_sha256'])
        except (ValueError,OSError) as exc:
            item.update(status='DATA_SOURCE_BLOCKED',error_code=getattr(exc,'code',type(exc).__name__),
                        reason=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        result['companies'].append(item)
    for name,data in [('filings',filings),('fact_candidates',facts)]:
        (output/f'{name}.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    result['filing_rows']=len(filings);result['fact_candidate_rows']=len(facts)
    result['storage']=put_candidates(args.db,filings,facts,args.data_dir/'raw')
    result['eligible_pit_fact_rows']=0
    result['blocking_evidence']=['original filing body and acceptance header','verified timestamp timezone','as-filed numeric verification',
                                 'historical SIC with filing provenance','stable issuer/share-class identity bridge']
    package=Path(__file__).resolve().parents[1]
    result['code_sha256']=hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes() for p in sorted(package.rglob('*.py')))).hexdigest()
    result['input_sha256']={n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in ('filings.json','fact_candidates.json')}
    page='<!doctype html><meta charset="utf-8"><title>G3 SEC披露证据审计</title><h1>SEC申报索引与财务候选审计</h1><p>候选财务值不是已验证历史PIT值；原稿/接受时间尚未核验，全部禁止进入历史决策。当前SIC不回填历史。</p><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2))+'</pre>'
    (output/'report.html').write_text(page,encoding='utf-8')
    result['artifacts_sha256']={n:hashlib.sha256((output/n).read_bytes()).hexdigest() for n in ('filings.json','fact_candidates.json','report.html')}
    (output/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({'output':str(output.resolve()),'filings':len(filings),'fact_candidates':len(facts),'status':result['status']}),flush=True)
    return 4
