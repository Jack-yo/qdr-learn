"""No fabricated market/event rows: admission and integrity checks only."""
import hashlib
import json
from pathlib import Path

import pytest

from quant_research.data.action_audit import (
    _audit_record, _event_day, _receipt_index, _safe_time, audit_events,
)
from quant_research.policy import PolicyError


def test_absent_real_source_is_blocked_not_empty_success(tmp_path):
    with pytest.raises(PolicyError) as error:
        audit_events(tmp_path)
    assert error.value.code == 'NO_CORPORATE_EVENT_ARCHIVE'
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('query', [
    {'symbol': 'aapl'}, {'symbol': 'AAPL,TSLA'}, {'symbol': '../secret'},
    {'database': '../secret'}, {'database': 'archive'}, {'limit': 0},
    {'limit': 101}, {'offset': -1}, {'offset': 100001},
])
def test_invalid_query_never_reads_a_file(tmp_path, query):
    with pytest.raises(PolicyError) as error:
        audit_events(tmp_path, **query)
    assert error.value.code == 'ACTION_AUDIT_QUERY_INVALID'
    assert not (tmp_path / 'data').exists()


def test_future_and_naive_asof_rejected_before_db_access(tmp_path):
    with pytest.raises(PolicyError):
        audit_events(tmp_path, asof_utc='2099-12-31T00:00:00Z')
    with pytest.raises(PolicyError):
        audit_events(tmp_path, asof_utc='2026-11-01T00:00:00')


def test_receipt_index_rejects_unverified_claims(tmp_path):
    directory = tmp_path / 'receipts'
    directory.mkdir()
    (directory / 'bad.json').write_text(json.dumps({
        'url': 'https://data.alpaca.markets/v1/corporate-actions',
        'params': {'symbols': 'AAPL'},
        'sha256': hashlib.sha256(b'anything').hexdigest(),
        'fetched_at': '2026-11-01T00:00:00Z',
        'request_key': '0'*64,
    }))
    assert _receipt_index(tmp_path) == {}


def test_cannot_reclassify_a_missing_source_as_verified(tmp_path):
    record = {
        'provider': 'ALPACA',
        'source_endpoint': 'https://data.alpaca.markets/v1/corporate-actions',
        'provider_event_id': 'provider-event-1',
        'event_type': 'forward_splits', 'symbol': 'AAPL',
        'raw_sha256': 'f'*64,
        'retrieved_at_utc': '2026-11-01T00:00:00Z',
        'available_at_utc': '2026-11-01T00:00:00Z',
        'published_at_utc': None,
        'payload': {},
    }
    outcome = _audit_record(record, tmp_path, {}, _safe_time('2026-11-02T00:00:00Z'))
    assert outcome['status'] == 'BLOCKED_SOURCE_EVIDENCE'
    assert outcome['historical_pit_eligible'] is False
    assert outcome['settlement_eligible'] is False
    assert outcome['real_orders_enabled'] is False


def test_event_day_is_a_label_not_publication_time():
    assert _event_day({'process_date': '2020-01-03'}) == '2020-01-03'
    assert _event_day('bad') is None
    with pytest.raises(ValueError):
        _safe_time('2026-11-01T00:00:00')


def test_no_production_code_writes_backtest_acceptance():
    code = Path(__file__).resolve().parents[1] / 'quant_research/data/action_audit.py'
    content = code.read_text(encoding='utf-8')
    assert 'PIT_VERIFIED' not in content
    assert 'INSERT INTO' not in content
    assert 'UPDATE ' not in content


def test_actual_archived_vintage_if_available():
    """Positive end-to-end evidence only when the genuine local G2 warehouse exists."""
    project = Path.cwd()
    if not any((project / 'data' / name).is_file() for name in
               ('g2_evidence.duckdb', 'real_v21.duckdb', 'research.duckdb')):
        pytest.skip('BLOCKED_NO_REAL_G2_EVENT_DATABASE')
    response = audit_events(project, limit=10)
    assert response['historical_pit_eligible'] is False
    assert response['settlement_eligible'] is False
    assert response['real_orders_enabled'] is False
    assert all(not x['settlement_eligible'] for x in response['events']
               if 'settlement_eligible' in x)
