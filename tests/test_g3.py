"""Real SEC/rename snapshots only; mutations are fault injection into real metadata."""
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
import json

import pytest

from quant_research.data.http import HttpCache,DataUnavailable
from quant_research.data.providers.sec import SECProvider
from quant_research.data.filing_candidates import fact_candidates,require_verified_publication
from quant_research.data.filing_store import put_candidates
from quant_research.policy import PolicyError


def real_sec(cik='320193'):
    provider=SECProvider(HttpCache(Path('data/raw'),offline=True))
    try:
        snapshots=provider.snapshots(cik)
        submission=next(s for s in snapshots if s['kind']=='submissions')
        facts=next(s for s in snapshots if s['kind']=='companyfacts')
        filings=provider.filing_history(submission)
    except (DataUnavailable,FileNotFoundError) as exc:pytest.skip('BLOCKED_SEC_REAL_CACHE: '+str(exc))
    return provider,submission,facts,filings


def test_all_advertised_history_pages_and_final_period_exclusion():
    provider,submission,_,filings=real_sec()
    assert len(provider.history_page_evidence)==1+len(submission['payload']['filings'].get('files',[]))
    assert len({f['accession'] for f in filings})==len(filings)
    assert all('2017-01-01'<=f['filed_date']<='2024-12-31' for f in filings)
    assert all(f['accepted_at_verified_utc'] is None and f['available_at_historical_utc'] is None for f in filings)
    assert sum(f['form']=='10-K' for f in filings)==8


def test_financial_candidates_exact_source_record_lineage():
    _,_,snapshot,filings=real_sec()
    candidates=fact_candidates(snapshot,filings)
    assert candidates and len({f['candidate_id'] for f in candidates})==len(candidates)
    for f in candidates:
        source=snapshot['payload']['facts']['us-gaap'][f['concept']]['units'][f['unit']][f['source_record_index']]
        assert (source['val'],source['accn'],source['end'])==(f['value'],f['accession'],f['period_end'])
        assert not f['decision_eligible'] and f['available_at_historical_utc'] is None


def test_quarter_end_and_z_suffix_do_not_prove_publication_time():
    _,_,_,filings=real_sec()
    filing=next(f for f in filings if f['form']=='10-K')
    # Actual fiscal period boundary is a real date, never a disclosure substitute.
    from datetime import timezone
    decision=datetime.fromisoformat(filing['period_end']).replace(tzinfo=timezone.utc)
    with pytest.raises(PolicyError,match='acceptance'):require_verified_publication(filing,decision)
    assert filing['accepted_time_source_text']
    forged=deepcopy(filing)
    forged['accepted_at_verified_utc']=forged['retrieved_at_utc']
    forged['available_at_historical_utc']=forged['retrieved_at_utc']
    with pytest.raises(PolicyError,match='evidence'):require_verified_publication(forged,datetime.fromisoformat(forged['retrieved_at_utc']))


def test_candidate_storage_idempotent_and_cannot_promote_eligibility(tmp_path):
    _,_,snapshot,filings=real_sec()
    facts=fact_candidates(snapshot,filings)
    path=tmp_path/'filings.duckdb'
    first=put_candidates(path,filings,facts)
    assert first['new_filing_versions']==len(filings) and first['new_financial_candidates']==len(facts)
    assert put_candidates(path,filings,facts)=={'new_filing_versions':0,'new_financial_candidates':0}
    invalid=deepcopy(facts[:1]);invalid[0]['decision_eligible']=True
    with pytest.raises(ValueError,match='promote'):put_candidates(path,filings,invalid)
    altered=deepcopy(facts[:1]);altered[0]['value']+=1
    with pytest.raises(ValueError,match='does not match'):put_candidates(path,filings,altered)


def test_cannot_join_another_issuer_to_financial_candidates():
    _,_,snapshot,_=real_sec()
    _,_,_,other=real_sec('789019')
    with pytest.raises(DataUnavailable,match='issuer mismatch'):fact_candidates(snapshot,other)


def test_rename_relationship_does_not_backfill_permanent_master():
    from quant_research.data.identity_evidence import rename_candidates,require_known_relation
    manifests=list(Path('outputs/g2').glob('*/manifest.json'))
    if not manifests:pytest.skip('BLOCKED_RENAME_SNAPSHOTS_UNAVAILABLE')
    data=json.loads(manifests[0].read_text(encoding='utf-8'))
    events=json.loads((manifests[0].parent/'events.json').read_text(encoding='utf-8'))
    review=data.get('review')
    if not review:
        from quant_research.data.event_review import review as review_cases
        review=review_cases(events,data['external_sources'],Path('data/raw'))
    relations=rename_candidates(events,review)
    assert len(relations)==1
    relation=relations[0]
    assert relation['old_symbol']=='FB' and relation['new_symbol']=='META' and relation['effective_date']=='2022-06-09'
    assert 'security_id' not in relation and not relation['tradability_eligible']
    observed=datetime.fromisoformat(relation['observed_at_utc'])
    with pytest.raises(PolicyError,match='Later-observed'):require_known_relation(relation,observed-timedelta(microseconds=1))
    with pytest.raises(PolicyError,match='tradability'):require_known_relation(relation,observed)
