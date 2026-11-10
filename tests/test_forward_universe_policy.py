"""REAL_ONLY forward-as-of guards. No generated prices, assets or market fixtures."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from quant_research.data.forward_universe import (
    _asof, asof_directory, observation_changes, resolve_symbols,
)
from quant_research.policy import PolicyError


def test_no_archive_cannot_create_historical_membership(tmp_path):
    for run in (
        lambda: asof_directory(tmp_path),
        lambda: observation_changes(tmp_path),
        lambda: resolve_symbols(tmp_path, ['AAPL']),
    ):
        with pytest.raises(PolicyError) as info:
            run()
        assert info.value.code == 'NO_REAL_ASSET_OBSERVATION'
    assert not (tmp_path / 'data').exists()


def test_asof_must_be_exact_observed_time_not_unzoned_or_future():
    invalid = ('2026-11-09', '2026-11-09T12:00:00', 'yesterday', '', None, 42)
    for value in invalid:
        if value is None:
            continue  # Deliberate default: inspection at actual current UTC.
        with pytest.raises(PolicyError):
            _asof(value)
    with pytest.raises(PolicyError) as info:
        _asof((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    assert info.value.code == 'ASSET_ASOF_IN_FUTURE'


def test_filter_and_symbol_contract_reject_ambiguous_intent(tmp_path):
    for query in ({'q': 'X'*65}, {'limit':101},{'limit':-1},{'offset':-1},
                  {'state':'PIT_VERIFIED'},{'state':'investable'}):
        with pytest.raises(PolicyError) as info:
            asof_directory(tmp_path, **query)
        assert info.value.code == 'ASSET_QUERY_INVALID'
    for tickers in ([], ['aapl'], ['AAPL','AAPL'], ['AAPL,MSFT'],
                    ['AAPL','BAD/SYMBOL'], ['X'*30], ['AAPL']*101):
        with pytest.raises(PolicyError) as info:
            resolve_symbols(tmp_path, tickers)
        assert info.value.code == 'ASSET_SYMBOLS_INVALID'
    for limit in (0,-1,101,1.5):
        with pytest.raises(PolicyError) as info:
            observation_changes(tmp_path, limit=limit)
        assert info.value.code == 'ASSET_QUERY_INVALID'


def test_malicious_latest_pointer_never_grants_universe(tmp_path):
    folder=tmp_path/'data/managed/asset_observations'
    folder.mkdir(parents=True)
    (folder/'latest.json').write_text(json.dumps({
        'schema':'ALPACA_ASSETS_OBSERVED_V1', 'snapshot_id':'e'*64,
    }),encoding='utf-8')
    with pytest.raises(PolicyError) as info:
        asof_directory(tmp_path)
    assert info.value.code == 'ASSET_ARCHIVE_MISSING'


def test_existing_real_snapshot_only_when_available():
    root=Path.cwd()
    try:
        recent=asof_directory(root, state='candidate', limit=1)
    except PolicyError as exc:
        if exc.code=='NO_REAL_ASSET_OBSERVATION':
            pytest.skip('BLOCKED_NO_REAL_ALPACA_ASSET_SNAPSHOT')
        raise
    assert recent['snapshot_id'] and recent['raw_sha256']
    assert recent['capabilities']['historical_pit_universe'].startswith('BLOCKED_')
    assert recent['capabilities']['current_stock_only_universe'].startswith('BLOCKED_')
    assert not recent['real_orders_enabled']
    for item in recent['assets']:
        assert not item['stock_vs_etf_verified']
        assert not item['historical_pit_eligible']
        assert not item['trading_signal_eligible']
    history=observation_changes(root,limit=1)
    assert history['snapshot_count']>=1
    assert not history['historical_pit_eligible']


def test_source_observation_selection_never_looks_ahead(monkeypatch):
    """Only timestamp comparisons; no securities/prices or fake asset payloads."""
    from quant_research.data import forward_universe as universe
    earlier=datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    later=datetime(2026, 1, 6, 10, tzinfo=timezone.utc)
    snapshots=[{'observed_at':later,'snapshot_id':'later'},
               {'observed_at':earlier,'snapshot_id':'earlier'}]
    monkeypatch.setattr(universe,'_observations',lambda _:snapshots)
    with pytest.raises(PolicyError) as info:
        universe._select(Path.cwd(), earlier-timedelta(seconds=1))
    assert info.value.code == 'NO_ASOF_ASSET_EVIDENCE'
    selected, age, _=universe._select(Path.cwd(),earlier+timedelta(seconds=1))
    assert selected['snapshot_id']=='earlier'
    assert 0<age<1