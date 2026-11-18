"""P6 L2 downstream context contract tests."""
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow import l2_downstream


def _forecast():
    return {
        "status": "RESEARCH_ONLY",
        "asof_session": "2026-01-30",
        "model_version": "ridge-v1",
        "label_bundle_id": "accepted-v1",
        "label_bundle_sha256": "a" * 64,
        "source_snapshot_sha256": "b" * 64,
        "forecasts": [
            {
                "style_id": style,
                "horizon": horizon,
                "forecast_status": "RESEARCH_ONLY",
                "predicted_relative_return": 0.001 * horizon,
            }
            for style in STYLE_IDS for horizon in HORIZONS
        ],
    }


def _frozen():
    clock = TradingClock()
    window = clock.window("2026-01-30", 1)
    live = _forecast()
    return {
        "session_date_et": live["asof_session"],
        "model_version": live["model_version"],
        "label_bundle_sha256": live["label_bundle_sha256"],
        "source_snapshot_sha256": live["source_snapshot_sha256"],
        "identity": "d" * 64,
        "frozen_at_utc": (
            pd.Timestamp(window.signal_time) + pd.Timedelta(minutes=1)
        ).isoformat(),
        "forecasts": live["forecasts"],
    }


def _validation(status="OOS_VALIDATED", admitted=False):
    return {
        "status": "P5_RESEARCH_VALIDATION",
        "asof_session": "2026-01-30",
        "identity": "e" * 64,
        "model_version": "ridge-v1",
        "label_bundle_sha256": "a" * 64,
        "qualification": [
            {
                "style_id": style,
                "horizon": horizon,
                "qualification_status": status,
                "model_admitted": admitted,
                "oos_gate_passed": True,
                "forward_gate_passed": admitted,
            }
            for style in STYLE_IDS for horizon in HORIZONS
        ],
    }


def _wire(monkeypatch, *, forecast=None, validation=None, frozen=None):
    monkeypatch.setattr(
        l2_downstream, "calculate_forecast",
        lambda *a, **k: forecast or _forecast(),
    )
    monkeypatch.setattr(
        l2_downstream, "read_validation_on_or_before",
        lambda *a, **k: validation or _validation(),
    )
    if frozen is not False:
        monkeypatch.setattr(
            l2_downstream, "load_frozen_forecast_v1",
            lambda *a, **k: frozen or _frozen(),
        )


def test_oos_validated_is_not_downstream_eligible(monkeypatch, tmp_path):
    _wire(monkeypatch)
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "RESEARCH_ONLY"
    assert result["code"] == "NO_MODEL_ADMITTED_L2_STYLE_UNITS"
    assert result["admitted_units"] == 0
    assert result["l3_style_context_available"] is False
    assert result["forecast_identity"] == "d" * 64
    assert result["validation_identity"] == "e" * 64
    assert len(result["contexts"]) == 21
    assert all(row["admitted_relative_return"] is None for row in result["contexts"])
    assert not any(row["downstream_context_eligible"] for row in result["contexts"])


def test_only_exact_model_admitted_units_expose_frozen_numeric_context(
    monkeypatch, tmp_path
):
    validation = _validation()
    validation["qualification"][0] = {
        "style_id": STYLE_IDS[0],
        "horizon": HORIZONS[0],
        "qualification_status": "MODEL_ADMITTED",
        "model_admitted": True,
        "oos_gate_passed": True,
        "forward_gate_passed": True,
    }
    _wire(monkeypatch, validation=validation)
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "MODEL_ADMITTED_CONTEXT"
    assert result["admitted_units"] == 1
    assert result["l3_style_context_available"] is True
    eligible = [row for row in result["contexts"] if row["downstream_context_eligible"]]
    assert len(eligible) == 1
    assert eligible[0]["style_id"] == STYLE_IDS[0]
    assert eligible[0]["horizon"] == HORIZONS[0]
    assert eligible[0]["admitted_relative_return"] is not None
    assert result["forecast_identity"] == "d" * 64
    assert not result["decision_eligible"]
    assert not result["real_orders_enabled"]


def test_admitted_model_without_frozen_current_forecast_stays_research_only(
    monkeypatch, tmp_path
):
    validation = _validation("MODEL_ADMITTED", True)
    _wire(monkeypatch, validation=validation, frozen=False)
    monkeypatch.setattr(
        l2_downstream,
        "load_frozen_forecast_v1",
        lambda *a, **k: (_ for _ in ()).throw(
            FileNotFoundError("L2_FROZEN_FORECAST_NOT_FOUND")
        ),
    )
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "RESEARCH_ONLY"
    assert result["code"] == "L2_CURRENT_FORECAST_NOT_FROZEN"
    assert result["l3_style_context_available"] is False


def test_frozen_forecast_must_match_current_model_output(monkeypatch, tmp_path):
    validation = _validation("MODEL_ADMITTED", True)
    frozen = _frozen()
    frozen["forecasts"] = [dict(row) for row in frozen["forecasts"]]
    frozen["forecasts"][0]["predicted_relative_return"] = 0.99
    _wire(monkeypatch, validation=validation, frozen=frozen)
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_FROZEN_FORECAST_DIFFERS_FROM_CURRENT_MODEL_OUTPUT"


def test_model_or_label_bundle_mismatch_blocks_bridge(monkeypatch, tmp_path):
    forecast = _forecast()
    validation = _validation("MODEL_ADMITTED", True)
    validation["model_version"] = "other-model"
    _wire(monkeypatch, forecast=forecast, validation=validation)
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_MODEL_VERSION_MISMATCH"

    validation["model_version"] = forecast["model_version"]
    validation["label_bundle_sha256"] = "c" * 64
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_LABEL_BUNDLE_MISMATCH"


def test_missing_p4_evidence_returns_research_only(monkeypatch, tmp_path):
    forecast = {
        "status": "BLOCKED",
        "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
        "asof_session": "2026-01-30",
    }
    _wire(
        monkeypatch,
        forecast=forecast,
        validation={
            "status": "BLOCKED",
            "code": "L2_P5_VALIDATION_REPORT_NOT_FOUND",
        },
    )
    result = l2_downstream.build_downstream_context(tmp_path)
    assert result["status"] == "RESEARCH_ONLY"
    assert result["code"] == "L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert result["l3_style_context_available"] is False
