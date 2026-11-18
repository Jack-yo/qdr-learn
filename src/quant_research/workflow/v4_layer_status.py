"""Read-only P6 four-layer evidence status.

This module aggregates existing immutable/read-only evidence. It never trains,
writes a decision, changes eligibility, or infers L3 style provenance that is
not explicitly bound in the V4 input bundle.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from quant_research.research.v4_forecast_archive import latest_forward_research
from quant_research.workflow.l1_runtime import L1Blocked, market_overview_for_api
from quant_research.workflow.l2_downstream import build_downstream_context
from quant_research.workflow.v4_candidate_bridge import latest_indicative_reviews


SCHEMA = "qdr.v4.layer-status.v1"


def _iso(value):
    if not value:
        return None
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.isoformat()


def _latest_not_after(records, asof):
    if not records:
        return None
    if asof is None:
        return records[0]
    eligible = [
        row for row in records
        if _iso(row.get("session_date_et"))
        and row["session_date_et"] <= asof
    ]
    return eligible[0] if eligible else None


def four_layer_status(root: Path, *, asof: str | None = None,
                      horizon: int = 3) -> dict:
    """Summarize L1/L2/L3/L4 evidence without granting execution eligibility."""
    if horizon not in (1, 3, 5):
        raise ValueError("Layer status horizon must be 1, 3 or 5")
    if asof is not None and _iso(asof) != asof:
        raise ValueError("Layer status asof must be ISO date")
    root = Path(root).resolve()

    try:
        l1_raw = market_overview_for_api(root, horizon, asof)
        l1 = {
            "status": l1_raw.get("status") or "BLOCKED",
            "asof_session": l1_raw.get("asof_session"),
            "model_version": l1_raw.get("model_version"),
            "model_admitted": l1_raw.get("model_admitted") is True,
            "current_prediction_eligible": (
                l1_raw.get("current_prediction_eligible") is True
            ),
            "forecast_present": l1_raw.get("forecast") is not None,
            "source_snapshot_sha256": l1_raw.get("source_snapshot_sha256"),
            "downstream_context_eligible": bool(
                l1_raw.get("model_admitted") is True
                and l1_raw.get("forecast") is not None
            ),
        }
    except (L1Blocked, OSError, ValueError, KeyError, TypeError) as exc:
        l1 = {
            "status": "BLOCKED",
            "code": getattr(exc, "code", None) or type(exc).__name__,
            "asof_session": asof,
            "model_admitted": False,
            "current_prediction_eligible": False,
            "forecast_present": False,
            "downstream_context_eligible": False,
        }

    try:
        l2_raw = build_downstream_context(root, asof=asof)
        l2 = {
            "status": l2_raw.get("status"),
            "code": l2_raw.get("code"),
            "asof_session": l2_raw.get("asof_session"),
            "model_version": l2_raw.get("model_version"),
            "admitted_units": int(l2_raw.get("admitted_units") or 0),
            "l3_style_context_available": bool(
                l2_raw.get("l3_style_context_available")
            ),
            "source_snapshot_sha256": l2_raw.get("source_snapshot_sha256"),
            "label_bundle_id": l2_raw.get("label_bundle_id"),
            "label_bundle_sha256": l2_raw.get("label_bundle_sha256"),
            "feature_bundle_id": l2_raw.get("feature_bundle_id"),
            "feature_bundle_sha256": l2_raw.get("feature_bundle_sha256"),
            "historical_feature_pit_attested": (
                l2_raw.get("historical_feature_pit_attested") is True
            ),
            "forecast_identity": l2_raw.get("forecast_identity"),
            "validation_identity": l2_raw.get("validation_identity"),
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        l2 = {
            "status": "BLOCKED",
            "code": type(exc).__name__,
            "asof_session": asof,
            "admitted_units": 0,
            "l3_style_context_available": False,
        }

    known_sessions = [
        item for item in (asof, _iso(l1.get("asof_session")), _iso(l2.get("asof_session")))
        if item is not None
    ]
    target_asof = min(known_sessions) if known_sessions else None
    alignment_sessions = {
        value for value in (
            _iso(l1.get("asof_session")),
            _iso(l2.get("asof_session")),
        ) if value is not None
    }
    aligned = len(alignment_sessions) <= 1 and (
        not alignment_sessions or target_asof in alignment_sessions
    )

    try:
        l3_records = latest_forward_research(root, limit=20)
        l3_record = _latest_not_after(l3_records, target_asof)
    except (OSError, ValueError, KeyError, TypeError):
        l3_record = None
    l3 = {
        "status": (
            l3_record.get("status") if l3_record
            else "BLOCKED"
        ),
        "code": None if l3_record else "NO_L3_FORWARD_RESEARCH_ARCHIVE",
        "asof_session": l3_record.get("session_date_et") if l3_record else target_asof,
        "forecast_identity": l3_record.get("identity") if l3_record else None,
        "forecast_rows": l3_record.get("forecast_rows") if l3_record else 0,
        "source_snapshot_sha256": (
            l3_record.get("source_snapshot_sha256") if l3_record else None
        ),
        "prospective_forward_research": bool(
            l3_record
            and l3_record.get("status") == "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY"
        ),
        "style_input_binding_verified": bool(
            l3_record and l3_record.get("l2_style_binding_verified") is True
        ),
        "style_historical_pit_attested": bool(
            l3_record and l3_record.get("l2_style_historical_pit_attested") is True
        ),
        "style_binding_context_sha256": (
            l3_record.get("l2_style_binding_context_sha256")
            if l3_record else None
        ),
        "style_binding_start_session": (
            l3_record.get("l2_style_binding_start_session")
            if l3_record else None
        ),
        "style_binding_end_session": (
            l3_record.get("l2_style_binding_end_session")
            if l3_record else None
        ),
        "style_binding_model_versions": (
            l3_record.get("l2_style_model_versions") or []
            if l3_record else []
        ),
        "style_binding_label_bundle_sha256s": (
            l3_record.get("l2_style_label_bundle_sha256s") or []
            if l3_record else []
        ),
        "style_binding_feature_bundle_sha256s": (
            l3_record.get("l2_style_feature_bundle_sha256s") or []
            if l3_record else []
        ),
        "style_binding_source_snapshot_sha256s": (
            l3_record.get("l2_style_source_snapshot_sha256s") or []
            if l3_record else []
        ),
        "style_input_binding_code": (
            None
            if l3_record and l3_record.get("l2_style_binding_verified") is True
            else "L3_STYLE_INPUT_NOT_BOUND_TO_L2_QUALIFICATION_IDENTITY"
        ),
        "downstream_context_eligible": bool(
            l3_record
            and l3_record.get("status") == "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY"
            and l3_record.get("l2_style_binding_verified") is True
            and l3_record.get("l2_style_historical_pit_attested") is True
        ),
    }

    try:
        reviews = latest_indicative_reviews(root, limit=30)
        l4_record = _latest_not_after(reviews.get("records") or [], target_asof)
    except (OSError, ValueError, KeyError, TypeError):
        l4_record = None
    l4 = {
        "status": l4_record.get("status") if l4_record else "BLOCKED",
        "code": None if l4_record else "NO_L4_RESEARCH_RISK_REVIEW",
        "asof_session": l4_record.get("session_date_et") if l4_record else target_asof,
        "plan_identity": l4_record.get("identity") if l4_record else None,
        "research_plan_count": (
            l4_record.get("research_plan_count") if l4_record else 0
        ),
        "source_snapshot_sha256": (
            l4_record.get("source_snapshot_sha256") if l4_record else None
        ),
        "risk_review_only": True,
        "execution_eligible": False,
        "real_orders_enabled": False,
    }

    blockers = []
    if not aligned:
        blockers.append("LAYER_SESSION_MISMATCH")
    if not l1.get("downstream_context_eligible"):
        blockers.append("L1_NOT_MODEL_ADMITTED")
    if not l2.get("l3_style_context_available"):
        blockers.append("L2_NO_MODEL_ADMITTED_STYLE_CONTEXT")
    if not l3_record:
        blockers.append("L3_FORWARD_RESEARCH_MISSING")
    elif not l3["prospective_forward_research"]:
        blockers.append("L3_NOT_PROSPECTIVE_FORWARD_RESEARCH")
    if not l3["style_input_binding_verified"]:
        blockers.append("L3_L2_STYLE_BINDING_NOT_VERIFIED")
    elif not l3["style_historical_pit_attested"]:
        blockers.append("L3_L2_STYLE_HISTORY_NOT_PIT_ATTESTED")
    else:
        if (
            l3.get("style_binding_end_session") != target_asof
            or not _iso(l3.get("style_binding_start_session"))
        ):
            blockers.append("L3_L2_BINDING_SESSION_MISMATCH")
        if (
            not l2.get("model_version")
            or l2.get("model_version") not in l3.get("style_binding_model_versions", [])
        ):
            blockers.append("L3_L2_MODEL_VERSION_BINDING_MISMATCH")
        if (
            not l2.get("label_bundle_sha256")
            or l2.get("label_bundle_sha256")
            not in l3.get("style_binding_label_bundle_sha256s", [])
        ):
            blockers.append("L3_L2_LABEL_BUNDLE_BINDING_MISMATCH")
        if (
            not l2.get("feature_bundle_sha256")
            or l2.get("feature_bundle_sha256")
            not in l3.get("style_binding_feature_bundle_sha256s", [])
        ):
            blockers.append("L3_L2_FEATURE_BUNDLE_BINDING_MISMATCH")
        if (
            not l2.get("source_snapshot_sha256")
            or l2.get("source_snapshot_sha256")
            not in l3.get("style_binding_source_snapshot_sha256s", [])
        ):
            blockers.append("L3_L2_SOURCE_BINDING_MISMATCH")
    if l3_record and l3_record.get("session_date_et") != target_asof:
        blockers.append("L3_SESSION_NOT_CURRENT")
    if not l4_record:
        blockers.append("L4_RISK_REVIEW_MISSING")
    elif l4_record.get("status") not in {
        "RESEARCH_PLANS_ONLY", "NO_RESEARCH_CANDIDATES"
    }:
        blockers.append("L4_RISK_REVIEW_INVALID")
    elif l4_record.get("session_date_et") != target_asof:
        blockers.append("L4_SESSION_NOT_CURRENT")
    if (
        l3_record and l4_record
        and l3_record.get("source_snapshot_sha256")
        and l4_record.get("source_snapshot_sha256")
        and l3_record.get("source_snapshot_sha256")
        != l4_record.get("source_snapshot_sha256")
    ):
        blockers.append("L3_L4_SOURCE_SNAPSHOT_MISMATCH")

    return {
        "schema": SCHEMA,
        "status": (
            "FOUR_LAYER_RESEARCH_CONTEXT_READY"
            if not blockers else "RESEARCH_ONLY"
        ),
        "asof_session": target_asof,
        "horizon": horizon,
        "session_alignment_verified": aligned,
        "layers": {
            "l1_market": l1,
            "l2_style": l2,
            "l3_alpha": l3,
            "l4_risk": l4,
        },
        "blockers": blockers,
        "complete_four_layer_context": not blockers,
        "decision_eligible": False,
        "execution_eligible": False,
        "real_orders_enabled": False,
    }
