"""Read-only L2 -> downstream context contract for QDR P6.

This bridge never turns RESEARCH_ONLY/OOS_VALIDATED rows into Alpha inputs.
Only exact MODEL_ADMITTED style×horizon units may expose an admitted numeric
context, and even then execution/order eligibility remains false.
"""
from __future__ import annotations

from pathlib import Path
import math

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.research.l2_forecast_archive import load_frozen_forecast_v1
from quant_research.workflow.l2_forecast import calculate_forecast
from quant_research.workflow.l2_validation import (
    read_latest_validation,
    read_validation_on_or_before,
)


CONTRACT_VERSION = "qdr-l2-downstream-context-v1"


def build_downstream_context(root: Path, *, asof: str | None = None) -> dict:
    root = Path(root).resolve()
    forecast = calculate_forecast(root, asof=asof)
    forecast_asof = forecast.get("asof_session") or asof
    validation = (
        read_validation_on_or_before(root, asof=forecast_asof)
        if forecast_asof is not None
        else read_latest_validation(root)
    )

    base = {
        "schema": "qdr.l2.downstream-context.v1",
        "contract_version": CONTRACT_VERSION,
        "asof_session": forecast.get("asof_session") or validation.get("asof_session") or asof,
        "model_version": forecast.get("model_version"),
        "label_bundle_id": forecast.get("label_bundle_id"),
        "label_bundle_sha256": forecast.get("label_bundle_sha256"),
        "feature_bundle_id": forecast.get("feature_bundle_id"),
        "feature_bundle_sha256": forecast.get("feature_bundle_sha256"),
        "historical_feature_pit_attested": (
            forecast.get("historical_feature_pit_attested") is True
        ),
        "source_snapshot_sha256": forecast.get("source_snapshot_sha256"),
        "forecast_identity": None,
        "validation_identity": validation.get("identity"),
        "validation_asof_session": validation.get("asof_session"),
        "contexts": [],
        "admitted_units": 0,
        "l3_style_context_available": False,
        "historical_decision_eligible": False,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }
    if forecast.get("status") != "RESEARCH_ONLY":
        return {
            **base,
            "status": "RESEARCH_ONLY",
            "code": forecast.get("code") or "L2_CURRENT_FORECAST_NOT_AVAILABLE",
        }
    if forecast.get("historical_feature_pit_attested") is not True:
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_HISTORICAL_FEATURE_PIT_NOT_ATTESTED",
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
    if validation.get("historical_feature_pit_attested") is not True:
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_P5_FEATURE_PIT_NOT_ATTESTED",
        }
    if validation.get("feature_bundle_sha256") != forecast.get("feature_bundle_sha256"):
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_FEATURE_BUNDLE_MISMATCH",
        }

    try:
        frozen = load_frozen_forecast_v1(
            root, forecast["asof_session"], forecast["model_version"]
        )
    except FileNotFoundError:
        return {
            **base,
            "status": "RESEARCH_ONLY",
            "code": "L2_CURRENT_FORECAST_NOT_FROZEN",
        }
    if (
        frozen.get("session_date_et") != forecast.get("asof_session")
        or frozen.get("model_version") != forecast.get("model_version")
        or frozen.get("label_bundle_sha256") != forecast.get("label_bundle_sha256")
        or frozen.get("feature_bundle_sha256") != forecast.get("feature_bundle_sha256")
        or frozen.get("historical_feature_pit_attested") is not True
        or frozen.get("source_snapshot_sha256") != forecast.get("source_snapshot_sha256")
    ):
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_FROZEN_FORECAST_PROVENANCE_MISMATCH",
        }
    clock = TradingClock()
    window = clock.window(forecast["asof_session"], 1)
    frozen_at = pd.Timestamp(frozen.get("frozen_at_utc"))
    if (
        frozen.get("prospective_before_next_open") is not True
        or frozen_at.tzinfo is None
        or not (
            pd.Timestamp(window.signal_time)
            <= frozen_at.tz_convert("UTC")
            < pd.Timestamp(window.entry_time)
        )
    ):
        return {
            **base,
            "status": "RESEARCH_ONLY",
            "code": "L2_FORECAST_NOT_FROZEN_BEFORE_NEXT_ENTRY",
        }

    live_map = {
        (row.get("style_id"), int(row.get("horizon"))): row
        for row in forecast.get("forecasts", [])
        if row.get("style_id") in STYLE_IDS and row.get("horizon") in HORIZONS
    }
    frozen_map = {
        (row.get("style_id"), int(row.get("horizon"))): row
        for row in frozen.get("forecasts", [])
        if row.get("style_id") in STYLE_IDS and row.get("horizon") in HORIZONS
    }
    expected = {(style, horizon) for style in STYLE_IDS for horizon in HORIZONS}
    if set(live_map) != expected or set(frozen_map) != expected:
        return {
            **base,
            "status": "BLOCKED",
            "code": "L2_FROZEN_FORECAST_GRID_MISMATCH",
        }
    for key in expected:
        live_row, frozen_row = live_map[key], frozen_map[key]
        if live_row.get("forecast_status") != frozen_row.get("forecast_status"):
            return {
                **base,
                "status": "BLOCKED",
                "code": "L2_FROZEN_FORECAST_DIFFERS_FROM_CURRENT_MODEL_OUTPUT",
            }
        left = live_row.get("predicted_relative_return")
        right = frozen_row.get("predicted_relative_return")
        if (left is None) != (right is None) or (
            left is not None and not math.isclose(
                float(left), float(right), rel_tol=0.0, abs_tol=1e-15
            )
        ):
            return {
                **base,
                "status": "BLOCKED",
                "code": "L2_FROZEN_FORECAST_DIFFERS_FROM_CURRENT_MODEL_OUTPUT",
            }

    base = {
        **base,
        "forecast_identity": frozen.get("identity"),
        "forecast_frozen_at_utc": frozen.get("frozen_at_utc"),
    }
    qualification = {
        (row.get("style_id"), int(row.get("horizon"))): row
        for row in validation.get("qualification", [])
        if row.get("style_id") in STYLE_IDS and row.get("horizon") in HORIZONS
    }
    forecasts = frozen_map
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
