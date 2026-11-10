"""Bounded G5 daily real-data orchestration.

This module is deliberately an orchestration layer: it does not create market
data and it never turns an archived session into a current trading event.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from quant_research.clock import TradingClock
from quant_research.data.catalog import write_catalog
from quant_research.data.close_snapshot import capture, latest_ready_session
from quant_research.data.http import atomic_write
from quant_research.policy import PolicyError
from .operation_lock import operation_lock


def _code(exc):
    """Return a non-sensitive, stable failure label."""
    return str(getattr(exc, "code", type(exc).__name__))


def _window(now, clock=None):
    """Return the one XNYS session currently eligible for G5, or raise."""
    clock = clock or TradingClock()
    day = latest_ready_session(clock, now)
    ready_at = clock.close(day) + timedelta(minutes=20)
    position = clock.calendar.sessions.get_loc(day)
    sessions = clock.calendar.sessions
    if position + 1 >= len(sessions):
        raise PolicyError("XNYS_CALENDAR_EXHAUSTED", "No next XNYS session is available")
    next_open = clock.calendar.session_open(sessions[position + 1]).to_pydatetime()
    if not (ready_at <= now < next_open):
        raise PolicyError("DAILY_WINDOW_CLOSED", "The delayed close-to-next-open window is not open")
    return day, ready_at, next_open


def _write(path, manifest):
    atomic_write(path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode())


def _stage(manifest, path, name, operation):
    item = {"status": "RUNNING"}
    manifest["stages"][name] = item
    _write(path, manifest)
    try:
        result = operation()
        item["status"] = "COMPLETED"
        if isinstance(result, dict):
            # Stage details are restricted to already-structured metadata.
            item["result"] = result
        manifest["stages"][name] = item
        _write(path, manifest)
        return True, result
    except Exception as exc:
        item.update(status="BLOCKED", code=_code(exc))
        manifest["stages"][name] = item
        manifest.update(status="BLOCKED", blocking_stage=name,
                        finished_at_utc=datetime.now(timezone.utc).isoformat())
        _write(path, manifest)
        print(json.dumps({"run_id": manifest["run_id"], "status": "BLOCKED",
                          "stage": name, "code": item["code"], "output": str(path.parent)}), flush=True)
        return False, None


def execute(args):
    """Keep duplicate scheduler invocations out of the same operating sequence."""
    root, run_id = Path.cwd().resolve(), str(uuid4())
    with operation_lock(root, "daily_ops", "daily-ops", run_id) as ownership:
        return _execute_locked(args, root, run_id, ownership)


def _execute_locked(args, root, run_id, ownership):
    """Run maintenance, freeze, observation and catalog for the current window.

    ``args.offline`` is consumed by maintenance; ``args.env_file`` is handled
    by the CLI before dispatch and is intentionally not read here.
    """
    output = root / "outputs" / "daily_ops" / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = output / "manifest.json"
    manifest = {
        "run_id": output.name,
        "workflow": "daily-ops",
        "policy": "REAL_ONLY",
        "status": "RUNNING",
        "operation_token": ownership["token"],
        "recovered_lock": ownership["recovered_lock"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "offline": args.offline,
        "stages": {name: {"status": "NOT_RUN"} for name in
                   ("maintain-data", "capture", "daily-observation", "data-catalog")},
        "real_orders_enabled": False,
    }
    _write(manifest_path, manifest)

    try:
        now = datetime.now(timezone.utc)
        day, ready_at, next_open = _window(now)
        session = day.date().isoformat()
        manifest.update(session_date_et=session, window_ready_at_utc=ready_at.isoformat(),
                        next_open_utc=next_open.isoformat(), now_utc=now.isoformat())
        _write(manifest_path, manifest)
    except Exception as exc:
        manifest.update(status="BLOCKED", code=_code(exc), finished_at_utc=datetime.now(timezone.utc).isoformat())
        _write(manifest_path, manifest)
        print(json.dumps({"run_id": manifest["run_id"], "status": "BLOCKED",
                          "stage": "clock", "code": manifest["code"], "output": str(output)}), flush=True)
        return 4

    maintenance_id = str(uuid4())
    manifest["maintenance_run_id"] = maintenance_id
    maintenance_args = SimpleNamespace(
        config=root / "configs" / "data_maintenance.yaml", cadence="daily",
        groups="prices,actions", end=session, full=False,
        offline=bool(getattr(args, "offline", False)),
        run_id=maintenance_id,
    )
    from .maintenance import execute as maintain
    def update():
        code = maintain(maintenance_args)
        if code != 0:
            raise PolicyError("DAILY_MAINTENANCE_BLOCKED", "Review the maintenance manifest before retrying")
        return {"exit_code": code, "run_id": maintenance_id}

    ok, _ = _stage(manifest, manifest_path, "maintain-data", update)
    if not ok:
        return 4

    from quant_research.workflow import daily_observation

    ok, captured = _stage(manifest, manifest_path, "capture", lambda: capture(root, session))
    if not ok:
        return 4
    snapshot, inserted = captured
    manifest["capture_sha256"] = snapshot["capture_sha256"]
    manifest["stages"]["capture"]["result"] = {"inserted": bool(inserted), "capture_sha256": snapshot["capture_sha256"]}
    _write(manifest_path, manifest)

    def observe():
        # A repeat with the same frozen SHA reuses the existing report, while
        # this daily_ops run still receives its own attempt manifest.
        try:
            previous = daily_observation.latest_report(root, session)
            if previous.get("capture_sha256") == snapshot["capture_sha256"]:
                return {"reused": True, "run_id": previous["run_id"], "capture_sha256": snapshot["capture_sha256"]}
        except PolicyError as exc:
            if exc.code != "DAILY_OBSERVATION_NOT_FOUND":
                raise
        generated = daily_observation.generate(root, session)
        return {"reused": False, "run_id": generated["run_id"], "capture_sha256": generated["capture_sha256"]}

    ok, _ = _stage(manifest, manifest_path, "daily-observation", observe)
    if not ok:
        return 4
    def catalog():
        folder, result = write_catalog(root)
        if result["cache_hash_failures"]:
            raise PolicyError("CATALOG_HASH_MISMATCH", "Catalog found corrupt source objects")
        return {"catalog_snapshot": folder.relative_to(root).as_posix()}

    ok, catalog_result = _stage(manifest, manifest_path, "data-catalog", catalog)
    if not ok:
        return 4
    manifest.update(status="COMPLETED", catalog_snapshot=catalog_result["catalog_snapshot"],
                    finished_at_utc=datetime.now(timezone.utc).isoformat())
    _write(manifest_path, manifest)
    print(json.dumps({"run_id": manifest["run_id"], "status": manifest["status"],
                      "session_date_et": session, "output": output.as_posix()}, ensure_ascii=False))
    return 0
