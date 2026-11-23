"""REAL_ONLY guard tests; no synthetic market or asset records are ever produced."""
from pathlib import Path
import json

import pytest

from quant_research.data.assets import (
    ENDPOINTS, _validate_payload, archive_response, inventory, sync, fetch_assets,
)
from quant_research.policy import PolicyError


def test_observed_us_equity_catalog_accepts_provider_numeric_leading_symbol():
    payload = [{
        'id': '5375e9fa-3ada-4ed2-a5fb-eb774fea22f4',
        'symbol': '98400U111', 'class': 'us_equity', 'status': 'active',
        'tradable': True, 'exchange': 'NYSE',
    }]
    assert _validate_payload(json.dumps(payload).encode()) == payload


def test_observed_us_equity_catalog_accepts_retained_provider_symbol():
    payload = [{
        'id': '5375e9fa-3ada-4ed2-a5fb-eb774fea22f4',
        'symbol': 'VEAC_DELISTED', 'class': 'us_equity', 'status': 'inactive',
        'tradable': False, 'exchange': 'NYSE',
    }]
    assert _validate_payload(json.dumps(payload).encode()) == payload


def test_unconfigured_api_never_fetches_or_fabricates(tmp_path, monkeypatch):
    monkeypatch.delenv('ALPACA_API_KEY', raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY', raising=False)
    with pytest.raises(PolicyError) as exc:
        fetch_assets()
    assert exc.value.code == 'MISSING_CREDENTIALS'
    with pytest.raises(PolicyError) as exc:
        sync(tmp_path, offline=True)
    assert exc.value.code == 'NO_REAL_ASSET_OBSERVATION'
    assert not (tmp_path / 'data').exists()


def test_unauthenticated_and_invalid_responses_are_never_archived(tmp_path):
    for body in [b'[]', b'{}', b'not-json', b'', b'[1]', b'[{"id":null}]']:
        with pytest.raises(PolicyError):
            archive_response(tmp_path, body, endpoint=ENDPOINTS['paper'],
                             observed_at_utc='2026-11-10T08:00:00+00:00')
    assert not (tmp_path / 'data').exists()


def test_reject_future_time_unknown_provider_and_invalid_query(tmp_path):
    with pytest.raises(PolicyError) as exc:
        archive_response(tmp_path, b'[]',endpoint=ENDPOINTS['paper'],
                         observed_at_utc='2099-01-01T00:00:00+00:00')
    assert exc.value.code == 'ASSET_OBSERVATION_TIME_INVALID'
    with pytest.raises(PolicyError) as exc:
        archive_response(tmp_path, b'[]',endpoint='https://untrusted.invalid/v2/assets',
                         observed_at_utc='2026-11-10T08:00:00+00:00')
    assert exc.value.code == 'ASSET_ENDPOINT_UNAPPROVED'
    for args in ({'q':'a'*65},{'status':'PIT_VERIFIED'},{'tradable':'yes'},
                 {'limit':101},{'offset':-1}):
        with pytest.raises(PolicyError) as exc:
            inventory(tmp_path, **args)
        assert exc.value.code == 'ASSET_QUERY_INVALID'


def test_pointer_change_cannot_create_a_verified_source(tmp_path):
    folder = tmp_path / 'data/managed/asset_observations'
    folder.mkdir(parents=True)
    (folder / 'latest.json').write_text(json.dumps({'schema':'ALPACA_ASSETS_OBSERVED_V1',
                                                   'snapshot_id':'f'*64}),encoding='utf-8')
    with pytest.raises(PolicyError) as exc:
        inventory(tmp_path)
    assert exc.value.code == 'ASSET_ARCHIVE_MISSING'
    (folder / 'latest.json').write_text('not-json', encoding='utf-8')
    with pytest.raises(PolicyError) as exc:
        inventory(tmp_path)
    assert exc.value.code == 'ASSET_ARCHIVE_TAMPERED'


def test_untrusted_pagination_and_identity_inputs_blocked(tmp_path):
    for endpoint in ('custom', '', None):
        with pytest.raises(PolicyError):
            fetch_assets(endpoint=endpoint)
    # A valid-looking response is not enough to pass historical model/backtest
    # checks: this module never writes PIT_VERIFIED into universe_daily and
    # never upgrades SYMBOL-UNVERIFIED historical bar identities.


def test_existing_genuine_asset_snapshot_if_available():
    project = Path.cwd()
    try:
        data = inventory(project,limit=1)
    except PolicyError as exc:
        if exc.code == 'NO_REAL_ASSET_OBSERVATION':
            pytest.skip('BLOCKED_NO_REAL_ALPACA_ASSET_SNAPSHOT')
        raise
    assert data['status']=='OBSERVED_CURRENT_CATALOG_NOT_HISTORICAL_PIT'
    assert data['returned_records'] > 0
    assert data['capabilities']['historical_universe'].startswith('BLOCKED_')
    assert data['capabilities']['issuer_identity'].startswith('BLOCKED_')
