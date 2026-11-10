"""Scoped symbol-change evidence; never synthesizes a historical security master."""
from datetime import date,datetime
import hashlib

from quant_research.clock import utc
from quant_research.policy import PolicyError


def rename_candidates(events,review):
    checks={c['event_id']:c for c in review['case_checks']}
    result=[]
    for event in events:
        if event['event_type']!='name_changes':continue
        check=checks[event['provider_event_id']]
        if check['status']!='CASE_FIELDS_MATCH':continue
        p=event['payload']
        effective=date.fromisoformat(p['process_date'])
        result.append({'relation_evidence_id':hashlib.sha256(event['provider_event_id'].encode()).hexdigest(),
            'old_symbol':p['old_symbol'],'new_symbol':p['new_symbol'],'old_cusip':p.get('old_cusip'),'new_cusip':p.get('new_cusip'),
            'effective_date':str(effective),'observed_at_utc':event['retrieved_at_utc'],
            'published_at_verified_utc':None,'provider_event_id':event['provider_event_id'],
            'provider_sha256':event['raw_sha256'],'independent_sha256':check['independent_sha256'],
            'scope':'DOCUMENTED_RENAME_RELATION_NOT_GLOBAL_SECURITY_ID','tradability_eligible':False})
    return result


def require_known_relation(relation,decision_at):
    if utc(datetime.fromisoformat(relation['observed_at_utc']))>utc(decision_at):
        raise PolicyError('IDENTITY_NOT_KNOWN_AT_DECISION','Later-observed identity evidence cannot be backfilled')
    if not relation.get('tradability_eligible'):
        raise PolicyError('IDENTITY_MASTER_INCOMPLETE','Rename evidence alone does not prove historical tradability')
