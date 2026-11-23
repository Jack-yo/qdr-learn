"""Current-vintage split-only feature prices. Never an execution-price contract."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import math
import os
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant_research.policy import PolicyError
from .bundle import frame_hash
from .http import DataUnavailable
from .providers.actions import ActionProvider


BASIS = 'split_adjusted_price_proxy'
# Declared before examining reference results; do not relax to obtain a pass.
TOLERANCES = {'price_atol': 0.0001, 'price_rtol': 1e-8, 'volume_atol': 1.0}


@dataclass(frozen=True)
class FeaturePrices:
    _prices: pd.DataFrame
    _metadata: dict

    @property
    def prices(self):
        if frame_hash(self._prices) != self._metadata['feature_snapshot_sha256']:
            raise PolicyError('FEATURE_SNAPSHOT_MUTATED', 'Derived feature snapshot changed')
        return self._prices.copy(deep=True)

    @property
    def metadata(self):
        return deepcopy(self._metadata)


def build_split_prices(bundle, http, action_start, action_end):
    """Re-read the full hashed action query; no caller-supplied events or PASS switch.

    The query is by process_date, NOT ex_date or historical publication time.
    A vendor query is evidence of returned records, not proof of market-wide completeness.
    """
    bundle.require('raw_prices')
    raw = bundle.prices
    if set(raw.source) != {'ALPACA'} or set(raw.feed) != {'sip'}:
        raise PolicyError('FEATURE_SOURCE_UNSUPPORTED', 'This transform requires verified Alpaca SIP raw')
    anchor = date.fromisoformat(bundle.metadata['asof_date_et'])
    if date.fromisoformat(action_start) > pd.to_datetime(raw.date).min().date() or date.fromisoformat(action_end) < anchor:
        raise PolicyError('ACTION_QUERY_COVERAGE', 'Action process-date query must span the price range and anchor')
    provider = ActionProvider(http)
    events = provider.events(sorted(set(raw.symbol)), action_start, action_end)
    # A mutable request pointer alone is insufficient evidence of first observation.
    receipts = {}
    for path in (http.root/'receipts').glob('*.json'):
        receipt = json.loads(path.read_text(encoding='utf-8'))
        receipts.setdefault(receipt.get('request_key'), []).append(receipt)
    for page in provider.pages:
        matching = [r for r in receipts.get(page['request_key'], [])
                    if r.get('url') == provider.endpoint and r.get('sha256') == page['raw_sha256']
                    and r.get('fetched_at') == page['retrieved_at_utc']]
        if not matching:
            raise PolicyError('ACTION_RECEIPT_MISSING', 'Action observation lacks an immutable source receipt')
    observed = max(pd.Timestamp(p['retrieved_at_utc']) for p in provider.pages)
    if observed > pd.Timestamp(bundle.metadata['knowledge_cutoff_utc']):
        raise PolicyError('ACTION_AFTER_CUTOFF', 'Action snapshot was observed after the requested knowledge cutoff')
    symbols = set(raw.symbol)
    splits, seen, unsupported = [], set(), []
    for event in events:
        if event['symbol'] not in symbols:
            raise PolicyError('ACTION_SYMBOL_MISMATCH', 'Unrequested action symbol returned')
        kind, payload = event['event_type'], event['payload']
        if kind == 'cash_dividends':
            continue  # Explicit price-return proxy; no dividend adjustment or cash credit.
        effective = payload.get('ex_date') or payload.get('effective_date')
        if not effective:
            unsupported.append(f"{event['symbol']}:{kind}:effective date missing")
            continue
        effective = date.fromisoformat(effective)
        if effective > anchor:
            continue  # Never apply a future split to an earlier anchor.
        if kind not in ('forward_splits', 'reverse_splits'):
            unsupported.append(f"{event['symbol']}:{kind}:{effective}")
            continue
        key = event['symbol'], effective
        if key in seen:
            raise PolicyError('ACTION_REVISION_AMBIGUOUS', 'Multiple split claims for one symbol/date', [str(key)])
        seen.add(key)
        if 'old_rate' not in payload or 'new_rate' not in payload or not payload.get('ex_date'):
            raise PolicyError('INVALID_SPLIT_FIELDS', 'Split requires old/new rates and ex-date')
        old, new = float(payload['old_rate']), float(payload['new_rate'])
        if not all(math.isfinite(x) and x > 0 for x in (old, new)):
            raise PolicyError('INVALID_SPLIT_RATIO', 'Split ratios must be finite and positive')
        if (kind == 'forward_splits' and new <= old) or (kind == 'reverse_splits' and old <= new):
            raise PolicyError('INVALID_SPLIT_DIRECTION', 'Split direction contradicts old/new rates')
        splits.append({**event, 'price_multiplier': old/new})
    if unsupported:
        raise PolicyError('UNSUPPORTED_FEATURE_ACTION', 'Affected symbols require an accepted event treatment', unsupported)
    prices = raw.copy(deep=True)
    multiplier = pd.Series(1.0, index=prices.index)
    days = pd.to_datetime(prices.date).dt.date
    for event in splits:
        mask = prices.symbol.eq(event['symbol']) & days.lt(date.fromisoformat(event['payload']['ex_date']))
        multiplier.loc[mask] *= event['price_multiplier']
    for column in ('open', 'high', 'low', 'close', 'vwap'):
        if column in prices:
            prices[column] = prices[column] * multiplier
    prices['volume'] = prices.volume / multiplier
    prices['split_price_multiplier'] = multiplier
    prices['raw_price_response_sha256'] = prices.raw_sha256
    prices = prices.rename(columns={'ingested_at': 'raw_price_ingested_at'})
    prices = prices.drop(columns=['adj_close'], errors='ignore')
    prices['adjustment_basis'] = BASIS
    # Even zero-event claims depend on observation of the action query.
    prices['available_at'] = pd.to_datetime(prices.available_at, utc=True).clip(lower=observed)
    prices['availability_basis'] = 'max_price_and_action_first_observed'
    prices['quality_flag'] = prices.quality_flag.astype(str) + '|SPLIT_ONLY_PRICE_PROXY|NOT_TOTAL_RETURN|NOT_EXECUTION_PRICE'
    if not np.isfinite(prices[['open','high','low','close','volume']].to_numpy()).all():
        raise PolicyError('FEATURE_NUMERIC_INVALID', 'Split adjustment produced invalid numeric values')
    dollar_error = float((prices.close * prices.volume - raw.close * raw.volume).abs().max())
    if not np.allclose(prices.close * prices.volume, raw.close * raw.volume, rtol=1e-12, atol=1e-6):
        raise PolicyError('FEATURE_DOLLAR_VOLUME_MISMATCH', 'Split adjustment must preserve price times volume')
    metadata = {
        'source': 'ALPACA', 'feed': 'sip', 'adjustment_basis': BASIS,
        'anchor_date_et': str(anchor), 'rows': len(prices), 'symbols': sorted(symbols),
        'raw_snapshot_sha256': bundle.metadata['snapshot_sha256'],
        'feature_snapshot_sha256': frame_hash(prices), 'action_pages': provider.pages,
        'action_query': {'start': action_start, 'end': action_end, 'date_basis': 'process_date'},
        'returned_events': len(events), 'applied_splits': splits,
        'cash_dividends_excluded': sum(e['event_type'] == 'cash_dividends' for e in events),
        'max_dollar_volume_absolute_error': dollar_error,
        'source_version_kind': 'current_revised_snapshot', 'historical_decision_eligible': False,
        'research_grade': False, 'execution_ready': False, 'real_orders_enabled': False,
        'limitations': ['PRICE_RETURN_PROXY_NOT_TOTAL_RETURN', 'ACTION_COMPLETENESS_NOT_INDEPENDENTLY_PROVEN',
                        'HISTORICAL_AVAILABILITY_UNVERIFIED', 'PERMANENT_IDENTITIES_UNVERIFIED'],
    }
    return FeaturePrices(prices, metadata)


def split_reference(http, clock, symbols, start, end):
    """Separate vendor-normalized reference; deliberately never constructs PriceRecord."""
    zone = ZoneInfo('America/New_York')
    params = {'symbols': ','.join(sorted(set(symbols))), 'timeframe': '1Day', 'adjustment': 'split',
              'feed': 'sip', 'sort': 'asc', 'limit': 10000, 'asof': '-',
              'start': datetime.combine(date.fromisoformat(start), datetime.min.time(), zone).isoformat(),
              'end': (clock.close(end) + timedelta(minutes=1)).isoformat()}
    headers = {}
    if not http.offline:
        key, secret = os.environ.get('ALPACA_API_KEY'), os.environ.get('ALPACA_SECRET_KEY')
        if not key or not secret:
            raise DataUnavailable('Local Alpaca credentials required', 'MISSING_CREDENTIALS')
        headers = {'APCA-API-KEY-ID': key, 'APCA-API-SECRET-KEY': secret}
    rows, pages, tokens, keys = [], [], set(), set()
    while True:
        response = http.get('https://data.alpaca.markets/v2/stocks/bars', params, headers)
        payload = json.loads(response.body)
        if not isinstance(payload.get('bars'), dict):
            raise DataUnavailable('Invalid split-reference schema')
        pages.append({'raw_sha256': response.sha256, 'retrieved_at_utc': response.fetched_at.isoformat(),
                      'request_key': response.request_key})
        for symbol, bars in payload['bars'].items():
            if symbol not in symbols:
                raise DataUnavailable('Unexpected split-reference symbol')
            for bar in bars:
                day = pd.Timestamp(bar['t']).tz_convert(zone).date()
                key = symbol, day
                if key in keys:
                    raise DataUnavailable('Duplicate split-reference row')
                keys.add(key)
                if not date.fromisoformat(start) <= day <= date.fromisoformat(end):
                    raise DataUnavailable('Split-reference date outside query')
                values = [float(bar[k]) for k in ('o','h','l','c','v')]
                if not all(math.isfinite(v) and v > 0 for v in values):
                    raise DataUnavailable('Invalid split-reference OHLCV')
                rows.append({
                    'symbol':symbol,'date':day,'open':values[0],'high':values[1],
                    'low':values[2],'close':values[3],'volume':values[4],
                    'event_time':clock.close(day),
                    'available_at':response.fetched_at,
                    'ingested_at':response.fetched_at,
                    'availability_basis':'first_observed',
                    'raw_sha256':response.sha256,
                })
        token = payload.get('next_page_token')
        if not token:
            break
        if token in tokens:
            raise DataUnavailable('Repeated split-reference token')
        tokens.add(token)
        params = {**params, 'page_token': token}
    return pd.DataFrame(rows), pages


def vendor_split_features(bundle, reference):
    """Use the provider's own split-adjusted SIP bars as current forward features.

    This path is intentionally narrower than the raw-to-adjusted normalization
    audit.  It does not prove our corporate-action reconstruction, historical
    PIT membership, total-return labels, or execution prices.  It only admits
    the exact vendor-normalized bars whose immutable response receipts are
    already present in the raw cache.
    """
    if not isinstance(reference, pd.DataFrame) or reference.empty:
        raise PolicyError('VENDOR_SPLIT_REFERENCE_MISSING',
                          'Vendor split-adjusted feature reference is empty')
    required = {
        'symbol','date','open','high','low','close','volume','event_time',
        'available_at','ingested_at','availability_basis','raw_sha256',
    }
    if required - set(reference):
        raise PolicyError('VENDOR_SPLIT_REFERENCE_SCHEMA_INVALID',
                          'Vendor split-adjusted feature rows lack provenance fields')
    ref = reference.copy()
    ref['date'] = pd.to_datetime(ref['date'])
    if ref.duplicated(['symbol','date']).any():
        raise PolicyError('VENDOR_SPLIT_REFERENCE_DUPLICATED',
                          'Vendor split-adjusted rows contain duplicate symbol/date keys')
    if ref['raw_sha256'].astype(str).str.fullmatch(r'[0-9a-f]{64}').eq(False).any():
        raise PolicyError('VENDOR_SPLIT_REFERENCE_PROVENANCE_INVALID',
                          'Vendor split-adjusted rows lack valid response hashes')
    raw = bundle.prices
    mapping = raw[['symbol','security_id']].drop_duplicates()
    if mapping.symbol.duplicated().any() or mapping.security_id.duplicated().any():
        raise PolicyError('VENDOR_SPLIT_IDENTITY_AMBIGUOUS',
                          'Current raw bundle does not provide a one-to-one symbol identity map')
    identity = mapping.set_index('symbol').security_id.to_dict()
    requested = set(bundle.metadata['symbols'])
    if set(ref.symbol) - requested:
        raise PolicyError('VENDOR_SPLIT_REFERENCE_SYMBOL_MISMATCH',
                          'Vendor split-adjusted response contains an unrequested symbol')
    anchor = pd.Timestamp(bundle.metadata['asof_date_et'])
    current = ref.loc[ref.date.eq(anchor)]
    if set(current.symbol) != requested or len(current) != len(requested):
        raise PolicyError('VENDOR_SPLIT_REFERENCE_CURRENT_COVERAGE',
                          'Vendor split-adjusted bars do not cover the full requested current session')
    if not set(ref.symbol).issubset(identity):
        raise PolicyError('VENDOR_SPLIT_IDENTITY_MISSING',
                          'Vendor split-adjusted symbol has no matching observed raw identity')
    cutoff = pd.Timestamp(bundle.metadata['knowledge_cutoff_utc'])
    if cutoff.tzinfo is None:
        raise PolicyError('VENDOR_SPLIT_CUTOFF_INVALID',
                          'Current feature cutoff must be timezone-aware')
    cutoff = cutoff.tz_convert('UTC')
    available = pd.to_datetime(ref.available_at, utc=True)
    ingested = pd.to_datetime(ref.ingested_at, utc=True)
    events = pd.to_datetime(ref.event_time, utc=True)
    if (available.gt(cutoff).any() or ingested.lt(available).any()
            or available.lt(events).any()):
        raise PolicyError('VENDOR_SPLIT_AVAILABILITY_INVALID',
                          'Vendor split-adjusted bars violate source/cutoff time ordering')
    ref['security_id'] = ref.symbol.map(identity)
    ref['source'] = 'ALPACA'
    ref['feed'] = 'sip'
    ref['adjustment_basis'] = 'vendor_split_adjusted_price_proxy'
    ref['quality_flag'] = (
        'REAL|ALPACA_VENDOR_SPLIT_ADJUSTED|CURRENT_FORWARD_RESEARCH_ONLY|'
        'NOT_TOTAL_RETURN|NOT_EXECUTION_PRICE|HISTORICAL_PIT_UNVERIFIED'
    )
    prices = ref[[
        'date','security_id','symbol','open','high','low','close','volume',
        'event_time','available_at','ingested_at','availability_basis',
        'raw_sha256','source','feed','adjustment_basis','quality_flag',
    ]].sort_values(['security_id','date']).reset_index(drop=True)
    metadata = {
        'source':'ALPACA','feed':'sip',
        'adjustment_basis':'vendor_split_adjusted_price_proxy',
        'anchor_date_et':str(anchor.date()),
        'rows':len(prices),'symbols':sorted(requested),
        'raw_snapshot_sha256':bundle.metadata['snapshot_sha256'],
        'feature_snapshot_sha256':frame_hash(prices),
        'source_version_kind':'current_vendor_normalized_snapshot',
        'historical_decision_eligible':False,
        'research_grade':False,'execution_ready':False,'real_orders_enabled':False,
        'limitations':[
            'VENDOR_NATIVE_SPLIT_ADJUSTMENT_NOT_LOCAL_NORMALIZATION_PROOF',
            'PRICE_RETURN_PROXY_NOT_TOTAL_RETURN',
            'HISTORICAL_PIT_UNIVERSE_UNVERIFIED',
            'PERMANENT_IDENTITIES_UNVERIFIED',
            'NOT_EXECUTION_PRICE',
        ],
    }
    return FeaturePrices(prices, metadata)


def compare_reference(features, reference):
    """Full OHLCV/key reconciliation; missing or extra reference rows cannot pass."""
    local = features.prices.copy()
    local['date'] = pd.to_datetime(local.date).dt.date
    reference = reference.copy()
    reference['date'] = pd.to_datetime(reference.date).dt.date
    joined = local.merge(reference, on=['symbol','date'], suffixes=('_local','_vendor'), how='outer',
                         indicator=True, validate='one_to_one')
    checks, failures = {}, pd.Series(False, index=joined.index)
    for column in ('open','high','low','close','volume'):
        a, b = joined[column+'_local'], joined[column+'_vendor']
        good = np.isclose(a, b, rtol=0 if column=='volume' else TOLERANCES['price_rtol'],
                          atol=TOLERANCES['volume_atol'] if column=='volume' else TOLERANCES['price_atol'])
        failures |= ~good
        unadjusted = joined['split_price_multiplier'].eq(1)
        checks[column] = {'mismatches': int((~good).sum()), 'max_absolute_error': float((a-b).abs().max()),
                          'unadjusted_row_mismatches': int(((~good) & unadjusted).sum())}
    missing = int(joined['_merge'].ne('both').sum())
    examples = joined.loc[failures, ['symbol','date']].head(20).astype(str).to_dict('records')
    return {'status': 'PASS' if not failures.any() and not missing else 'BLOCKED',
            'scope': 'SAME_VENDOR_NORMALIZATION_CONSISTENCY_ONLY', 'rows_compared': len(joined),
            'unmatched_keys': missing, 'tolerances': TOLERANCES.copy(), 'checks': checks,
            'mismatch_examples': examples, 'independent_completeness_proof': False,
            'diagnostic_note': 'Price quantization is investigated separately; declared tolerances are unchanged.'}
