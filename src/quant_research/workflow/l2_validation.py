"""Explicit QDR L2 P5 validation workflow.

Heavy walk-forward/ablation research is run explicitly and may be frozen.
Web GET endpoints only read the immutable report; they never rerun P5.
"""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path

import pandas as pd
import yaml

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import (
    HORIZONS,
    MODEL_VERSION,
    STYLE_IDS,
    ForecastConfig,
)
from quant_research.research.l2_label_bundle import load_label_bundle_v1
from quant_research.research.l2_validation import (
    PROBABILITY_CALIBRATION_STATUS,
    ValidationConfig,
    collect_frozen_forecasts_v1,
    qualify_models_v1,
    run_ablation_oos_v1,
    score_genuine_forward_v1,
    validate_oos_v1,
)
from quant_research.research.l2_validation_archive import (
    freeze_validation_report_v1,
    load_latest_validation_v1,
    load_validation_on_or_before_v1,
)
from quant_research.workflow.l2_forecast import _settings as forecast_settings
from quant_research.workflow.l2_styles import load_observation_frame


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def validation_settings(root: Path) -> ValidationConfig:
    path = Path(root) / "configs/l2_validation.yaml"
    defaults = ValidationConfig()
    if not path.is_file():
        return defaults
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    allowed = {field.name for field in fields(ValidationConfig)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(
            "Unexpected L2 validation config keys: " + ",".join(sorted(unknown))
        )
    config = ValidationConfig(**{
        field.name: data.get(field.name, getattr(defaults, field.name))
        for field in fields(ValidationConfig)
    })
    config.validate()
    return config


def _empty_oos_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "date", "style_id", "horizon", "forward_relative_return",
        "predicted_relative_return", "zero_baseline",
        "mean_baseline", "momentum_baseline",
    ])


