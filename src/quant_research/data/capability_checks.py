"""Evidence-based admission checks for REAL_ONLY research and replay.

Status is derived from source-backed warehouse rows, never from configurable
PASS flags.  Unknown lineage, time travel and absence of a corporate-action
coverage calendar explicitly block affected capabilities.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re

import pandas as pd

from quant_research.clock import TradingClock


def verdict(*missing):
    values = list(dict.fromkeys(str(m) for m in missing if m))
    return {"status": "BLOCKED" if values else "PASS", "missing_evidence": values}


def _relation(db, name):
    return bool(db.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [name]).fetchone()[0])


def _verified_action_receipt(root, digest, symbol, day, available_at):
    """Conservatively verify ONE complete source response for symbol and day.

    Multipart histories are deliberately rejected until page-chain validation is
    implemented. A mere matching hash or corporate-actions URL proves nothing
    about completeness, requested symbol, covered dates or when it was known.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", str(digest)):
        return False
    path = Path(root) / "objects" / digest
    if not path.is_file():
        return False
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        return False
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return False
    if (not isinstance(body, dict) or not isinstance(body.get('corporate_actions'), dict)
            or body.get('next_page_token')):
        return False
    for folder in (Path(root) / "receipts", Path(root) / "yahoo" / "receipts"):
        for receipt_path in folder.glob("*.json"):
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                params = receipt.get('params') or {}
                fetched = pd.Timestamp(receipt.get('fetched_at'))
                available = pd.Timestamp(available_at)
                if (receipt.get('sha256') != digest
                        or receipt.get('url') != 'https://data.alpaca.markets/v1/corporate-actions'
                        or fetched.tzinfo is None or available.tzinfo is None
                        or fetched > available or params.get('page_token')
                        or symbol not in str(params.get('symbols', '')).split(',')
                        or not str(params.get('start', '')) <= day <= str(params.get('end', ''))):
                    continue
                return True
            except (OSError, ValueError, TypeError):
                continue
    return False


