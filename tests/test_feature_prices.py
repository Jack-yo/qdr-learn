"""Actual SIP cache integration, fault injection, and scalar invariants only."""
from datetime import datetime, timezone
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_research.data.bundle import load_real_bundle, frame_hash, verify_lineage
from quant_research.data.feature_prices import build_split_prices, compare_reference, split_reference, TOLERANCES
from quant_research.data.http import HttpCache, DataUnavailable
from quant_research.clock import TradingClock
from quant_research.policy import PolicyError


def test_reference_refresh_cannot_claim_offline_source():
    from quant_research.workflow.feature_price_audit import execute
    with pytest.raises(ValueError, match='Offline audit cannot refresh'):
        execute(SimpleNamespace(offline=True, refresh_source_responses=True))


@pytest.fixture(scope='module')
def actual():
    if not Path('data/real_v21.duckdb').is_file():
        pytest.skip('BLOCKED_REAL_SIP_WAREHOUSE_MISSING')
    bundle = load_real_bundle(Path('data/real_v21.duckdb'), asof='2026-11-06')
    try:
        features = build_split_prices(bundle, HttpCache(Path('data/raw'), offline=True), '2016-01-01', '2026-11-06')
        reference, pages = split_reference(HttpCache(Path('data/raw'), offline=True), TradingClock(),
                                           bundle.metadata['symbols'], '2017-01-03', '2026-11-06')
    except (DataUnavailable, FileNotFoundError) as exc:
        pytest.skip('BLOCKED_REAL_ACTION_OR_REFERENCE_CACHE: '+str(exc))
    return bundle, features, reference


def test_full_real_feature_scope_and_raw_immutability(actual):
    bundle, features, _ = actual
    raw, adjusted = bundle.prices, features.prices
    assert len(adjusted) == 49520 and len(features.metadata['applied_splits']) == 8
    assert features.metadata['returned_events'] == 1042
    assert frame_hash(raw) == features.metadata['raw_snapshot_sha256']
    assert set(raw.adjustment_basis) == {'raw'}
    assert set(adjusted.adjustment_basis) == {'split_adjusted_price_proxy'}
    assert not features.metadata['execution_ready'] and not features.metadata['historical_decision_eligible']
    assert np.allclose(raw.close*raw.volume, adjusted.close*adjusted.volume, rtol=1e-12, atol=1e-6)
    assert (pd.to_datetime(adjusted.available_at, utc=True) >= pd.to_datetime(raw.available_at, utc=True)).all()
    with pytest.raises(PolicyError, match='Unknown raw'):
        verify_lineage(adjusted, Path('data/raw'))


def test_actual_split_date_boundary_and_cash_dividend_not_applied(actual):
    bundle, features, _ = actual
    raw, adjusted = bundle.prices, features.prices
    for event in features.metadata['applied_splits']:
        before = raw.symbol.eq(event['symbol']) & pd.to_datetime(raw.date).lt(pd.Timestamp(event['payload']['ex_date']))
        after = raw.symbol.eq(event['symbol']) & ~before
        assert adjusted.loc[before, 'split_price_multiplier'].eq(event['price_multiplier']).all()
        assert adjusted.loc[after, 'split_price_multiplier'].eq(1).all()
    spy = raw.symbol.eq('SPY')
    pd.testing.assert_series_equal(raw.loc[spy,'close'], adjusted.loc[spy,'close'])
    assert features.metadata['cash_dividends_excluded'] == 1034


