"""G13 read-only inspection of genuine, attested forward decisions.

A decision is never reconstructed from later prices. Only byte-hash verified
model and decision archives, the exact known-at-time raw SIP dataset and the
existing forward_shadow capability may release *research* candidate rows.
No broker connections, order placement, inference or trading advice.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from quant_research.policy import PolicyError

SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_SIGNALS = 100
_BANNED_FIELDS = frozenset({
    "actual_return", "actual_excess_return", "realized_return", "realized_pnl",
    "forward_return", "forward_excess_return", "label", "label_available_at",
    "target", "future_return", "net_pnl", "fill_price", "filled_at",
})


def _fail(code, explanation):
    raise PolicyError(code, explanation)


def _utc(value):
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError('Timezone omitted')
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        _fail('FROZEN_TIME_UNVERIFIED', 'Every model, feature and decision timestamp requires a verified UTC offset')


def _sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def _artifact(root: Path, relative: str, digest: str, directory: str):
    """Verify an archived file is inside the ONLY allowed managed namespace."""
    if not _sha(digest) or not isinstance(relative, str):
        _fail('FROZEN_ARCHIVE_INVALID', 'Archive path or SHA256 is missing')
    base = (root / 'data' / 'managed' / directory).resolve()
    target = (root / 'data' / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        _fail('FROZEN_ARCHIVE_UNAVAILABLE', 'Model/decision archive is missing or outside its managed directory')
    if target.stat().st_size > 20 * 1024 * 1024:
        _fail('FROZEN_ARCHIVE_TOO_LARGE', 'Archive exceeds the read-only verification limit')
    raw = target.read_bytes()
    if sha256(raw).hexdigest() != digest:
        _fail('FROZEN_ARCHIVE_CHANGED', 'Archived model/decision bytes do not match their attestation')
    return raw


def _session(value):
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value or parsed > datetime.now(timezone.utc).date():
            raise ValueError('Invalid session date')
    except (ValueError, TypeError):
        _fail('FROZEN_SESSION_INVALID', 'Requested session must be a nonfuture ISO exchange date')
    return value


def _candidate_rows(signals, *, session, frozen_at, clock, source_ids):
    """Validate orders-only payload; don't infer probabilities or position weights."""
    if not isinstance(signals, list) or len(signals) > MAX_SIGNALS:
        _fail('FROZEN_SIGNAL_SCHEMA_INVALID', 'Frozen signals must be a bounded list of at most 100 records')
    recorded = set()
    results = []
    close = clock.close(session)
    next_open = clock.window(session, 1).entry_time
    for signal in signals:
        if not isinstance(signal, dict) or _BANNED_FIELDS.intersection(signal):
            _fail('FROZEN_DECISION_LOOKAHEAD', 'A decision cannot contain realized outcomes, labels or fills')
        fields = {'security_id', 'symbol', 'sector', 'signal_time', 'feature_available_at',
                  'fit_time', 'exit_date', 'adv20', 'atr20', 'decision_eligible', 'adjustment_basis'}
        if fields - set(signal):
            _fail('FROZEN_SIGNAL_FIELDS_MISSING', 'Decision lacks mandatory risk and source fields')
        sid, symbol = signal['security_id'], signal['symbol']
        if (not isinstance(sid, str) or sid.startswith('SYMBOL-UNVERIFIED:') or
                not isinstance(symbol, str) or source_ids.get(sid) != symbol):
            _fail('FROZEN_SIGNAL_IDENTITY_INVALID', 'Security ID and symbol must match admitted source bars')
        if sid in recorded:
            _fail('FROZEN_SIGNAL_DUPLICATE', 'Duplicate stock candidates cannot be issued in one decision')
        recorded.add(sid)
        if signal['decision_eligible'] is not True or signal['adjustment_basis'] != 'raw':
            _fail('FROZEN_SIGNAL_NOT_ELIGIBLE', 'Signals must be individually eligible and use original raw prices')
        fit, available, issued = (_utc(signal[key]) for key in ('fit_time', 'feature_available_at', 'signal_time'))
        if not (fit <= issued and available <= issued and close < issued <= frozen_at < next_open):
            _fail('FROZEN_SIGNAL_TIME_INVALID', 'Model/feature availability and frozen signal time must precede entry')
        horizon = next((h for h in (1,3,5)
                        if signal['exit_date'] == clock.window(session, h).exit_time.date().isoformat()), None)
        if horizon is None:
            _fail('FROZEN_SIGNAL_EXIT_INVALID', 'Exit must match H1/H3/H5 exchange-session close')
        for name in ('adv20', 'atr20'):
            value = signal[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                _fail('FROZEN_SIGNAL_RISK_INVALID', 'ADV20 and ATR20 must be finite and positive')
        if not isinstance(signal['sector'], str) or not signal['sector'].strip() or signal['sector'] == 'UNKNOWN':
            _fail('FROZEN_SIGNAL_SECTOR_INVALID', 'Unverified industry classification cannot support sector limits')
        for optional, lower, upper in (('p_up', 0, 1), ('planned_weight', 0, .1)):
            if optional in signal:
                value = signal[optional]
                if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not lower <= value <= upper:
                    _fail('FROZEN_SIGNAL_OPTIONAL_INVALID', 'Optional score or weight must be an explicit finite value in range')
        results.append({
            'symbol': symbol, 'security_id': sid, 'sector': signal['sector'],
            'horizon': horizon, 'exit_date': signal['exit_date'],
            'signal_time_utc': issued.isoformat(),
            'probability_up': signal.get('p_up'), 'planned_weight': signal.get('planned_weight'),
            'adv20': signal['adv20'], 'atr20': signal['atr20'],
            'source_snapshot_verified': True,
        })
    if sum(x['planned_weight'] or 0 for x in results) > .5 + 1e-10:
        _fail('FROZEN_SIGNAL_PORTFOLIO_LIMIT', 'Explicit candidate weights exceed the research portfolio limit')
    return results


def inspect_frozen_decision(root, *, session=None, db='data/real_v21.duckdb'):
    """Return an evidence-gated candidate snapshot; never create or mutate state.

    No data -> a precise blocked response. An existing but malformed archive ->
    PolicyError, so callers cannot silently fall back to an older success.
    """
    root = Path(root).resolve()
    session = _session(session)
    target = (root / db).resolve()
    if not target.is_relative_to((root/'data').resolve()):
        _fail('FROZEN_DB_PATH_INVALID', 'Only project-local real data warehouses may be inspected')
    empty = {'status': 'BLOCKED', 'code': 'NO_ACCEPTED_FROZEN_DECISION', 'session_date_et': session,
             'candidates': [], 'candidate_count': 0, 'real_orders_enabled': False,
             'execution_ready': False, 'historical_pit_eligible': False}
    if not target.is_file():
        return {**empty, 'code': 'NO_REAL_DATA'}
    try:
        from quant_research.data.store import duckdb
    except ImportError:
        _fail('FROZEN_DATABASE_RUNTIME_UNAVAILABLE', 'Local DuckDB runtime is required to inspect real attestations')
    try:
        with duckdb.connect(str(target), read_only=True) as database:
            if session:
                row = database.execute('''SELECT session,decision_sha256,artifact_path,model_id,
                    source_snapshot_sha256,frozen_at,status FROM decision_attestations
                    WHERE session=? ORDER BY frozen_at DESC LIMIT 1''', [session]).fetchone()
            else:
                row = database.execute('''SELECT session,decision_sha256,artifact_path,model_id,
                    source_snapshot_sha256,frozen_at,status FROM decision_attestations
                    ORDER BY session DESC,frozen_at DESC LIMIT 1''').fetchone()
            if row is None:
                return empty
            day, digest, path, model_id, source_sha, at, state = row
            model = database.execute('''SELECT model_sha256,artifact_path,fit_at,
                source_dataset_sha256,status FROM model_attestations WHERE model_id=?''', [model_id]).fetchone()
    except (OSError, ValueError, duckdb.Error):
        _fail('FROZEN_STORE_UNAVAILABLE', 'Read-only decision attestation store is unavailable')
    day = str(day)
    _session(day)
    if state != 'HASH_VERIFIED' or not _sha(source_sha) or not model or model[-1] != 'SOURCE_VERIFIED':
        _fail('FROZEN_ATTESTATION_NOT_ACCEPTED', 'Decision/model attestation lacks accepted states or source SHA256')
    if not _sha(model[3]):
        _fail('FROZEN_MODEL_SOURCE_UNVERIFIED', 'Model training dataset needs a source SHA256')
    frozen = _utc(at)
    fitted = _utc(model[2])
    if not fitted <= frozen <= datetime.now(timezone.utc):
        _fail('FROZEN_MODEL_TIME_INVALID', 'Model must have been fitted by the recorded decision freeze time')
    raw = _artifact(root, path, digest, 'decisions')
    _artifact(root, model[1], model[0], 'models')
    try:
        decision = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        _fail('FROZEN_DECISION_JSON_INVALID', 'Archived decision cannot be decoded')
    if (not isinstance(decision, dict) or decision.get('session') != day or
            decision.get('model_id') != model_id or
            decision.get('source_snapshot_sha256') != source_sha or
            _utc(decision.get('frozen_at_utc')) != frozen):
        _fail('FROZEN_DECISION_LINK_MISMATCH', 'Decision fields do not match the immutable attestations')
    symbols = decision.get('universe_symbols')
    if (not isinstance(symbols, list) or not symbols or len(symbols) > 100 or
            any(not isinstance(x, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',x) for x in symbols) or
            len(symbols) != len(set(symbols))):
        _fail('FROZEN_UNIVERSE_REQUIRED', 'Explicit observed-source universe must be frozen with each decision')
    from quant_research.clock import TradingClock
    from quant_research.data.bundle import load_real_bundle
    clock = TradingClock()
    clock.session(day)
    if not clock.close(day) < frozen < clock.window(day, 1).entry_time:
        _fail('FROZEN_DECISION_TIME_INVALID', 'Decision freeze must occur after close and before next session opens')
    bundle = load_real_bundle(target, 'alpaca', asof=day, cutoff=frozen,
                              symbols=symbols, raw_root=root/'data/raw')
    bundle.require('forward_shadow')
    if bundle.metadata['feed'] != 'sip' or bundle.metadata['snapshot_sha256'] != source_sha:
        _fail('FROZEN_PRICE_SNAPSHOT_MISMATCH', 'Frozen decision must match precisely the source-observed SIP dataset')
    current = bundle.prices
    current = current.loc[current.date.astype(str) == day]
    source_ids = dict(zip(current.security_id.astype(str),current.symbol.astype(str)))
    candidates = _candidate_rows(decision.get('signals'), session=day, frozen_at=frozen,
                                  clock=clock, source_ids=source_ids)
    return {'status': 'ATTESTED_FORWARD_DECISION_RESEARCH_ONLY', 'session_date_et': day,
            'source_snapshot_sha256': source_sha, 'decision_sha256': digest,
            'model_sha256': model[0], 'model_id': model_id,
            'frozen_at_utc': frozen.isoformat(), 'candidates': candidates,
            'candidate_count': len(candidates),
            'forward_data_eligible': True, 'paper_replay_data_eligible': True,
            'historical_pit_eligible': False, 'real_orders_enabled': False,
            'execution_ready': False,
            'notice': 'Source-accepted frozen research decision only; no trade order, profitability or broker fill is implied.'}
