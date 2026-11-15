"""L1 V3 on-demand research runtime, bounded memory memo and immutable snapshots.

No trading, no automatic broker calls. A GET can save an idempotent audit snapshot
only if a real as-of market scan succeeded. No full market-history warehouse.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
import threading
import time

from quant_research.clock import TradingClock
from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.workflow.l1_probability_v3 import analyze_l1_v3

_MEMO = {}
_LOCK = threading.RLock()
_MEMO_TTL = 600
_MAX_MEMO = 3
_CORE_SYMBOLS = ("SPY", "RSP", "IWM", "HYG", "LQD")


def latest_completed_session(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware now required")
    now = now.astimezone(timezone.utc)
    clock = TradingClock()
    session = clock.calendar.date_to_session(now.date(), direction="previous")
    while clock.close(session) + clock.delay > now:
        session = clock.calendar.previous_session(session)
    return session.date().isoformat()


def _compact(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def save_research_snapshot(root, payload):
    """Append-only small evidence. Caller has obtained real provider receipts."""
    if (payload.get("schema") != "qdr.l1.probability.v3" or
            payload.get("historical_pit_verified") is not False or
            payload.get("status") != "RESEARCH_ONLY" or
            payload.get("execution_eligible") is not False):
        raise ValueError("Not a qualifying research-only snapshot")
    day = str(payload.get("asof_session", ""))
    if len(day) != 10 or day[4] != "-" or day[7] != "-":
        raise ValueError("Invalid session day")
    if not payload.get("source_receipts"):
        raise ValueError("No independently fetched source receipt")
    # No publication of certified probabilities even in an audit snapshot.
    if any(v.get("admitted_probabilities") is not None
           for v in payload.get("horizons", {}).values()):
        raise ValueError("Admitted probabilities are forbidden without PIT audit")
    # The server response may contain an archive receipt from a prior call.
    # Remove that runtime-only field so repeated requests are idempotent.
    archived = {key: value for key, value in payload.items()
                if key not in ("research_snapshot","outcome_status")}
    body = _compact(archived)
    digest = sha256(body).hexdigest()
    folder = Path(root) / "outputs" / "l1_v3_research" / day
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest[:24] + ".json")
    try:
        with target.open("xb") as file:
            file.write(body)
    except FileExistsError:
        if sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError("Snapshot hash conflict")
    return {"path": str(target.relative_to(Path(root))),
            "sha256": digest, "status": "IMMUTABLE_RESEARCH_ONLY"}


def recent_research_snapshots(root, limit=15):
    """Read-only archive index. Never relabel this as a live OOS scorecard."""
    folder = Path(root) / "outputs" / "l1_v3_research"
    if not folder.exists():
        return []
    found = []
    for path in sorted(folder.glob("20??-??-??/*.json"), reverse=True)[:max(limit * 4, 40)]:
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if (data.get("schema") != "qdr.l1.probability.v3" or
                    data.get("status") != "RESEARCH_ONLY" or
                    data.get("execution_eligible") is not False):
                continue
            found.append({"asof_session": data.get("asof_session"),
                         "model_version": data.get("model_version"),
                         "sha256": sha256(raw).hexdigest(),
                         "horizons_available": sorted(int(h) for h, item in data.get("horizons", {}).items()
                                                      if item.get("research_estimates") is not None),
                         "status": "RESEARCH_ONLY"})
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if len(found) >= limit:
            break
    return found


def current_l1_v3(root, *, refresh=False, sources=None, now=None, freeze=False):
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timezone-aware now required")
    day = latest_completed_session(stamp)
    memo_key = (str(Path(root).resolve()), day)
    # Only memoize normal production requests, never injected test providers.
    eligible_memo = sources is None and now is None and not refresh
    if eligible_memo:
        with _LOCK:
            item = _MEMO.get(memo_key)
            if item and item[0] > time.monotonic():
                result = item[1]
                if freeze:
                    save_research_snapshot(root, result)
                return result
    feed = sources or LiveSources(root)
    # Five core ETFs only, rather than duplicating V2's 19-symbol full scan.
    # 2500 calendar days (~6.8 years) may be reduced by provider entitlement.
    raw, receipts = feed.bars(days=2500, symbols=_CORE_SYMBOLS, refresh=refresh)
    if not receipts:
        raise SourceUnavailable("V3_SOURCE_RECEIPTS_MISSING")
    output = analyze_l1_v3(raw, receipts=receipts, asof_limit=day)
    if output["asof_session"] != day:
        raise SourceUnavailable("V3_NOT_LATEST_COMPLETED_SESSION")
    output["fetched_at"] = receipts[-1].get("fetched_at")
    output["data_feed"] = receipts[-1].get("feed")
    output["source_fingerprint"] = sha256(_compact(receipts)).hexdigest()
    output["snapshot_status"] = "ON_DEMAND_NOT_DAILY_SCHEDULED"
    if freeze:
        output["research_snapshot"] = save_research_snapshot(root, output)
        from quant_research.workflow.l1_v3_outcomes import settle_due_research
        output["outcome_status"] = settle_due_research(
            root, raw, latest_session=day, limit=30)
    if sources is None and now is None:
        with _LOCK:
            _MEMO[memo_key] = (time.monotonic() + _MEMO_TTL, output)
            while len(_MEMO) > _MAX_MEMO:
                _MEMO.pop(next(iter(_MEMO)))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="L1 V3 audit-only scenario probabilities")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--save-snapshot", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = current_l1_v3(args.root, refresh=args.refresh,
                               freeze=args.save_snapshot)
        print(_compact({
            "status": result["status"],
            "asof_session": result["asof_session"],
            "horizons": {h: {"status": v["status"],
                             "qualified": v["qualification"]["admitted"],
                             "research_estimates": v.get("research_estimates"),
                             "validation": v.get("validation")}
                         for h, v in result["horizons"].items()},
            "snapshot": result.get("research_snapshot")
        }).decode())
        return 0
    except (SourceUnavailable, ValueError, OSError) as exc:
        print(_compact({"status": "BLOCKED",
                        "code": getattr(exc, "code", type(exc).__name__)}).decode())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
