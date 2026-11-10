"""Accession-linked fact candidates. Never backdate the current aggregate vintage."""
import math
import hashlib
import re
from .http import DataUnavailable

CONCEPTS=('Assets','StockholdersEquity','NetIncomeLoss','NetCashProvidedByUsedInOperatingActivities','CommonStockSharesOutstanding')


def fact_candidates(snapshot,filings):
    if any(int(f['cik'])!=int(snapshot['cik']) for f in filings):raise DataUnavailable('Filing issuer mismatch')
    index={f['accession']:f for f in filings}
    output=[]
    for name in CONCEPTS:
        concept=snapshot['payload']['facts'].get('us-gaap',{}).get(name,{})
        for unit,values in concept.get('units',{}).items():
            for source_index,item in enumerate(values):
                filing=index.get(item.get('accn'))
                if not filing or filing['form'] not in ('10-K','10-Q','10-K/A','10-Q/A'):continue
                value=item.get('val')
                if not isinstance(value,(int,float)) or not math.isfinite(value):raise DataUnavailable('Non-finite financial candidate')
                output.append({'cik':snapshot['cik'],'accession':item['accn'],'concept':name,'unit':unit,
                    'candidate_id':hashlib.sha256(f"{snapshot['raw_sha256']}:{name}:{unit}:{source_index}".encode()).hexdigest(),
                    'source_record_index':source_index,'fiscal_year':item.get('fy'),'fiscal_period':item.get('fp'),
                    'value':value,'period_start':item.get('start'),'period_end':item['end'],
                    'filed_date':item.get('filed'),'form':item.get('form'),'frame':item.get('frame'),
                    'available_at_historical_utc':None,'decision_eligible':False,
                    'source_kind':'CURRENT_AGGREGATE_CANDIDATE_NOT_VERIFIED_AS_FILED',
                    'facts_source_hash':snapshot['raw_sha256'],'filing_index_hash':filing['source_hash']})
    return output


def require_verified_publication(filing,decision_at):
    from quant_research.policy import PolicyError
    from quant_research.clock import utc
    if (filing.get('source_version_kind')!='documented_original_filing'
        or not re.fullmatch(r'[a-f0-9]{64}',str(filing.get('original_filing_hash','')))
        or filing.get('accepted_at_verified_utc') is None or filing.get('available_at_historical_utc') is None):
        raise PolicyError('PUBLICATION_TIME_UNVERIFIED','Original filing acceptance and availability evidence required')
    from datetime import datetime
    if utc(datetime.fromisoformat(filing['available_at_historical_utc']))>utc(decision_at):
        raise PolicyError('FUTURE_FILING_REJECTED','Filing was not available at the decision time')
