"""Immutable forward L2 forecast snapshots for later P5 scoring."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS


ARCHIVE_SCHEMA = "qdr.l2.frozen-forecast.v1"


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _sha(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_model(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value):
        raise ValueError("Invalid L2 model version for archive")
    return value


def freeze_forecast_snapshot_v1(
    root: Path, forecast_payload: dict, *, now_utc=None
) -> dict:
    """Freeze one exact style/horizon research snapshot; never overwrite it."""
    if forecast_payload.get("status") != "RESEARCH_ONLY":
        raise ValueError("Only RESEARCH_ONLY L2 forecasts may be frozen")
    if forecast_payload.get("real_orders_enabled") is not False:
        raise ValueError("L2 frozen forecast must keep real orders disabled")
    if forecast_payload.get("historical_decision_eligible") is not False:
        raise ValueError("L2 frozen forecast cannot claim historical decision eligibility")
    asof = str(forecast_payload.get("asof_session") or "")
    try:
        from datetime import date
        if date.fromisoformat(asof).isoformat() != asof:
            raise ValueError
    except ValueError:
        raise ValueError("Invalid L2 forecast asof session") from None
    source_sha = str(forecast_payload.get("source_snapshot_sha256") or "")
    labels_sha = str(forecast_payload.get("label_bundle_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("L2 forecast source snapshot SHA256 is required")
    if not re.fullmatch(r"[0-9a-f]{64}", labels_sha):
        raise ValueError("L2 forecast label bundle SHA256 is required")
    model_version = _safe_model(str(forecast_payload.get("model_version") or ""))

    rows = forecast_payload.get("forecasts")
    if not isinstance(rows, list) or len(rows) != 21:
        raise ValueError("L2 frozen forecast requires 21 explicit style/horizon rows")
    identities = []
    eligible = 0
    for row in rows:
        key = (row.get("style_id"), row.get("horizon"))
        identities.append(key)
        if row.get("date") != asof:
            raise ValueError("L2 forecast row date differs from snapshot session")
        if row.get("real_orders_enabled") is not False or row.get("decision_eligible") is not False:
            raise ValueError("Frozen L2 row cannot be execution eligible")
        if row.get("forecast_status") == "RESEARCH_ONLY":
            eligible += 1
            if row.get("predicted_relative_return") is None:
                raise ValueError("Eligible L2 forecast row has no prediction")
        elif row.get("forecast_status") != "BLOCKED":
            raise ValueError("Unexpected L2 forecast row status")
    expected = {(style, horizon) for style in STYLE_IDS for horizon in HORIZONS}
    if set(identities) != expected:
        raise ValueError("L2 frozen forecast must contain the exact seven-style H1/H3/H5 grid")
    blocked = sum(row.get("forecast_status") == "BLOCKED" for row in rows)
    if eligible != int(forecast_payload.get("eligible_units", -1)) or eligible <= 0:
        raise ValueError("L2 eligible-unit count mismatch")
    if blocked != int(forecast_payload.get("blocked_units", -1)) or eligible + blocked != 21:
        raise ValueError("L2 blocked-unit count mismatch")

    base = {
        "schema": ARCHIVE_SCHEMA,
        "session_date_et": asof,
        "model_version": model_version,
        "forecast_protocol_version": forecast_payload.get("forecast_protocol_version"),
        "source_snapshot_sha256": source_sha,
        "label_bundle_id": forecast_payload.get("label_bundle_id"),
        "label_bundle_sha256": labels_sha,
        "label_source_evidence_sha256": forecast_payload.get("label_source_evidence_sha256"),
        "config": forecast_payload.get("config"),
        "eligible_units": eligible,
        "blocked_units": int(forecast_payload.get("blocked_units", 0)),
        "forecasts": rows,
        "historical_decision_eligible": False,
        "real_orders_enabled": False,
    }
    identity = _sha(base)
    frozen_at = pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if frozen_at.tzinfo is None:
        raise ValueError("L2 forecast freeze time must be timezone-aware")
    frozen_at = frozen_at.tz_convert("UTC")
    window = TradingClock().window(
        asof, 1, now=frozen_at.to_pydatetime()
    )
    prospective = bool(
        pd.Timestamp(window.signal_time)
        <= frozen_at
        < pd.Timestamp(window.entry_time)
    )
    record = {
        **base,
        "identity": identity,
        "frozen_at_utc": frozen_at.isoformat(),
        "prospective_before_next_open": prospective,
        "status": (
            "FROZEN_L2_FORWARD_RESEARCH_ONLY"
            if prospective
            else "FROZEN_L2_RETROSPECTIVE_ASOF_ONLY"
        ),
    }

    root = Path(root).resolve()
    folder = root / "outputs/l2_style_forecasts" / asof / model_version
    target = folder / "manifest.json"
    if target.is_file():
        existing = load_frozen_forecast_v1(root, asof, model_version)
        if existing.get("identity") == identity:
            return existing
        raise FileExistsError("L2_FORECAST_ALREADY_FROZEN_WITH_DIFFERENT_IDENTITY")
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=folder,
        prefix=".manifest-", suffix=".json", delete=False
    ) as handle:
        handle.write(_canonical(record))
        temp = Path(handle.name)
    try:
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return record


def load_frozen_forecast_v1(root: Path, session_date: str, model_version: str) -> dict:
    """Read and verify one exact archived snapshot identity."""
    model_version = _safe_model(model_version)
    path = Path(root).resolve() / "outputs/l2_style_forecasts" / session_date / model_version / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError("L2_FROZEN_FORECAST_NOT_FOUND")
    data = json.loads(path.read_text(encoding="utf-8"))
    identity = data.pop("identity", None)
    frozen = data.pop("frozen_at_utc", None)
    status = data.pop("status", None)
    declared_prospective = data.pop("prospective_before_next_open", None)
    if not frozen or _sha(data) != identity:
        raise ValueError("L2_FROZEN_FORECAST_IDENTITY_MISMATCH")
    frozen_at = pd.Timestamp(frozen)
    if frozen_at.tzinfo is None:
        raise ValueError("L2_FROZEN_FORECAST_TIME_INVALID")
    frozen_at = frozen_at.tz_convert("UTC")
    try:
        window = TradingClock().window(
            session_date, 1, now=frozen_at.to_pydatetime()
        )
    except ValueError as exc:
        raise ValueError("L2_FROZEN_FORECAST_TIME_INVALID") from exc
    expected_prospective = bool(
        pd.Timestamp(window.signal_time)
        <= frozen_at
        < pd.Timestamp(window.entry_time)
    )
    allowed = {
        "FROZEN_L2_RESEARCH_ONLY",
        "FROZEN_L2_FORWARD_RESEARCH_ONLY",
        "FROZEN_L2_RETROSPECTIVE_ASOF_ONLY",
    }
    if status not in allowed:
        raise ValueError("L2_FROZEN_FORECAST_SCOPE_INVALID")
    if status == "FROZEN_L2_RESEARCH_ONLY":
        if declared_prospective is not None:
            raise ValueError("L2_FROZEN_FORECAST_LEGACY_SCOPE_INVALID")
        prospective = expected_prospective
    else:
        if type(declared_prospective) is not bool:
            raise ValueError("L2_FROZEN_FORECAST_SCOPE_INVALID")
        prospective = declared_prospective
        expected_status = (
            "FROZEN_L2_FORWARD_RESEARCH_ONLY"
            if expected_prospective
            else "FROZEN_L2_RETROSPECTIVE_ASOF_ONLY"
        )
        if prospective is not expected_prospective or status != expected_status:
            raise ValueError("L2_FROZEN_FORECAST_SCOPE_TIME_MISMATCH")
    return {
        **data,
        "identity": identity,
        "frozen_at_utc": frozen_at.isoformat(),
        "prospective_before_next_open": prospective,
        "status": status,
    }