def test_earlier_anchor_does_not_apply_known_future_splits(actual):
    bundle = load_real_bundle(Path('data/real_v21.duckdb'), asof='2024-12-31')
    features = build_split_prices(bundle, HttpCache(Path('data/raw'), offline=True), '2016-01-01', '2026-11-06')
    assert not features.metadata['applied_splits']
    assert features.prices.split_price_multiplier.eq(1).all()
    pd.testing.assert_series_equal(features.prices.close, bundle.prices.close)
    assert not features.metadata['historical_decision_eligible']
    from quant_research.features.context import make_context
    from quant_research.research.labels import make_labels
    # Only pre-2025 actual outcomes; final strategy test remains sealed.
    frame = features.prices
    frame = frame.loc[pd.to_datetime(frame.date).ge('2024-11-01')]
    context = make_context(frame, TradingClock(), 'SPY', '2024-11-01', '2024-12-31')
    labels = make_labels(context, TradingClock(), adjustment_basis='split_adjusted_price_proxy')
    assert labels.forward_return.isna().all() and labels.net_return.isna().all()
    valid = labels.loc[labels.proxy_forward_return.notna()]
    assert len(valid) > 0 and set(valid.horizon) == {1,3,5}
    assert pd.to_datetime(valid.exit_date).max() <= pd.Timestamp('2024-12-31')
    with pytest.raises(PolicyError, match='Raw OHLC alone'):
        make_labels(context, TradingClock(), adjustment_basis='raw')


def test_observed_actions_cannot_move_back_before_knowledge_cutoff(actual):
    bundle = load_real_bundle(Path('data/real_v21.duckdb'), asof='2026-11-06',
                              cutoff=datetime(2026,11,7,6,0,tzinfo=timezone.utc))
    with pytest.raises(PolicyError, match='after the requested knowledge cutoff'):
        build_split_prices(bundle, HttpCache(Path('data/raw'), offline=True), '2016-01-01', '2026-11-06')


def test_incomplete_action_query_cannot_claim_coverage(actual):
    with pytest.raises(PolicyError, match='must span'):
        build_split_prices(actual[0], HttpCache(Path('data/raw'), offline=True), '2020-01-01', '2026-11-06')
    with pytest.raises(PolicyError, match='must span'):
        build_split_prices(actual[0], HttpCache(Path('data/raw'), offline=True), '2016-01-01', '2024-12-31')


def test_actual_reference_discrepancy_remains_blocked_without_threshold_tuning(actual):
    _, features, reference = actual
    result = compare_reference(features, reference)
    assert result['status'] == 'BLOCKED'
    assert result['rows_compared'] == 49520 and result['unmatched_keys'] == 0
    assert result['checks']['volume']['mismatches'] == 0
    assert result['checks']['close']['mismatches'] == 11149
    assert result['checks']['close']['unadjusted_row_mismatches'] == 0
    assert result['checks']['close']['max_absolute_error'] == pytest.approx(0.005)
    assert TOLERANCES['price_atol'] == 0.0001


def test_missing_reference_row_cannot_pass_even_when_remaining_values_match(actual):
    result = compare_reference(actual[1], actual[2].iloc[1:])
    assert result['status'] == 'BLOCKED' and result['unmatched_keys'] == 1


def test_feature_copy_cannot_change_evidence(actual):
    features = actual[1]
    frame = features.prices
    frame.loc[frame.index[0], 'close'] += 1  # Fault injection only.
    assert frame_hash(frame) != features.metadata['feature_snapshot_sha256']
    assert frame_hash(features.prices) == features.metadata['feature_snapshot_sha256']


def test_missing_action_receipt_blocks_derived_features(actual, tmp_path):
    # Copy the two real action pages/pointers, deliberately omit receipts.
    root = tmp_path/'raw'
    (root/'objects').mkdir(parents=True); (root/'requests').mkdir()
    for page in actual[1].metadata['action_pages']:
        digest, key = page['raw_sha256'], page['request_key']
        shutil.copyfile(Path('data/raw/objects')/digest, root/'objects'/digest)
        shutil.copyfile(Path('data/raw/requests')/(key+'.json'), root/'requests'/(key+'.json'))
    with pytest.raises(PolicyError, match='immutable source receipt'):
        build_split_prices(actual[0], HttpCache(root, offline=True), '2016-01-01', '2026-11-06')
