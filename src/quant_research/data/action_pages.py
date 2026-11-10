"""G8.3: independently verify a complete archived Alpaca corporate-action page chain.

This verifier is strictly read-only. A complete provider pagination traversal for an
explicit query is NOT issuer-universe coverage, PIT availability or settlement proof.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from quant_research.policy import PolicyError
from quant_research.data.action_audit import ENDPOINT, _safe_time

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LIMIT = 100


def _error(code, description, missing=()):
    raise PolicyError(code, description, missing)


def _checked_query(symbols, start, end, page_size):
    if (not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= _LIMIT
            or any(not isinstance(v, str) or not _SYMBOL.fullmatch(v) for v in symbols)
            or len(set(symbols)) != len(symbols)):
        _error('ACTION_QUERY_INVALID', 'Choose 1–100 distinct uppercase asset codes')
    try:
        left, right = date.fromisoformat(start), date.fromisoformat(end)
    except (TypeError, ValueError):
        _error('ACTION_QUERY_INVALID', 'Start and end must be ISO dates')
    if left > right or type(page_size) is not int or not 1 <= page_size <= 1000:
        _error('ACTION_QUERY_INVALID', 'Invalid date range or page-size limit')
    return {'symbols': ','.join(sorted(symbols)), 'start': left.isoformat(), 'end': right.isoformat(),
            'limit': page_size, 'sort': 'asc', 'data_quality': 'complete'}


def _key(params):
    return sha256((ENDPOINT + '?' + urlencode(sorted(params.items()))).encode()).hexdigest()


def _catalog(raw_root, cutoff):
    folder = Path(raw_root) / 'receipts'
    if not folder.is_dir():
        _error('ACTION_RECEIPTS_MISSING', 'No real archived corporate-action request receipts')
    index = {}
    # Never trust a mutable requests cache pointer. Inspect all immutable fetch receipts.
    for path in folder.glob('*.json'):
        try:
            item = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(item, dict) or item.get('url') != ENDPOINT
                    or not isinstance(item.get('params'), dict)
                    or item.get('request_key') != _key(item['params'])
                    or not isinstance(item.get('sha256'), str)
                    or not _SHA.fullmatch(item['sha256'])):
                continue
            when = _safe_time(item['fetched_at'])
            if when > cutoff:
                continue
            index.setdefault(item['request_key'], []).append((when, item))
        except (OSError, TypeError, ValueError, KeyError):
            continue
    for group in index.values():
        group.sort(key=lambda part: part[0])
    return index


def _read_page(root, receipt):
    digest = receipt['sha256']
    path = root / 'objects' / digest
    try:
        raw = path.read_bytes()
    except OSError:
        _error('ACTION_PAGE_BYTES_MISSING', 'Immutable provider page is missing', [digest])
    if len(raw) > 25 * 1024 * 1024 or sha256(raw).hexdigest() != digest:
        _error('ACTION_PAGE_HASH_MISMATCH', 'Provider page hash is corrupt or over size limit', [digest])
    try:
        response = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        _error('ACTION_PAGE_JSON_INVALID', 'Provider page is not valid JSON')
    if not isinstance(response, dict) or not isinstance(response.get('corporate_actions'), dict):
        _error('ACTION_PAGE_SCHEMA_INVALID', 'Missing source corporate_actions object')
    next_token = response.get('next_page_token')
    if next_token is not None and (not isinstance(next_token, str) or not next_token or len(next_token) > 2048):
        _error('ACTION_PAGE_TOKEN_INVALID', 'Provider returned an invalid continuation token')
    count, ids = 0, []
    for kind, group in response['corporate_actions'].items():
        if not isinstance(kind, str) or not isinstance(group, list):
            _error('ACTION_PAGE_SCHEMA_INVALID', 'Invalid corporate-action event group')
        for event in group:
            if not isinstance(event, dict) or not isinstance(event.get('id'), str) or not event['id']:
                _error('ACTION_PAGE_EVENT_INVALID', 'Event must have a provider event ID')
            count += 1
            ids.append(event['id'])
    return next_token, count, ids


def audit_action_pages(project_root, *, symbols, start, end, page_size=1000,
                       asof_utc=None, max_pages=100):
    """Verify request-to-response continuity and detect incomplete/mixed page chains.

    Returns only source-query completeness. It never writes action_coverage_daily,
    universe_daily, issuer IDs, model attestations, or orders.
    """
    params = _checked_query(symbols, start, end, page_size)
    if type(max_pages) is not int or not 1 <= max_pages <= 1000:
        _error('ACTION_QUERY_INVALID', 'max_pages must be from 1 through 1000')
    if asof_utc is None:
        cutoff = datetime.now(timezone.utc)
    else:
        try:
            cutoff = _safe_time(asof_utc)
        except (ValueError, TypeError):
            _error('ACTION_ASOF_INVALID', 'UTC knowledge cutoff needs an explicit timezone')
        if cutoff > datetime.now(timezone.utc):
            _error('ACTION_ASOF_IN_FUTURE', 'Cannot use future source evidence')
    root = Path(project_root).resolve() / 'data' / 'raw'
    index = _catalog(root, cutoff)
    base_key = _key(params)
    first = index.get(base_key, [])
    if not first:
        _error('ACTION_FIRST_PAGE_MISSING', 'No authenticated first page of this exact source query',
               ['matching symbol set / date range / page size / real fetch receipt'])
    # The latest first-page attempt is authoritative. Never silently fall back
    # to an older successful traversal when a newer traversal is incomplete.
    when, receipt = first[-1]
    pages, previous_time = [], when
    token, seen_tokens, seen_ids = None, set(), set()
    for page_number in range(max_pages):
        expected_params = {**params, **({'page_token': token} if token else {})}
        if receipt['params'] != expected_params:
            _error('ACTION_PAGE_REQUEST_MISMATCH', 'Response belongs to a different provider query')
        next_token, count, event_ids = _read_page(root, receipt)
        if seen_ids.intersection(event_ids) or len(event_ids) != len(set(event_ids)):
            _error('ACTION_PAGE_DUPLICATE_EVENTS', 'An event ID was repeated across source pages')
        seen_ids.update(event_ids)
        pages.append({'index': page_number + 1, 'response_sha256': receipt['sha256'],
                      'request_key': receipt['request_key'], 'fetched_at_utc': previous_time.isoformat(),
                      'source_event_count': count, 'has_next_page': bool(next_token)})
        if next_token is None:
            return {
                'status': 'SOURCE_QUERY_PAGE_CHAIN_VERIFIED', 'source': 'ALPACA',
                'source_endpoint': ENDPOINT, 'source_query': params,
                'asof_utc': cutoff.isoformat(), 'first_page_observed_at_utc': when.isoformat(),
                'last_page_observed_at_utc': previous_time.isoformat(),
                'verified_page_count': len(pages), 'unique_source_event_count': len(seen_ids),
                'pages': pages, 'source_query_pagination_complete': True,
                'full_historical_action_coverage_verified': False,
                'historical_publication_time_verified': False,
                'issuer_identity_verified': False, 'settlement_verified': False,
                'historical_pit_eligible': False, 'historical_backtest_eligible': False,
                'real_orders_enabled': False,
                'limitations': ['EXACT_PROVIDER_QUERY_ONLY_NOT_FULL_HISTORICAL_UNIVERSE',
                                'PAGINATION_DOES_NOT_PROVE_HISTORIC_PUBLICATION_TIME',
                                'CORPORATE_ACTION_SETTLEMENT_NOT_VERIFIED'],
            }
        if next_token in seen_tokens:
            _error('ACTION_PAGE_CYCLE', 'Repeated provider continuation token')
        seen_tokens.add(next_token)
        token = next_token
        next_params = {**params, 'page_token': token}
        candidates = [item for item in index.get(_key(next_params), []) if item[0] >= previous_time]
        if not candidates:
            _error('ACTION_PAGE_CHAIN_INCOMPLETE', 'A provider continuation page is not archived',
                   ['page_token:' + token[:64]])
        previous_time, receipt = candidates[0]
    _error('ACTION_PAGE_LIMIT', 'Page traversal exceeded the configured maximum')
