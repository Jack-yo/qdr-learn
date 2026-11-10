"""Append-only pre-entry observations of the reviewed Alpaca ETF profile."""
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.policy import PolicyError
from .bundle import load_real_bundle, verify_lineage


STORE = Path("data/managed/close_snapshots/observations.sqlite3")
PRICE_FIELDS = [
    "symbol", "security_id", "date", "open", "high", "low", "close", "volume",
    "event_time", "available_at", "ingested_at", "raw_sha256",
]


def latest_ready_session(clock, now):
    """Latest XNYS session after the delayed daily-bars observation window opens."""
    local_day = now.astimezone(clock.calendar.tz).date()
    day = clock.calendar.date_to_session(local_day, direction="previous")
    if clock.close(day) + timedelta(minutes=20) > now:
        day = clock.calendar.previous_session(day)
    return day


def _decode(row):
    payload, digest = row
    if hashlib.sha256(payload.encode()).hexdigest() != digest:
        raise PolicyError("CLOSE_SNAPSHOT_HASH_MISMATCH", "Frozen observation failed SHA256 verification")
    return {**json.loads(payload), "capture_sha256": digest}


def read_snapshot(root, asof=None):
    path = Path(root).resolve() / STORE
    if not path.is_file():
        raise PolicyError("NO_CLOSE_SNAPSHOT", "Capture a current session before the next open")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
        if asof is None:
            row = database.execute(
                "SELECT payload,sha256 FROM snapshots ORDER BY session_date DESC LIMIT 1"
            ).fetchone()
        else:
            row = database.execute(
                "SELECT payload,sha256 FROM snapshots WHERE session_date=?", [asof]
            ).fetchone()
    if row is None:
        raise PolicyError("NO_CLOSE_SNAPSHOT", "No frozen observation for the requested session")
    snapshot = _decode(row)
    prices = pd.DataFrame(snapshot["rows"]).assign(
        source=snapshot["source"], feed=snapshot["feed"],
        adjustment_basis=snapshot["adjustment_basis"],
    )
    verify_lineage(prices, Path(root).resolve() / "data/raw")
    return snapshot


def capture(root, asof=None):
    root = Path(root).resolve()
    clock = TradingClock()
    now = datetime.now(timezone.utc)
    if asof is None:
        day = latest_ready_session(clock, now)
    else:
        day = clock.session(date.fromisoformat(asof))
    session = day.date().isoformat()
    path = root / STORE
    if path.is_file():
        try:
            return read_snapshot(root, session), False
        except PolicyError as exc:
            if exc.code != "NO_CLOSE_SNAPSHOT":
                raise
    ready_at = clock.close(day) + timedelta(minutes=20)
    if now < ready_at:
        raise PolicyError("CLOSE_WINDOW_NOT_READY", "Wait until 20 minutes after the completed session")
    next_open = clock.window(day, 1, now=now).entry_time
    if now >= next_open:
        raise PolicyError("CLOSE_WINDOW_EXPIRED", "Past sessions cannot be frozen after their next open")
    bundle = load_real_bundle(root / "data/real_v21.duckdb", "alpaca", session, now,
                              start=session, raw_root=root / "data/raw")
    bundle.require("observation")
    bundle.require("raw_prices")
    prices = bundle.prices[PRICE_FIELDS].sort_values("symbol")
    if (prices.event_time != clock.close(day)).any():
        raise PolicyError("CLOSE_EVENT_TIME_MISMATCH", "Daily price event does not match the session close")

    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as database, database:
        database.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            session_date TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL
        )""")
        database.execute("BEGIN IMMEDIATE")
        existing = database.execute(
            "SELECT payload,sha256 FROM snapshots WHERE session_date=?", [session]
        ).fetchone()
        if existing:
            return _decode(existing), False
        frozen_at = datetime.now(timezone.utc)
        if frozen_at >= next_open:
            raise PolicyError("CLOSE_WINDOW_EXPIRED", "Verification completed after the next open")
        meta = bundle.metadata
        record = {
            "status": "OBSERVATION_FROZEN", "source": "ALPACA", "feed": "sip",
            "adjustment_basis": "raw", "session_date_et": session,
            "capture_started_at_utc": now.isoformat(), "frozen_at_utc": frozen_at.isoformat(),
            "next_open_utc": next_open.isoformat(), "published_at_utc": None,
            "availability_basis": "VERIFIED_LOCAL_FETCH_RECEIPT",
            "source_snapshot_sha256": meta["snapshot_sha256"],
            "source_provenance": meta["source_provenance"],
            "scope": "EXPLICIT_ETF_OBSERVATION_ONLY", "identity_status": "UNVERIFIED",
            "decision_eligible": False, "historical_decision_eligible": False,
            "research_grade": False, "execution_ready": False, "real_orders_enabled": False,
            "rows": prices.to_dict(orient="records"),
        }
        payload = json.dumps(record, sort_keys=True, default=lambda value: value.isoformat(), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        database.execute("INSERT INTO snapshots VALUES (?,?,?)", [session, payload, digest])
    return _decode((payload, digest)), True


def execute(args):
    record, inserted = capture(Path.cwd(), args.asof)
    print(json.dumps({**record, "inserted": inserted}))
    return 0
