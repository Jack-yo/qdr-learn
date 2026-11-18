"""Immutable P5 validation reports for the L2 style model."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS


SCHEMA = "qdr.l2.validation-report.v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )


def _identity(report: dict) -> str:
    return sha256(_canonical(report).encode("utf-8")).hexdigest()




def _validate_qualification(report: dict) -> None:
    rows = report.get("qualification")
    if not isinstance(rows, list) or len(rows) != len(STYLE_IDS) * len(HORIZONS):
        raise ValueError("P5 validation requires exact 7x3 qualification rows")
    expected = {(style, horizon) for style in STYLE_IDS for horizon in HORIZONS}
    identities = []
    admitted = 0
    for row in rows:
        style = row.get("style_id")
        try:
            horizon = int(row.get("horizon"))
        except (TypeError, ValueError):
            raise ValueError("Invalid P5 qualification horizon") from None
        identities.append((style, horizon))
        status = row.get("qualification_status")
        if status not in {"RESEARCH_ONLY", "OOS_VALIDATED", "MODEL_ADMITTED"}:
            raise ValueError("Invalid P5 qualification status")
        if row.get("decision_eligible") is not False or row.get("real_orders_enabled") is not False:
            raise ValueError("P5 qualification cannot enable execution")
        is_admitted = row.get("model_admitted") is True
        if is_admitted:
            admitted += 1
            if (
                status != "MODEL_ADMITTED"
                or row.get("oos_gate_passed") is not True
                or row.get("forward_gate_passed") is not True
            ):
                raise ValueError("MODEL_ADMITTED row lacks required evidence gates")
        elif status == "MODEL_ADMITTED":
            raise ValueError("MODEL_ADMITTED status requires model_admitted=true")
    if set(identities) != expected:
        raise ValueError("P5 qualification grid identity mismatch")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("P5 validation summary is required")
    if int(summary.get("total_units", -1)) != len(expected):
        raise ValueError("P5 validation summary total-unit mismatch")
    if int(summary.get("model_admitted_units", -1)) != admitted:
        raise ValueError("P5 validation summary admitted-unit mismatch")
    enabled = summary.get("model_admission_enabled")
    if type(enabled) is not bool:
        raise ValueError("P5 model-admission switch state is required")
    if admitted and not enabled:
        raise ValueError("P5 report cannot admit models while admission switch is disabled")


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
    for key in (
        "source_snapshot_sha256", "label_bundle_sha256",
        "feature_bundle_sha256"
    ):
        if not _SHA.fullmatch(str(report.get(key) or "")):
            raise ValueError("P5 validation requires " + key)
    if report.get("historical_feature_pit_attested") is not True:
        raise ValueError("P5 validation requires verified historical feature PIT")
    _validate_qualification(report)

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
        existing = _verify(target)
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
    _validate_qualification(data)
    feature_sha=data.get("feature_bundle_sha256")
    feature_pit=data.get("historical_feature_pit_attested")
    if feature_sha is None and feature_pit is None:
        # Legacy P5 reports remain inspectable but can never be used as
        # model-admission evidence by P6.
        data={**data,
              "historical_feature_pit_attested":False,
              "legacy_feature_evidence_missing":True}
    elif (
        not _SHA.fullmatch(str(feature_sha or ""))
        or feature_pit is not True
    ):
        raise ValueError("P5_VALIDATION_FEATURE_EVIDENCE_INVALID")
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


def load_validation_on_or_before_v1(root: Path, asof: str) -> dict:
    """Load newest integrity-checked report whose session is <= requested date."""
    requested = date.fromisoformat(asof)
    if requested.isoformat() != asof:
        raise ValueError("Invalid P5 downstream asof session")
    base = Path(root).resolve() / "outputs/l2_validation"
    if not base.is_dir():
        raise FileNotFoundError("L2_P5_VALIDATION_REPORT_NOT_FOUND")
    sessions = []
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        try:
            session = date.fromisoformat(folder.name)
        except ValueError:
            continue
        if session.isoformat() == folder.name and session <= requested:
            sessions.append(folder.name)
    for session in sorted(sessions, reverse=True):
        folder = base / session
        candidates = []
        for identity_dir in folder.iterdir():
            path = identity_dir / "manifest.json"
            if path.is_file():
                candidates.append(_verify(path))
        if candidates:
            return max(candidates, key=lambda item: item["frozen_at_utc"])
    raise FileNotFoundError("L2_P5_VALIDATION_REPORT_NOT_FOUND")