def assess(db, prices, raw_root, asof, cutoff):
    """Return capability prerequisites independently of vendor subscription.

    ``asof`` and ``cutoff`` are the accepted dataset's dates/times.  A current
    snapshot downloaded in 2026 cannot be retroactively known in 2017.
    No flag changes here grant access to real trading or a brokerage account.
    """
    ids = set(prices.security_id.astype(str))
    dates = sorted(set(pd.to_datetime(prices.date).dt.date))
    raw = set(prices.adjustment_basis) == {"raw"}
    current = prices.loc[pd.to_datetime(prices.date).dt.date == pd.Timestamp(asof).date()].copy()
    present = ids == set(current.security_id.astype(str))
    source = set(prices.source)
    cutoff = pd.Timestamp(cutoff).tz_convert("UTC")
    clock = TradingClock()
    missing = {"raw_prices": [] if raw else ["source-verified unadjusted OHLCV"]}

    # Historical decision availability must be established by first-observed
    # response timestamps, NOT by close time or the date of a retrieved bar.
    when = pd.to_datetime(prices.available_at, utc=True)
    signal_times = pd.to_datetime([clock.close(d) + clock.delay for d in pd.to_datetime(prices.date).dt.date], utc=True)
    history_known = bool((when <= signal_times).all())
    missing["historical_time"] = [] if history_known else ["historical publication-time evidence: historic prices first observed after their signal times"]

    registered = set()
    if _relation(db, "securities"):
        rows = db.execute("SELECT security_id,source,quality_flag FROM securities").fetchall()
        registered = {str(sid) for sid, src, q in rows if src in source and
                      "IDENTITY_VERIFIED" in str(q).split("|") and "UNVERIFIED" not in str(q)}
    missing["identity"] = [] if ids and ids <= registered and all(not x.startswith("SYMBOL-UNVERIFIED:") for x in ids) else ["provider-backed permanent identity with effective-dated symbol mapping"]

    # Membership is PIT only if eligibility was published/observed by decision time.
    universe_dates = set()
    latest_ids = set()
    if _relation(db, "universe_daily"):
        u = db.execute("SELECT date,security_id,is_eligible,available_at,quality_flag FROM universe_daily WHERE date>=? AND date<=?", [str(dates[0]), str(dates[-1])]).fetchall()
        for day, sid, eligible, at, q in u:
            label = str(q).split("|")
            if not eligible or "PIT_VERIFIED" not in label:
                continue
            t = pd.Timestamp(at)
            if t.tzinfo is None:
                continue
            if t <= pd.Timestamp(clock.close(day) + clock.delay):
                universe_dates.add((pd.Timestamp(day).date(), str(sid)))
            if pd.Timestamp(day).date() == pd.Timestamp(asof).date() and t <= cutoff:
                latest_ids.add(str(sid))
    historic_pairs = {(pd.Timestamp(d).date(), str(s)) for d, s in zip(prices.date, prices.security_id)}
    missing["historical_universe"] = [] if historic_pairs <= universe_dates else ["effective-dated historical investable universe and delistings"]
    missing["forward_universe"] = [] if present and ids <= latest_ids else ["prospectively recorded current universe eligibility"]

    # Corporate-action coverage is *not* inferred from zero event rows.
    # The original all-pages API response for each covered security/session is
    # necessary to prove that missing events really mean no event.
    certified = set()
    forward_certified = set()
    if _relation(db, "action_coverage_daily"):
        records = db.execute("SELECT date,security_id,source,raw_sha256,available_at,quality_flag FROM action_coverage_daily WHERE date>=? AND date<=?", [str(dates[0]), str(dates[-1])]).fetchall()
        root = Path(raw_root)
        # Only the exact security/date/symbol covered by the original provider
        # query can be certified. A generic API receipt cannot certify a full
        # asset history; multiple-page API histories remain blocked.
        symbols_by_key = {(str(row.security_id), str(pd.Timestamp(row.date).date())): str(row.symbol)
                          for row in prices.itertuples(index=False)}
        for day, sid, src, digest, at, q in records:
            day = str(pd.Timestamp(day).date())
            timestamp = pd.Timestamp(at)
            if src != "ALPACA" or timestamp.tzinfo is None or "COMPLETE_VERIFIED" not in str(q).split("|"):
                continue
            symbol = symbols_by_key.get((str(sid), day))
            if not symbol or not _verified_action_receipt(root, digest, symbol, day, timestamp):
                continue
            if timestamp <= pd.Timestamp(clock.close(day) + clock.delay):
                certified.add((pd.Timestamp(day).date(), str(sid)))
            if timestamp <= cutoff:
                forward_certified.add((pd.Timestamp(day).date(), str(sid)))

    missing["actions"] = [] if historic_pairs <= certified else ["complete corporate action coverage observed by each historic decision time"]
    current_pairs = {(pd.Timestamp(d).date(), str(s)) for d, s in zip(current.date, current.security_id)}
    missing["forward_actions"] = [] if current_pairs <= forward_certified else ["source-backed current corporate-action coverage known by actual decision cutoff"]

    # A frozen real model and decision are independent prerequisites.  A row in
    # runs does not prove a trained model or frozen pre-entry signal existed.
    frozen_models = set()
    decisions = False
    data_dir = Path(raw_root).resolve().parent
    def hash_file(relative_path, digest, prefix):
        if not re.fullmatch(r'[0-9a-f]{64}',str(digest)):
            return False
        folder = (data_dir / 'managed' / prefix).resolve()
        path = (data_dir / str(relative_path)).resolve()
        return (path.is_relative_to(folder) and path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest)
    if _relation(db, "model_attestations"):
        for model_id, sha, artifact_path, source_sha, fit_at, state in db.execute(
            "SELECT model_id,model_sha256,artifact_path,source_dataset_sha256,fit_at,status FROM model_attestations WHERE fit_at<=?",
            [cutoff.to_pydatetime()]).fetchall():
            if (state == 'SOURCE_VERIFIED' and hash_file(artifact_path, sha, 'models')
                    and source_sha and re.fullmatch(r'[0-9a-f]{64}',str(source_sha))):
                frozen_models.add(model_id)
    if frozen_models and _relation(db, "decision_attestations"):
        for model_id, sha, path, source_sha, frozen_at, state in db.execute(
            "SELECT model_id,decision_sha256,artifact_path,source_snapshot_sha256,frozen_at,status FROM decision_attestations WHERE session=? AND frozen_at<=?",
            [str(asof), cutoff.to_pydatetime()]).fetchall():
            if (state == 'HASH_VERIFIED' and model_id in frozen_models
                    and source_sha == hashlib.sha256(prices.to_json(orient='records',date_format='iso').encode()).hexdigest()
                    and hash_file(path, sha, 'decisions')):
                decisions = True
    missing["model"] = [] if frozen_models else ["source-linked frozen model bytes and SHA256 fitted before decision"]
    missing["decision"] = [] if decisions else ["unmodified, source-linked pre-entry decision archive"]

    # Signal can be frozen after the full SIP record arrives, provided the
    # observed data are still available before the *next* session opens.
    forward_times = pd.to_datetime(current.available_at, utc=True) if len(current) else pd.DatetimeIndex([], tz="UTC")
    next_open = clock.calendar.session_open(clock.calendar.next_session(str(asof)))
    observed_before_entry = bool(len(current) and (forward_times <= cutoff).all() and cutoff < next_open)
    missing["forward_clock"] = [] if observed_before_entry else ["verified actual feed arrival and decision cutoff before next open"]

    def combine(*parts):
        return verdict(*(reason for p in parts for reason in missing[p]))
    return {
        "historical_model": combine("historical_time", "identity", "historical_universe"),
        "industry_factors": verdict("as-filed, effective-dated industry classification"),
        "pit_fundamentals": verdict("original filing facts with SEC accession and accepted_at"),
        "historical_backtest": combine("historical_time", "identity", "historical_universe", "actions", *([] if raw else ["raw_prices"])),
        "forward_data": combine("identity", "forward_universe", "forward_actions", "forward_clock", *([] if raw else ["raw_prices"])),
        "forward_shadow": combine("identity", "forward_universe", "forward_actions", "forward_clock", "model", "decision", *([] if raw else ["raw_prices"])),
    }
