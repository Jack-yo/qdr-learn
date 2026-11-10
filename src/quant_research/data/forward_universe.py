"""Evidence-bound, forward-only asset-directory history and symbol resolution.

This is NOT a historical PIT constituent universe and never writes PIT_VERIFIED,
identity attestations, orders, or corporate-action settlement records.
Only actual G7 immutable provider response archives can supply asset observations.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re

from quant_research.data.assets import _root, _latest, _read_manifest, _timestamp, _digest, _canonical
from quant_research.policy import PolicyError

_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,19}")
_SHA = re.compile(r"[a-f0-9]{64}")
_MAX_OBSERVATIONS = 1000
_MAX_QUERY = 100
_STALE_AFTER_HOURS = 96  # Includes ordinary exchange weekends; not evidence of current tradability.


def _asof(value):
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str):
        raise PolicyError('ASSET_ASOF_INVALID', 'As-of must be an ISO 8601 UTC timestamp with an explicit offset')
    stamp = _timestamp(value)
    if stamp > datetime.now(timezone.utc):
        raise PolicyError('ASSET_ASOF_IN_FUTURE', 'Cannot inspect an asset observation as if it were already known')
    return stamp


def _observations(project_root):
    """Verify a complete immutable G7 snapshot chain, most recent first.

    Walking from the latest pointer rejects disconnected/tampered predecessor
    references.  Chronology is measured by the real API receipt time, never by
    price-bar dates, ticker first-seen fields or source current status.
    """
    folder = _root(project_root)
    manifest, assets = _latest(folder)
    first_id = _digest(_canonical(manifest))
    result, visited = [], set()
    current = (first_id, manifest, assets)
    now = datetime.now(timezone.utc)
    while current is not None:
        sid, meta, rows = current
        if sid in visited or len(result) >= _MAX_OBSERVATIONS:
            raise PolicyError('ASSET_CHAIN_INVALID', 'Snapshot chain contains a cycle or exceeds safety limit')
        visited.add(sid)
        observed = _timestamp(meta['observed_at_utc'])
        if observed > now:
            raise PolicyError('ASSET_CHAIN_INVALID', 'Asset observation timestamp is in the future')
        if result and observed > result[-1]['observed_at']:
            raise PolicyError('ASSET_CHAIN_INVALID', 'Source observations are not ordered chronologically')
        result.append({'snapshot_id': sid, 'manifest': meta, 'rows': rows, 'observed_at': observed})
        parent = meta.get('previous_snapshot_id')
        if parent is None:
            break
        if not isinstance(parent, str) or not _SHA.fullmatch(parent):
            raise PolicyError('ASSET_CHAIN_INVALID', 'Invalid previous asset observation ID')
        parent_meta, parent_rows = _read_manifest(folder, parent)
        current = (parent, parent_meta, parent_rows)
    return result


def _select(root, asof):
    history = _observations(root)
    selected = next((x for x in history if x['observed_at'] <= asof), None)
    if selected is None:
        raise PolicyError('NO_ASOF_ASSET_EVIDENCE',
                          'No actual provider asset snapshot had been observed by the requested cutoff',
                          ['first authenticated asset observation must precede as-of time'])
    age_hours = (asof - selected['observed_at']).total_seconds() / 3600
    return selected, age_hours, history


def _row(asset, collisions):
    return {
        'asset_id': asset['id'], 'symbol': asset['symbol'],
        'name': asset.get('name') or '', 'exchange': asset['exchange'],
        'source_status': asset['status'], 'provider_tradable': asset['tradable'],
        'ticker_ambiguous': asset['symbol'] in collisions,
        'observed_candidate': (asset['status'] == 'active' and asset['tradable']
                               and asset['symbol'] not in collisions),
        'stock_vs_etf_verified': False, 'issuer_identity_verified': False,
        'historical_pit_eligible': False, 'trading_signal_eligible': False,
    }


def asof_directory(project_root, *, asof_utc=None, q='', state='all', limit=30, offset=0):
    """Read an actual past observation; never project today's directory backwards."""
    if (not isinstance(q, str) or len(q) > 64 or state not in {'all','active','inactive','candidate','ambiguous'}
            or type(limit) is not int or not 0 <= limit <= _MAX_QUERY
            or type(offset) is not int or not 0 <= offset <= 1000000):
        raise PolicyError('ASSET_QUERY_INVALID', 'Invalid historical observation query or pagination')
    cutoff = _asof(asof_utc)
    selected, age, history = _select(project_root, cutoff)
    counts = Counter(r['symbol'] for r in selected['rows'])
    collisions = {s for s,n in counts.items() if n > 1}
    records = [_row(item, collisions) for item in selected['rows']]
    if state != 'all':
        if state == 'candidate':
            records = [item for item in records if item['observed_candidate']]
        elif state == 'ambiguous':
            records = [item for item in records if item['ticker_ambiguous']]
        else:
            records = [item for item in records if item['source_status'] == state]
    if q:
        lowered = q.casefold()
        records = [item for item in records if lowered in item['symbol'].casefold() or lowered in item['name'].casefold()]
    records.sort(key=lambda item: (item['symbol'], item['asset_id']))
    fresh = age <= _STALE_AFTER_HOURS
    return {
        'status': 'OBSERVATION_ONLY' if fresh else 'STALE_OBSERVATION_ONLY',
        'source': 'ALPACA', 'asof_utc': cutoff.isoformat(),
        'observed_at_utc': selected['observed_at'].isoformat(),
        'snapshot_id': selected['snapshot_id'],
        'raw_sha256': selected['manifest']['raw_sha256'],
        'endpoint': selected['manifest']['endpoint'],
        'hours_since_observation': round(age, 3), 'fresh_for_observation': fresh,
        'max_observation_age_hours': _STALE_AFTER_HOURS,
        'snapshot_count': len(history),
        'source_records': len(selected['rows']),
        'duplicate_ticker_count': len(collisions),
        'observed_active_tradable_unclassified': sum(x['observed_candidate'] for x in (_row(a,collisions) for a in selected['rows'])),
        'filtered_count': len(records), 'offset': offset, 'limit': limit,
        'assets': records[offset:offset+limit],
        'capabilities': {
            'provider_id_at_observation': 'SOURCE_OBSERVED',
            'current_stock_only_universe': 'BLOCKED_ASSET_CLASS_INCLUDES_ETF',
            'historical_pit_universe': 'BLOCKED_NO_POINT_IN_TIME_MEMBERSHIP',
            'issuer_or_permanent_security_identity': 'BLOCKED_VENDOR_UUID_NOT_ISSUER_ID',
            'corporate_actions_and_delistings': 'BLOCKED_NO_EVENT_SETTLEMENT_PROOF',
            'strict_backtest': 'BLOCKED_NEEDS_HISTORICAL_IDENTITY_AND_ACTIONS',
        },
        'real_orders_enabled': False,
    }


