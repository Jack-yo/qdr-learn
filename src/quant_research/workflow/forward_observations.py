"""Read-only inventory for the prospective forward-observation page.

This module deliberately has no paper-ledger/account dependency.  The close
snapshot store is an observation archive, not an account or execution ledger.
"""
from contextlib import closing
from pathlib import Path
import sqlite3

from quant_research.clock import TradingClock
from quant_research.data.close_snapshot import STORE, read_snapshot
from quant_research.policy import PolicyError


_PREREQUISITES = [
    "prospective registry",
    "accepted identities & actions",
    "frozen eligible model",
    "frozen pre-entry decision",
]


def _status(registered_count):
    return {
        "status": "BLOCKED",
        "prerequisites": list(_PREREQUISITES),
        "observations": {
            "registered_count": registered_count,
            "verified_displayed_count": 0,
            "observation_dates": [],
            "snapshots": [],
            "display_scope": "LATEST_UP_TO_20_ARCHIVED_SNAPSHOTS",
            "missing_xnys_sessions": [],
            "missing_scope": "BETWEEN_FIRST_AND_LAST_DISPLAYED_EXCLUSIVE",
        },
        "account": {"cash": None, "equity": None, "positions": None, "fills": None},
        "execution_ready": False,
        "real_orders_enabled": False,
    }


def _blocked(code, message, registered_count=0):
    return {**_status(registered_count), "error": {"code": code, "message": message}}


def _missing_sessions(dates):
    if len(dates) < 2:
        return []
    clock = TradingClock()
    first, last = dates[0], dates[-1]
    sessions = clock.calendar.sessions_in_range(first, last)
    displayed = set(dates)
    return [session.date().isoformat() for session in sessions if session.date().isoformat() not in displayed]


def inventory(root):
    """Inventory archived real observations without reading paper-account state.

    The database registration count is intentionally distinct from the number
    of snapshots that could be verified and displayed.  Any selected snapshot
    that cannot be verified blocks the response rather than being skipped.
    """
    root = Path(root).resolve()
    path = root / STORE
    if not path.is_file():
        return _blocked("NO_ARCHIVED_OBSERVATIONS", "No archived close-observation store is present")

    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as database:
            database.execute("BEGIN")
            row = database.execute("SELECT COUNT(*) FROM snapshots").fetchone()
            registered = int(row[0])
            date_rows = database.execute(
                "SELECT session_date FROM snapshots ORDER BY session_date DESC LIMIT 20"
            ).fetchall()
    except (sqlite3.DatabaseError, OSError):
        return _blocked("CLOSE_SNAPSHOT_STORE_CORRUPT", "The close-observation archive cannot be read", None)

    # An installed but empty archive is a valid zero-observation state.
    if not date_rows:
        return _blocked("NO_ARCHIVED_OBSERVATIONS", "The close-observation archive is empty", registered)

    snapshots = []
    try:
        clock = TradingClock()
        for (session_date,) in date_rows:
            if not isinstance(session_date, str) or clock.session(session_date).date().isoformat() != session_date:
                raise PolicyError("CLOSE_SNAPSHOT_INVALID_DATE", "Archived session date is invalid")
            snapshot = read_snapshot(root, session_date)
            if snapshot["session_date_et"] != session_date:
                raise PolicyError("CLOSE_SNAPSHOT_INVALID_DATE", "Snapshot date differs from its archive key")
            snapshots.append({
                "session_date": session_date,
                "source": snapshot["source"],
                "frozen_at_utc": snapshot["frozen_at_utc"],
                "next_open_utc": snapshot["next_open_utc"],
                "rows": len(snapshot["rows"]),
                "capture_sha256": snapshot["capture_sha256"],
                "source_snapshot_sha256": snapshot["source_snapshot_sha256"],
            })
    except (PolicyError, KeyError, TypeError, ValueError, OSError, sqlite3.Error) as exc:
        code = getattr(exc, "code", "CLOSE_SNAPSHOT_INVALID")
        return _blocked(code, "A selected close observation failed verification", registered)

    dates = sorted(item["session_date"] for item in snapshots)
    result = _status(registered)
    result["observations"].update({
        "verified_displayed_count": len(snapshots),
        "observation_dates": dates,
        "snapshots": snapshots,
        "missing_xnys_sessions": _missing_sessions(dates),
    })
    return result
