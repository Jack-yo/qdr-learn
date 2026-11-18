"""Read-only QDR L2 P4 forecast workflow.

Forecasts are available only when configs/l2_forecast.yaml names an immutable,
hash-verified label bundle. GET requests never train from exploratory labels,
write archives, or alter market data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import (
    FORECAST_PROTOCOL_VERSION, MODEL_VERSION, ForecastConfig, forecast_asof_v1,
)
from quant_research.research.l2_label_bundle import load_label_bundle_v1
from quant_research.workflow.l2_styles import load_observation_frame


def _settings(root: Path) -> dict:
    path = Path(root) / "configs/l2_forecast.yaml"
    if not path.is_file():
        return {
            "label_bundle_id": None,
            "min_training_sessions": 252,
            "embargo_sessions": 5,
            "ridge_alpha": 1.0,
        }
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowed = {
        "label_bundle_id", "min_training_sessions",
        "embargo_sessions", "ridge_alpha",
    }
    if set(data) - allowed:
        raise ValueError("Unexpected L2 forecast config keys")
    return {
        "label_bundle_id": data.get("label_bundle_id"),
        "min_training_sessions": int(data.get("min_training_sessions", 252)),
        "embargo_sessions": int(data.get("embargo_sessions", 5)),
        "ridge_alpha": float(data.get("ridge_alpha", 1.0)),
    }


def calculate_forecast(root: Path, *, asof: str | None = None,
                       horizon: int | None = None,
                       start: str = "2017-01-03") -> dict:
    """Return current P4 research predictions or an explicit evidence blocker."""
    root = Path(root).resolve()
    settings = _settings(root)
    if horizon is not None and horizon not in (1, 3, 5):
        raise ValueError("L2 forecast horizon must be 1, 3 or 5")

    bundle_id = settings["label_bundle_id"]
    if not bundle_id:
        return {
            "schema": "qdr.l2.forecast.v1",
            "status": "BLOCKED",
            "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
            "asof_session": asof,
            "forecast_protocol_version": FORECAST_PROTOCOL_VERSION,
            "model_version": MODEL_VERSION,
            "forecasts": [],
            "eligible_units": 0,
            "blocked_units": 21 if horizon is None else 7,
            "historical_decision_eligible": False,
            "real_orders_enabled": False,
            "missing_evidence": [
                "independently verified action-consistent T+1-open to T+H-close labels",
                "immutable source-hashed L2 label bundle",
            ],
        }

    clock = TradingClock()
    labels, manifest = load_label_bundle_v1(root, bundle_id, clock)
    observations, _, metadata, sessions, _ = load_observation_frame(
        root, asof=asof, start=start
    )
    day = pd.Timestamp(metadata["asof_date_et"])
    config = ForecastConfig(
        min_training_sessions=settings["min_training_sessions"],
        embargo_sessions=settings["embargo_sessions"],
        ridge_alpha=settings["ridge_alpha"],
    )
    forecasts = forecast_asof_v1(
        observations, labels, sessions, day, clock, config=config
    )
    if horizon is not None:
        forecasts = forecasts.loc[forecasts.horizon.eq(horizon)].copy()
    eligible = int(forecasts.forecast_status.eq("RESEARCH_ONLY").sum())
    blocked = int(forecasts.forecast_status.eq("BLOCKED").sum())
    records = json.loads(forecasts.to_json(orient="records", date_format="iso"))
    return {
        "schema": "qdr.l2.forecast.v1",
        "status": "RESEARCH_ONLY" if eligible else "BLOCKED",
        "code": None if eligible else "NO_ELIGIBLE_STYLE_HORIZON_FORECASTS",
        "asof_session": metadata["asof_date_et"],
        "signal_cutoff_utc": metadata["knowledge_cutoff_utc"],
        "source_snapshot_sha256": metadata["snapshot_sha256"],
        "source": metadata["source"],
        "price_basis": metadata.get("adjustment_basis", "yahoo_split_adjusted"),
        "label_bundle_id": bundle_id,
        "label_bundle_sha256": manifest["labels_sha256"],
        "label_source_evidence_sha256": manifest["source_evidence_sha256"],
        "forecast_protocol_version": FORECAST_PROTOCOL_VERSION,
        "model_version": MODEL_VERSION,
        "config": {
            "min_training_sessions": config.min_training_sessions,
            "embargo_sessions": config.embargo_sessions,
            "ridge_alpha": config.ridge_alpha,
        },
        "eligible_units": eligible,
        "blocked_units": blocked,
        "forecasts": records,
        "historical_decision_eligible": False,
        "real_orders_enabled": False,
        "limitations": [
            "STYLE_FORECAST_RESEARCH_ONLY",
            "NO_PROBABILITY_CALIBRATION_OR_MODEL_ADMISSION",
            "NO_BROKER_OR_PAPER_ORDER_EXECUTION",
        ],
    }
