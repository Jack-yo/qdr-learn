"""Issuer PDF and decimal checks use actual hashed market/document responses."""
from copy import deepcopy
from pathlib import Path
import json
import shutil

import pytest

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.data.feature_prices import build_split_prices, split_reference, FeaturePrices, compare_reference
from quant_research.data.http import HttpCache, DataUnavailable
from quant_research.data.split_evidence import review_issuer_splits, precision_diagnostics


@pytest.fixture(scope='module')
def evidence():
    if not Path('data/real_v21.duckdb').is_file():
        pytest.skip('BLOCKED_REAL_WAREHOUSE_MISSING')
    bundle = load_real_bundle(Path('data/real_v21.duckdb'), asof='2026-11-06')
    http = HttpCache(Path('data/raw'), offline=True)
    try:
        features = build_split_prices(bundle,http,'2016-01-01','2026-11-06')
        reference,_ = split_reference(http,TradingClock(),bundle.metadata['symbols'],'2017-01-03','2026-11-06')
    except (DataUnavailable,FileNotFoundError) as exc:
        pytest.skip('BLOCKED_REAL_ACTION_CACHE: '+str(exc))
    return bundle,features,reference,http


def test_exact_decimal_diagnostic_explains_reference_without_enabling_execution(evidence):
    bundle,features,reference,http = evidence
    result = precision_diagnostics(bundle,features,reference,http.root)
    assert not result['vendor_rounding_guaranteed'] and not result['enables_any_capability']
    assert not result['changes_strict_tolerances']
    for field, count in [('open',449),('high',361),('low',358),('close',401)]:
        check = result['checks'][field]
        assert check['rows']==18510 and check['binary64_floor_x100_plus_half_div100_mismatches']==0
        assert check['decimal_quantizer_mismatches']['ROUND_HALF_UP']==count
        assert check['exact_max_absolute_error']=='0.0050'
    assert compare_reference(features,reference)['status']=='BLOCKED'
    assert bundle.capabilities['historical_backtest']['status']=='BLOCKED'


def test_real_issuer_originals_verify_eight_cases_without_pit_promotion(evidence):
    bundle,features,_,http = evidence
    result = review_issuer_splits(features,http,bundle.metadata['knowledge_cutoff_utc'])
    if any(d['status']=='BLOCKED' for d in result['documents'].values()):
        pytest.skip('BLOCKED_REAL_ISSUER_DOCUMENT_CACHE')
    assert result['matched_splits']==8 and result['requested_splits']==8 and result['status']=='CASE_FIELDS_MATCH'
    iwf = next(c for c in result['checks'] if c['symbol']=='IWF')
    assert iwf['status']=='CASE_FIELDS_MATCH' and iwf['matched_pages']==[1]
    assert result['documents']['ISHARES_APRIL']['format']=='SEC_ORIGINAL_HTML'
    assert not result['execution_accepted']
    assert all(not c['historical_publication_time_verified'] for c in result['checks'])
    assert all(d['raw_sha256'] and d['request_key'] for d in result['documents'].values())


def test_issuer_receipt_cutoff_rejects_later_document_observation(evidence):
    _,features,_,http = evidence
    result = review_issuer_splits(features,http,'2026-11-07T07:00:00+00:00')
    assert result['matched_splits']==0
    assert all(d['code']=='ISSUER_AFTER_CUTOFF' for d in result['documents'].values())


def test_mutated_actual_event_cannot_forge_independent_verification(evidence):
    bundle,features,_,http = evidence
    metadata = deepcopy(features.metadata)
    metadata['applied_splits'][0]['payload']['new_rate'] *= 2  # Fault injection only.
    altered = FeaturePrices(features.prices,metadata)
    with pytest.raises(ValueError,match='does not match'):
        review_issuer_splits(altered,http,bundle.metadata['knowledge_cutoff_utc'])


def test_issuer_path_scope_and_credential_forwarding_are_rejected():
    http = HttpCache(Path('data/raw'),offline=True)
    with pytest.raises(ValueError,match='reviewed public document'):
        http.get('https://www.ishares.com/unreviewed.pdf')
    with pytest.raises(ValueError,match='Credential forwarding'):
        http.get('https://www.ishares.com/us/literature/sai/sai-ishares-trust-3-31.pdf',
                 headers={'APCA-API-KEY-ID':'REJECTED_FAULT_INJECTION'})


def test_web_evidence_requires_matching_snapshot_and_all_artifact_hashes(evidence,tmp_path):
    from quant_research.web import feature_evidence
    bundle,_,_,_ = evidence
    manifests = sorted(Path('outputs/feature_prices').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    source = next((p for p in manifests if json.loads(p.read_text()).get('issuer_review')),None)
    if source is None:
        pytest.skip('BLOCKED_REAL_ISSUER_AUDIT_RUN_MISSING')
    manifest=json.loads(source.read_text())
    # The live warehouse can gain rows after this archived report was made.
    # Exercise its actual recorded snapshot identity instead of assuming the
    # current warehouse still has the same hash.
    archived={**bundle.metadata,'snapshot_sha256':manifest['raw_snapshot_sha256'],
              'asof_date_et':manifest['anchor_date_et']}
    target = tmp_path/'outputs/feature_prices'/source.parent.name
    shutil.copytree(source.parent,target)
    result = feature_evidence(tmp_path,archived)
    expected=manifest['issuer_review']
    assert result['strict_reference_status']=='BLOCKED' and result['issuer_matched']==expected['matched_splits']
    assert result['issuer_unverified_symbols']==[c['symbol'] for c in expected['checks'] if c['status']!='CASE_FIELDS_MATCH']
    assert not result['execution_enabled']
    stale = dict(archived)
    stale['snapshot_sha256']='REJECTED_STALE_SNAPSHOT'
    assert feature_evidence(tmp_path,stale)['code']=='NO_MATCHING_FEATURE_EVIDENCE'
    (target/'issuer_checks.json').write_text('tampered audit')
    assert feature_evidence(tmp_path,archived)['code']=='FEATURE_EVIDENCE_ARTIFACT_HASH_MISMATCH'