def build_validation_report(root: Path, *, asof: str | None = None) -> dict:
    """Run P5 on one fixed historical evaluation span; no writes."""
    root = Path(root).resolve()
    f_settings = forecast_settings(root)
    bundle_id = f_settings["label_bundle_id"]
    if not bundle_id:
        return {
            "schema": "qdr.l2.validation.v1",
            "status": "BLOCKED",
            "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
            "asof_session": asof,
            "qualification": [],
            "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
            "real_orders_enabled": False,
        }

    clock = TradingClock()
    labels, label_manifest = load_label_bundle_v1(root, bundle_id, clock)
    observations, _, metadata, sessions, cutoff_timestamp = load_observation_frame(
        root, asof=asof
    )
    config = validation_settings(root)
    forecast_config = ForecastConfig(
        min_training_sessions=f_settings["min_training_sessions"],
        embargo_sessions=f_settings["embargo_sessions"],
        ridge_alpha=f_settings["ridge_alpha"],
    )
    asof_day = pd.Timestamp(metadata["asof_date_et"]).tz_localize(None).normalize()
    labels = labels.copy()
    labels["label_available_at"] = pd.to_datetime(
        labels["label_available_at"], utc=True, errors="coerce"
    )
    known_labels = labels.loc[
        labels.forward_relative_return.notna()
        & labels.label_available_at.notna()
        & labels.label_available_at.le(cutoff_timestamp)
    ].copy()
    labeled_dates = pd.DatetimeIndex(
        sorted(pd.to_datetime(
            known_labels["date"]
        ).dt.tz_localize(None).dt.normalize().unique())
    )
    labeled_dates = labeled_dates[
        labeled_dates.isin(pd.DatetimeIndex(sessions).tz_localize(None).normalize())
        & labeled_dates.le(asof_day)
    ]
    evaluation_dates = labeled_dates[-config.oos_evaluation_sessions:]

    if len(evaluation_dates):
        ablation_predictions, ablation_scores = run_ablation_oos_v1(
            observations,
            known_labels,
            sessions,
            evaluation_dates,
            clock,
            forecast_config=forecast_config,
        )
        full_predictions = (
            ablation_predictions.loc[
                ablation_predictions.variant.eq("full")
            ].drop(columns=["variant"]).copy()
            if not ablation_predictions.empty and "variant" in ablation_predictions
            else _empty_oos_frame()
        )
    else:
        full_predictions = _empty_oos_frame()
        ablation_predictions = pd.DataFrame()
        ablation_scores = pd.DataFrame()

    if full_predictions.empty:
        full_predictions = _empty_oos_frame()
    oos_validation = validate_oos_v1(full_predictions, config=config)

    frozen = collect_frozen_forecasts_v1(root, MODEL_VERSION)
    if not frozen.empty:
        frozen_dates = pd.to_datetime(frozen["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
        frozen = frozen.loc[frozen_dates.le(asof_day)].copy()
    forward_validation = score_genuine_forward_v1(frozen, known_labels)
    qualification = qualify_models_v1(
        oos_validation, forward_validation, config=config
    )
    if len(qualification) != len(STYLE_IDS) * len(HORIZONS):
        raise ValueError("P5 qualification must preserve exact 7x3 scope")

    validated_units = int(
        oos_validation.status.eq("OOS_VALIDATED").sum()
    )
    admitted_units = int(qualification.model_admitted.sum())
    genuine_forward_units = int(
        forward_validation.genuine_forward_sessions.gt(0).sum()
    ) if not forward_validation.empty else 0

    return {
        "schema": "qdr.l2.validation.v1",
        "status": "P5_RESEARCH_VALIDATION",
        "code": None,
        "asof_session": metadata["asof_date_et"],
        "source_snapshot_sha256": metadata["snapshot_sha256"],
        "source": metadata["source"],
        "label_bundle_id": bundle_id,
        "label_bundle_sha256": label_manifest["labels_sha256"],
        "label_source_evidence_sha256": label_manifest["source_evidence_sha256"],
        "model_version": MODEL_VERSION,
        "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
        "evaluation": {
            "requested_sessions": config.oos_evaluation_sessions,
            "actual_sessions": int(len(evaluation_dates)),
            "first_session": (
                evaluation_dates.min().date().isoformat()
                if len(evaluation_dates) else None
            ),
            "last_session": (
                evaluation_dates.max().date().isoformat()
                if len(evaluation_dates) else None
            ),
            "full_prediction_rows": int(len(full_predictions)),
            "ablation_prediction_rows": int(len(ablation_predictions)),
        },
        "config": {
            field.name: getattr(config, field.name)
            for field in fields(ValidationConfig)
        },
        "oos_validation": _records(oos_validation),
        "ablation_scores": _records(ablation_scores),
        "forward_validation": _records(forward_validation),
        "qualification": _records(qualification),
        "summary": {
            "oos_validated_units": validated_units,
            "genuine_forward_units": genuine_forward_units,
            "model_admitted_units": admitted_units,
            "total_units": len(STYLE_IDS) * len(HORIZONS),
            "model_admission_enabled": config.model_admission_enabled,
        },
        "historical_decision_eligible": False,
        "decision_eligible": False,
        "real_orders_enabled": False,
        "limitations": [
            "CONTINUOUS_RELATIVE_RETURN_MODEL_NO_PROBABILITY_TARGET",
            "OOS_VALIDATION_DOES_NOT_ENABLE_ORDERS",
            "MODEL_ADMISSION_REQUIRES_GENUINE_FORWARD_EVIDENCE_AND_EXPLICIT_SWITCH",
        ],
    }


def freeze_validation(root: Path, *, asof: str | None = None) -> dict:
    """Run and freeze P5 only when the prerequisite label bundle exists."""
    report = build_validation_report(root, asof=asof)
    if report.get("status") != "P5_RESEARCH_VALIDATION":
        return {
            "status": "BLOCKED_NO_VALIDATION_ARCHIVE_WRITE",
            "code": report.get("code") or "P5_VALIDATION_NOT_READY",
            "asof_session": report.get("asof_session") or asof,
            "real_orders_enabled": False,
        }
    frozen = freeze_validation_report_v1(root, report)
    return {
        "status": "FROZEN_P5_RESEARCH_VALIDATION",
        "asof_session": frozen["asof_session"],
        "identity": frozen["identity"],
        "frozen_at_utc": frozen["frozen_at_utc"],
        "summary": frozen["summary"],
        "real_orders_enabled": False,
    }


def read_latest_validation(root: Path, *, asof: str | None = None) -> dict:
    """Read P5 report only; never trigger validation computation."""
    try:
        return load_latest_validation_v1(root, asof=asof)
    except FileNotFoundError:
        return {
            "schema": "qdr.l2.validation.v1",
            "status": "BLOCKED",
            "code": "L2_P5_VALIDATION_REPORT_NOT_FOUND",
            "asof_session": asof,
            "qualification": [],
            "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
            "real_orders_enabled": False,
        }


def read_validation_on_or_before(root: Path, *, asof: str) -> dict:
    """Read newest frozen P5 report not later than asof; never recompute."""
    try:
        return load_validation_on_or_before_v1(root, asof)
    except FileNotFoundError:
        return {
            "schema": "qdr.l2.validation.v1",
            "status": "BLOCKED",
            "code": "L2_P5_VALIDATION_REPORT_NOT_FOUND",
            "asof_session": asof,
            "qualification": [],
            "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
            "real_orders_enabled": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run QDR L2 P5 OOS/ablation/forward validation; no orders"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--date", default=None)
    parser.add_argument(
        "--freeze", action="store_true",
        help="Freeze immutable P5 report; without this flag only print calculation",
    )
    args = parser.parse_args(argv)
    result = (
        freeze_validation(args.root, asof=args.date)
        if args.freeze
        else build_validation_report(args.root, asof=args.date)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result.get("status") in {
        "P5_RESEARCH_VALIDATION",
        "FROZEN_P5_RESEARCH_VALIDATION",
    } else 4


if __name__ == "__main__":
    raise SystemExit(main())
