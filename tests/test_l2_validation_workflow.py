"""P5 workflow tests: explicit compute/freeze and read-only report access."""
import pandas as pd

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow import l2_validation


def _qualification():
    return pd.DataFrame([
        {
            "style_id": style,
            "horizon": horizon,
            "qualification_status": "OOS_VALIDATED",
            "oos_gate_passed": True,
            "forward_gate_passed": False,
            "model_admitted": False,
            "reasons": ["MODEL_ADMISSION_SWITCH_DISABLED"],
            "decision_eligible": False,
            "real_orders_enabled": False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def _oos_validation():
    return pd.DataFrame([
        {
            "style_id": style,
            "horizon": horizon,
            "status": "OOS_VALIDATED",
            "validation_passed": True,
            "oos_sessions": 150,
            "decision_eligible": False,
            "real_orders_enabled": False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def test_missing_label_bundle_blocks_without_any_heavy_research(tmp_path, monkeypatch):
    monkeypatch.setattr(
        l2_validation, "forecast_settings",
        lambda root: {
            "label_bundle_id": None,
            "min_training_sessions": 252,
            "embargo_sessions": 5,
            "ridge_alpha": 1.0,
        },
    )
    called = []
    monkeypatch.setattr(
        l2_validation, "load_label_bundle_v1",
        lambda *args, **kwargs: called.append("labels"),
    )
    result = l2_validation.build_validation_report(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert result["real_orders_enabled"] is False
    assert called == []


def test_p5_build_uses_fixed_oos_span_and_preserves_21_units(tmp_path, monkeypatch):
    monkeypatch.setattr(
        l2_validation, "forecast_settings",
        lambda root: {
            "label_bundle_id": "accepted-v1",
            "min_training_sessions": 60,
            "embargo_sessions": 5,
            "ridge_alpha": 1.0,
        },
    )
    dates = pd.bdate_range("2024-01-02", periods=320)
    labels = pd.DataFrame([
        {
            "date": day,
            "style_id": style,
            "horizon": horizon,
            "forward_relative_return": 0.001,
        }
        for day in dates
        for style in STYLE_IDS
        for horizon in HORIZONS
    ])
    monkeypatch.setattr(
        l2_validation, "load_label_bundle_v1",
        lambda root, bundle_id, clock: (
            labels,
            {
                "labels_sha256": "a" * 64,
                "source_evidence_sha256": "b" * 64,
            },
        ),
    )
    metadata = {
        "asof_date_et": str(dates[-1].date()),
        "snapshot_sha256": "c" * 64,
        "source": "YAHOO",
    }
    monkeypatch.setattr(
        l2_validation, "load_observation_frame",
        lambda root, asof=None: (
            pd.DataFrame({"x": [1]}),
            pd.DataFrame(),
            metadata,
            dates,
            pd.Timestamp("2025-03-01T22:00:00Z"),
        ),
    )
    monkeypatch.setattr(
        l2_validation, "validation_settings",
        lambda root: l2_validation.ValidationConfig(
            oos_evaluation_sessions=252,
            min_oos_sessions=126,
        ),
    )
    captured = {}
    def fake_walk(*args, **kwargs):
        evaluation = pd.DatetimeIndex(args[3])
        captured["full_eval"] = evaluation
        return pd.DataFrame([
            {
                "date": evaluation[-1],
                "style_id": style,
                "horizon": horizon,
                "forward_relative_return": 0.001,
                "predicted_relative_return": 0.001,
                "zero_baseline": 0.0,
                "mean_baseline": 0.0001,
                "momentum_baseline": 0.0002,
            }
            for style in STYLE_IDS for horizon in HORIZONS
        ])
    monkeypatch.setattr(l2_validation, "walk_forward_oos_v1", fake_walk)
    def fake_ablation(*args, **kwargs):
        captured["ablation_eval"] = pd.DatetimeIndex(args[3])
        return (
            pd.DataFrame({"variant": ["full"]}),
            pd.DataFrame([{"variant": "full", "style_id": "size", "horizon": 1}]),
        )
    monkeypatch.setattr(l2_validation, "run_ablation_oos_v1", fake_ablation)
    monkeypatch.setattr(
        l2_validation, "validate_oos_v1",
        lambda frame, config=None: _oos_validation(),
    )
    monkeypatch.setattr(
        l2_validation, "collect_frozen_forecasts_v1",
        lambda root, model_version: pd.DataFrame(),
    )
    monkeypatch.setattr(
        l2_validation, "score_genuine_forward_v1",
        lambda frozen, labels: pd.DataFrame(),
    )
    monkeypatch.setattr(
        l2_validation, "qualify_models_v1",
        lambda oos, forward, config=None: _qualification(),
    )

    report = l2_validation.build_validation_report(tmp_path)
    assert report["status"] == "P5_RESEARCH_VALIDATION"
    assert report["evaluation"]["actual_sessions"] == 252
    assert len(captured["full_eval"]) == 252
    assert captured["full_eval"].equals(captured["ablation_eval"])
    assert len(report["qualification"]) == 21
    assert report["summary"]["oos_validated_units"] == 21
    assert report["summary"]["model_admitted_units"] == 0
    assert report["real_orders_enabled"] is False


def test_read_latest_validation_never_calls_heavy_builder(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        l2_validation, "build_validation_report",
        lambda *args, **kwargs: called.append("build"),
    )
    monkeypatch.setattr(
        l2_validation, "load_latest_validation_v1",
        lambda root, asof=None: {
            "schema": "qdr.l2.validation-report.v1",
            "status": "P5_RESEARCH_VALIDATION",
            "asof_session": asof or "2026-01-30",
            "qualification": [],
            "real_orders_enabled": False,
        },
    )
    result = l2_validation.read_latest_validation(tmp_path, asof="2026-01-30")
    assert result["status"] == "P5_RESEARCH_VALIDATION"
    assert called == []


def test_freeze_validation_writes_only_completed_report(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(
        l2_validation, "build_validation_report",
        lambda root, asof=None: {
            "status": "BLOCKED",
            "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
            "asof_session": asof,
        },
    )
    monkeypatch.setattr(
        l2_validation, "freeze_validation_report_v1",
        lambda *args, **kwargs: called.append("freeze"),
    )
    blocked = l2_validation.freeze_validation(tmp_path, asof="2026-01-30")
    assert blocked["status"] == "BLOCKED_NO_VALIDATION_ARCHIVE_WRITE"
    assert called == []

    monkeypatch.setattr(
        l2_validation, "build_validation_report",
        lambda root, asof=None: {
            "status": "P5_RESEARCH_VALIDATION",
            "asof_session": "2026-01-30",
            "real_orders_enabled": False,
        },
    )
    monkeypatch.setattr(
        l2_validation, "freeze_validation_report_v1",
        lambda root, report: {
            **report,
            "identity": "d" * 64,
            "frozen_at_utc": "2026-01-31T00:00:00+00:00",
            "summary": {"model_admitted_units": 0},
        },
    )
    frozen = l2_validation.freeze_validation(tmp_path, asof="2026-01-30")
    assert frozen["status"] == "FROZEN_P5_RESEARCH_VALIDATION"
    assert frozen["identity"] == "d" * 64
    assert frozen["real_orders_enabled"] is False
