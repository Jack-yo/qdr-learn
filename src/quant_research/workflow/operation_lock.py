"""Process-owned operations locks with persistent, recoverable owner markers."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from quant_research.data.http import atomic_write
from quant_research.policy import PolicyError


KINDS = {"daily_ops": "DAILY_OPS_LOCKED", "maintenance": "MAINTENANCE_LOCKED"}
WORKFLOWS = {"daily_ops": {"daily-ops"}, "maintenance": {"maintenance", "ops-backup"}}
RUN_FOLDERS = {"daily-ops": "daily_ops", "maintenance": "maintenance"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_owner(data, kind):
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("kind") != kind:
        return False
    if data.get("workflow") not in WORKFLOWS[kind] or type(data.get("pid")) is not int or data["pid"] <= 0:
        return False
    try:
        return all(str(UUID(data[key])) == data[key] for key in ("run_id", "token"))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def _read_owner(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _acquire(handle, code):
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise PolicyError(code, "An operations process holds the live lock or the guard is unavailable") from None


def _interrupt_run(root, owner):
    folder = RUN_FOLDERS.get(owner["workflow"])
    if folder is None:
        return "NO_ATTEMPT_MANIFEST"
    path = root / "outputs" / folder / owner["run_id"] / "manifest.json"
    if path.resolve() != path:
        return "MANIFEST_PATH_REJECTED"
    if not path.is_file():
        return "MANIFEST_MISSING"
    data = _read_owner(path)
    if not isinstance(data, dict) or data.get("operation_token") != owner["token"]:
        return "MANIFEST_OWNER_UNVERIFIED"
    if data.get("status") != "RUNNING":
        return "ALREADY_TERMINAL"
    for stage in [*data.get("stages", {}).values(), *data.get("tasks", [])]:
        if stage["status"] == "RUNNING":
            stage.update(status="INTERRUPTED", code="PROCESS_ENDED_BEFORE_STAGE_COMPLETION")
    data.update(status="INTERRUPTED", recovered_at_utc=_now(), interruption_code="PROCESS_LOCK_RELEASED")
    atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False).encode())
    return "INTERRUPTED"


def _publish_exclusive(path, body, code):
    # Publish a complete owner file in one step without overwriting a legacy writer.
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_bytes(body)
    try:
        if os.name == "nt":
            # Windows rename fails if the destination already exists.
            temporary.rename(path)
        else:
            os.link(temporary, path)
    except FileExistsError:
        raise PolicyError(code, "An existing owner marker must be preserved") from None
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def operation_lock(root, kind, workflow, run_id, *, recover=True):
    root = Path(root).resolve()
    base = root / "data/catalog"
    base.mkdir(parents=True, exist_ok=True)
    marker = base / f".{kind}.lock"
    guard = base / f".{kind}.guard"
    code = KINDS[kind]
    owner = {"schema": 1, "kind": kind, "workflow": workflow, "run_id": str(run_id),
             "token": str(uuid4()), "pid": os.getpid(), "created_at_utc": _now()}
    if not _valid_owner(owner, kind) or any(path.resolve() != path for path in (marker, guard)):
        raise PolicyError(code, "Operations lock scope is invalid")

    # The guard stays at a stable path. The kernel releases it when the owner exits.
    with guard.open("a+b") as handle:
        _acquire(handle, code)
        previous = None
        if marker.exists():
            old = _read_owner(marker)
            if not recover or not _valid_owner(old, kind):
                raise PolicyError(code, "Existing owner marker cannot be safely recovered")
            previous = {
                "kind": old["kind"], "workflow": old["workflow"], "run_id": old["run_id"],
                "pid": old["pid"], "manifest_status": _interrupt_run(root, old),
            }
        body = json.dumps(owner, indent=2).encode()
        if previous:
            atomic_write(marker, body)
        else:
            _publish_exclusive(marker, body, code)
        try:
            yield {"token": owner["token"], "recovered_lock": previous}
        finally:
            if _read_owner(marker) == owner:
                marker.unlink()
