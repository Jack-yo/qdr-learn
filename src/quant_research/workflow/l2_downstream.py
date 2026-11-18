"""Read-only L2 -> downstream context contract for QDR P6.

This bridge never turns RESEARCH_ONLY/OOS_VALIDATED rows into Alpha inputs.
Only exact MODEL_ADMITTED style×horizon units may expose an admitted numeric
context, and even then execution/order eligibility remains false.
"""
from __future__ import annotations

from pathlib import Path

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow.l2_forecast import calculate_forecast
from quant_research.workflow.l2_validation import (
    read_latest_validation,
    read_validation_on_or_before,
)


CONTRACT_VERSION = "qdr-l2-downstream-context-v1"


def build_downstream_context(root: Path, *, asof: str | None = None) -> dict:
    root = Path(root).resolve()
    forecast = calculate_forecast(root, asof=asof)
    validation = (
        read_validation_on_or_before(root, asof=asof)
        if asof is not None
        else read_latest_validation(root)
    )

    base = {
        "schema": "qdr.l2.downstream-context.v1",
        "contract_version": CONTRACT_VERSION,
        "asof_session": forecast.get("asof_session") or validation.get("asof_session") or asof,
        "model_version": forecast.get("model_version"),
        "label_bundle_id": forecast.get("label_bundle_id"),
        "label_bundle_sha256": forecast.get("label_bundle_sha256"),
        "source_snapshot_sha256": forecast.get("source_snapshot_sha256"),
        "contexts": [],
        "admitted_units": 0,
        "l3_style_context_available": False,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }
    if forecast.get("status") != "RESEARCH_ONLY":
        return {
            **base,
            "status": "RESEARCH_ONLY",
            "code": forecast.get("code") or "L2_CURRENT_FORECAST_NOT_AVAILABLE",
        }
    if validation.get("status") != "P5_RESEARCH_VALIDATION":
        return {
            **base,
            "status": "RESEARCH_ONLY",
            "code": validation.get("code") or "L2_P5_VALIDATION_NOT_AVAILABLE",
        }
    if validation.get("model_version") != forecast.get("model_version"):
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_MODEL_VERSION_MISMATCH",
        }
    if validation.get("label_bundle_sha256") != forecast.get("label_bundle_sha256"):
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_LABEL_BUNDLE_MISMATCH",
        }

    qualification = {
        (row.get("style_id"), int(row.get("horizon"))): row
        for row in validation.get("qualification", [])
        if row.get("style_id") in STYLE_IDS and row.get("horizon") in HORIZONS
    }
    forecasts = {
        (row.get("style_id"), int(row.get("horizon"))): row
        for row in forecast.get("forecasts", [])
        if row.get("style_id") in STYLE_IDS and row.get("horizon") in HORIZONS
    }
    rows = []
    admitted = 0
    for style_id in STYLE_IDS:
        for horizon in HORIZONS:
            key = (style_id, horizon)
            q = qualification.get(key) or {}
            f = forecasts.get(key) or {}
            is_admitted = bool(
                q.get("qualification_status") == "MODEL_ADMITTED"
                and q.get("model_admitted") is True
                and q.get("oos_gate_passed") is True
                and q.get("forward_gate_passed") is True
                and f.get("forecast_status") == "RESEARCH_ONLY"
                and f.get("predicted_relative_return") is not None
            )
            if is_admitted:
                admitted += 1
            rows.append({
                "style_id": style_id,
                "horizon": horizon,
                "qualification_status": q.get("qualification_status") or "RESEARCH_ONLY",
                "current_forecast_status": f.get("forecast_status") or "BLOCKED",
                "research_predicted_relative_return": f.get("predicted_relative_return"),
                "admitted_relative_return": (
                    f.get("predicted_relative_return") if is_admitted else None
                ),
                "downstream_context_eligible": is_admitted,
                "decision_eligible": False,
                "real_orders_enabled": False,
            })

    return {
        **base,
        "status": "MODEL_ADMITTED_CONTEXT" if admitted else "RESEARCH_ONLY",
        "code": None if admitted else "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
        "contexts": rows,
        "admitted_units": admitted,
        "l3_style_context_available": admitted > 0,
    }
