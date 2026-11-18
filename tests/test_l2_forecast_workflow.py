"""P4 read-only forecast workflow tests."""
from pathlib import Path

import pandas as pd

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow import l2_forecast


def test_missing_label_bundle_is_explicit_blocker(tmp_path):
    config = tmp_path / "configs"
    config.mkdir()
    (config / "l2_forecast.yaml").write_text(
        "label_bundle_id: null\nmin_training_sessions: 252\nembargo_sessions: 5\nridge_alpha: 1.0\n",
        encoding="utf-8",
    )
    result = l2_forecast.calculate_forecast(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert result["eligible_units"] == 0
    assert result["blocked_units"] == 21
    assert result["forecasts"] == []
    assert result["historical_decision_eligible"] is False
    assert result["real_orders_enabled"] is False


def test_configured_bundle_drives_21_research_units_without_writes(tmp_path, monkeypatch):
    config = tmp_path / "configs"
    config.mkdir()
    (config / "l2_forecast.yaml").write_text(
        "label_bundle_id: accepted-v1\nmin_training_sessions: 60\nembargo_sessions: 5\nridge_alpha: 1.0\n",
        encoding="utf-8",
    )
    calls = []
    labels = pd.DataFrame({"x": [1]})
    manifest = {
        "labels_sha256": "a" * 64,
        "source_evidence_sha256": "b" * 64,
    }
    monkeypatch.setattr(
        l2_forecast, "load_label_bundle_v1",
        lambda root, bundle_id, clock: calls.append(("labels", bundle_id)) or (labels, manifest),
    )
    sessions = pd.bdate_range("2025-01-02", periods=80)
    observations = pd.DataFrame({"placeholder": [1]})
    metadata = {
        "asof_date_et": str(sessions[-1].date()),
        "knowledge_cutoff_utc": "2025-04-23T22:00:00+00:00",
        "snapshot_sha256": "c" * 64,
        "source": "YAHOO",
        "adjustment_basis": "yahoo_split_adjusted",
    }
    monkeypatch.setattr(
        l2_forecast, "load_observation_frame",
        lambda root, **kwargs: (
            calls.append(("observations", kwargs)) or
            (observations, pd.DataFrame(), metadata, sessions, pd.Timestamp("2025-04-23T22:00:00Z"))
        ),
    )
    rows = []
    for style in STYLE_IDS:
        for horizon in HORIZONS:
            rows.append({
                "date": metadata["asof_date_et"],
                "style_id": style,
                "horizon": horizon,
                "predicted_relative_return": 0.001,
                "zero_baseline": 0.0,
                "mean_baseline": 0.0002,
                "momentum_baseline": 0.0003,
                "forecast_status": "RESEARCH_ONLY",
                "block_reason": None,
                "decision_eligible": False,
                "real_orders_enabled": False,
            })
    monkeypatch.setattr(
        l2_forecast, "forecast_asof_v1",
        lambda observations, labels, sessions, day, clock, config: (
            calls.append(("forecast", config)) or pd.DataFrame(rows)
        ),
    )
    result = l2_forecast.calculate_forecast(tmp_path)
    assert result["status"] == "RESEARCH_ONLY"
    assert result["eligible_units"] == 21
    assert result["blocked_units"] == 0
    assert len(result["forecasts"]) == 21
    assert result["label_bundle_id"] == "accepted-v1"
    assert result["source_snapshot_sha256"] == "c" * 64
    assert result["label_bundle_sha256"] == "a" * 64
    assert result["historical_decision_eligible"] is False
    assert result["real_orders_enabled"] is False
    assert calls[0] == ("labels", "accepted-v1")
    assert calls[1][0] == "observations"
    assert calls[2][0] == "forecast"


def test_horizon_filter_keeps_seven_explicit_units(tmp_path, monkeypatch):
    config = tmp_path / "configs"
    config.mkdir()
    (config / "l2_forecast.yaml").write_text(
        "label_bundle_id: accepted-v1\nmin_training_sessions: 60\nembargo_sessions: 5\nridge_alpha: 1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        l2_forecast, "load_label_bundle_v1",
        lambda *args: (pd.DataFrame(), {
            "labels_sha256": "a" * 64, "source_evidence_sha256": "b" * 64,
        }),
    )
    sessions = pd.bdate_range("2025-01-02", periods=80)
    metadata = {
        "asof_date_et": str(sessions[-1].date()),
        "knowledge_cutoff_utc": "2025-04-23T22:00:00+00:00",
        "snapshot_sha256": "c" * 64,
        "source": "YAHOO",
    }
    monkeypatch.setattr(
        l2_forecast, "load_observation_frame",
        lambda *args, **kwargs: (
            pd.DataFrame(), pd.DataFrame(), metadata, sessions,
            pd.Timestamp("2025-04-23T22:00:00Z"),
        ),
    )
    rows = [
        {
            "date": metadata["asof_date_et"], "style_id": style, "horizon": horizon,
            "predicted_relative_return": None, "zero_baseline": 0.0,
            "mean_baseline": None, "momentum_baseline": None,
            "forecast_status": "BLOCKED", "block_reason": "INSUFFICIENT_VERIFIED_TRAINING_SESSIONS",
            "decision_eligible": False, "real_orders_enabled": False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ]
    monkeypatch.setattr(
        l2_forecast, "forecast_asof_v1",
        lambda *args, **kwargs: pd.DataFrame(rows),
    )
    result = l2_forecast.calculate_forecast(tmp_path, horizon=3)
    assert len(result["forecasts"]) == 7
    assert result["blocked_units"] == 7
    assert {row["horizon"] for row in result["forecasts"]} == {3}
