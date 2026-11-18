"""Immutable P5 validation reports for the L2 style model."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile


SCHEMA = "qdr.l2.validation-report.v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )


def _identity(report: dict) -> str:
    return sha256(_canonical(report).encode("utf-8")).hexdigest()


def freeze_validation_report_v1(root: Path, report: dict) -> dict:
    """Append one exact P5 validation artifact; identical evidence is idempotent."""
    if report.get("status") != "P5_RESEARCH_VALIDATION":
        raise ValueError("Only completed P5 research validation may be frozen")
    if report.get("real_orders_enabled") is not False:
        raise ValueError("P5 validation cannot enable real orders")
    asof = str(report.get("asof_session") or "")
    try:
        if date.fromisoformat(asof).isoformat() != asof:
            raise ValueError
    except ValueError:
        raise ValueError("Invalid P5 validation session") from None
    for key in ("source_snapshot_sha256", "label_bundle_sha256"):
        if not _SHA.fullmatch(str(report.get(key) or "")):
            raise ValueError("P5 validation requires " + key)
    rows = report.get("qualification")
    if not isinstance(rows, list) or len(rows) != 21:
        raise ValueError("P5 validation requires exact 7x3 qualification rows")

    payload = {
        **report,
        "schema": SCHEMA,
    }
    identity = _identity(payload)
    record = {
        **payload,
        "identity": identity,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    root = Path(root).resolve()
    folder = root / "outputs/l2_validation" / asof / identity
    target = folder / "manifest.json"
    if target.is_file():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing.get("identity") == identity:
            return existing
        raise FileExistsError("P5_VALIDATION_IDENTITY_CONFLICT")
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=folder,
        prefix=".manifest-", suffix=".json", delete=False
    ) as handle:
        handle.write(_canonical(record))
        temp = Path(handle.name)
    try:
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return record


def _verify(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    identity = data.pop("identity", None)
    frozen = data.pop("frozen_at_utc", None)
    if not identity or not frozen or _identity(data) != identity:
        raise ValueError("P5_VALIDATION_REPORT_IDENTITY_MISMATCH")
    return {**data, "identity": identity, "frozen_at_utc": frozen}


def load_latest_validation_v1(root: Path, *, asof: str | None = None) -> dict:
    """Load newest integrity-checked P5 report, optionally for one session."""
    base = Path(root).resolve() / "outputs/l2_validation"
    if not base.is_dir():
        raise FileNotFoundError("L2_P5_VALIDATION_REPORT_NOT_FOUND")
    sessions = [asof] if asof else sorted(
        (p.name for p in base.iterdir() if p.is_dir()), reverse=True
    )
    for session in sessions:
        folder = base / str(session)
        if not folder.is_dir():
            continue
        candidates = []
        for identity_dir in folder.iterdir():
            path = identity_dir / "manifest.json"
            if path.is_file():
                record = _verify(path)
                candidates.append(record)
        if candidates:
            return max(candidates, key=lambda item: item["frozen_at_utc"])
    raise FileNotFoundError("L2_P5_VALIDATION_REPORT_NOT_FOUND")