def resolve_symbols(project_root, symbols, *, asof_utc=None):
    """Resolve provider asset UUIDs only from information observed by as-of.

    Returns rejected/ambiguous entries explicitly; it never upgrades the raw
    historical bar security_id, uses symbols as identity, or grants trade access.
    """
    if (not isinstance(symbols, (list, tuple)) or not 1 <= len(symbols) <= _MAX_QUERY
            or any(not isinstance(s,str) or not _SYMBOL.fullmatch(s) for s in symbols)
            or len(set(symbols)) != len(symbols)):
        raise PolicyError('ASSET_SYMBOLS_INVALID', 'Provide 1–100 distinct uppercase symbol codes')
    cutoff = _asof(asof_utc)
    selected, age, _ = _select(project_root, cutoff)
    by_symbol = {}
    for row in selected['rows']:
        by_symbol.setdefault(row['symbol'], []).append(row)
    results = []
    for symbol in symbols:
        matches = by_symbol.get(symbol, [])
        if not matches:
            reason = 'NOT_IN_OBSERVED_RESPONSE'
        elif len(matches) > 1:
            reason = 'SYMBOL_MULTIPLE_ASSET_UUIDS'
        elif age > _STALE_AFTER_HOURS:
            reason = 'SOURCE_OBSERVATION_STALE'
        elif matches[0]['status'] != 'active' or matches[0]['tradable'] is not True:
            reason = 'ASSET_NOT_ACTIVE_TRADABLE_AT_OBSERVATION'
        else:
            reason = None
        results.append({'symbol': symbol, 'provider_asset_id': matches[0]['id'] if len(matches)==1 else None,
                        'observed_asset_id_resolvable': reason is None,
                        'block_reason': reason, 'stock_vs_etf_verified': False,
                        'historical_pit_eligible': False, 'trading_signal_eligible': False})
    return {'status': 'OBSERVED_PROVIDER_ID_MAPPING_ONLY', 'asof_utc':cutoff.isoformat(),
            'observed_at_utc':selected['observed_at'].isoformat(),
            'snapshot_id':selected['snapshot_id'], 'source':'ALPACA',
            'resolved_count':sum(x['observed_asset_id_resolvable'] for x in results),
            'requested_count':len(results), 'results':results,
            'historical_pit_eligible':False, 'real_orders_enabled':False}


def observation_changes(project_root, *, limit=30):
    """Diff *observed* records, not legal listing/delisting corporate actions."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PolicyError('ASSET_QUERY_INVALID', 'Invalid observation history limit')
    snapshots = _observations(project_root)
    transitions = []
    for latest, prior in zip(snapshots, snapshots[1:]):
        old = {a['id']:a for a in prior['rows']}
        new = {a['id']:a for a in latest['rows']}
        added, missing = sorted(set(new)-set(old)), sorted(set(old)-set(new))
        changed = sorted(i for i in set(new)&set(old)
                         if any(new[i].get(k)!=old[i].get(k) for k in ('symbol','status','tradable','exchange')))
        transitions.append({
            'from_observed_utc':prior['observed_at'].isoformat(),
            'to_observed_utc':latest['observed_at'].isoformat(),
            'snapshot_id':latest['snapshot_id'],
            'source_asset_ids_added_to_response':len(added),
            'source_asset_ids_absent_from_response':len(missing),
            'same_asset_id_attributes_changed':len(changed),
            'examples':[
                {'asset_id':i,'kind':'ADDED_TO_RESPONSE','symbol':new[i]['symbol']} for i in added[:10]
            ] + [
                {'asset_id':i,'kind':'ABSENT_FROM_RESPONSE','symbol':old[i]['symbol']} for i in missing[:10]
            ] + [
                {'asset_id':i,'kind':'ATTRIBUTES_CHANGED','symbol_before':old[i]['symbol'],
                 'symbol_after':new[i]['symbol'], 'status_before':old[i]['status'],
                 'status_after':new[i]['status']} for i in changed[:10]
            ],
            'not_proof_of_legal_listing_delisting_rename':True,
        })
        if len(transitions)>=limit:
            break
    return {'status':'SOURCE_OBSERVATION_HISTORY',
            'snapshot_count':len(snapshots), 'latest_observed_at_utc':snapshots[0]['observed_at'].isoformat(),
            'transitions':transitions,'historical_pit_eligible':False,
            'real_orders_enabled':False}