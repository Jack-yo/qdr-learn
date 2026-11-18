"""L3 OOS cannot evaluate periods selected before the fixed L2 admission."""
import pandas as pd
import pytest

from quant_research.workflow import l2_l3_binding, v4_study_cli


def _receipt():
    return {
        "contract_version": l2_l3_binding.CONTRACT_VERSION,
        "scope": "PIT_REPLAY_HISTORY_PLUS_CURRENT_FORWARD",
        "start_session": "2025-01-02",
        "end_session": "2026-02-05",
        "rows": 275,
        "style_columns": ["style_l2_quality_h3"],
        "context_identity_sha256": "1" * 64,
        "context_modes": [
            "CURRENT_FROZEN_FORWARD",
            "HISTORICAL_PIT_REPLAY",
        ],
        "admission_asof_session": "2026-01-30",
        "admission_validation_identity": "2" * 64,
        "current_forward_session": "2026-02-05",
        "historical_replay_rows": 274,
        "current_forward_rows": 1,
        "model_versions": ["ridge-v1"],
        "label_bundle_sha256s": ["3" * 64],
        "feature_bundle_sha256s": ["4" * 64],
        "source_snapshot_sha256s": ["5" * 64],
        "binding_verified": True,
        "historical_pit_attested": True,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def _inputs():
    return (
        {
            "market_style": pd.DataFrame([{
                "date": pd.Timestamp("2026-02-05"),
                "state_available_at": "2026-02-05T21:16:00Z",
                "market_return_5": 0.01,
                "style_l2_quality_h3": 0.002,
            }]),
            "factors": pd.DataFrame(),
            "labels": pd.DataFrame(),
        },
        {
            "factor_names": ["alpha"],
            "source_snapshot_sha256": "6" * 64,
            "l2_style_context_receipt": _receipt(),
        },
    )


def _patch_common(monkeypatch, tmp_path):
    monkeypatch.setattr(
        v4_study_cli, "_checked_inputs",
        lambda root, bundle_id: _inputs(),
    )
    monkeypatch.setattr(
        l2_l3_binding, "verify_l2_style_history_binding",
        lambda *args, **kwargs: _receipt(),
    )
    config = tmp_path / "configs/experiments"
    config.mkdir(parents=True)
    (config / "v4_research.yaml").write_text(
        """
oos:
  min_training_sessions: 30
  training_window_sessions: 60
  calibration_sessions: 10
  gap_sessions: 5
  min_calibration_per_class: 2
  ridge_alpha: 1.0
  logistic_c: 1.0
  downside_threshold: -0.02
  seed: 42
""".strip(),
        encoding="utf-8",
    )


def test_l3_oos_cannot_start_on_or_before_l2_admission(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    with pytest.raises(
        ValueError, match="V4_L3_OOS_MUST_START_AFTER_L2_ADMISSION"
    ):
        v4_study_cli.run_managed_alpha_study(
            tmp_path,
            bundle_id="bound-v1",
            run_id="too-early",
            evaluation_start="2026-01-30",
            evaluation_end="2026-02-05",
        )


def test_l3_oos_after_l2_admission_can_enter_model_study(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    called = []
    monkeypatch.setattr(
        v4_study_cli,
        "study_conditional_alpha",
        lambda **kwargs: called.append(kwargs["evaluation_dates"]) or {
            "status": "RESEARCH_ONLY_NOT_ADMITTED_TO_PAPER"
        },
    )
    monkeypatch.setattr(
        v4_study_cli,
        "write_research_run",
        lambda *args, **kwargs: {"manifest_sha256": "7" * 64},
    )
    result = v4_study_cli.run_managed_alpha_study(
        tmp_path,
        bundle_id="bound-v1",
        run_id="post-admission",
        evaluation_start="2026-02-02",
        evaluation_end="2026-02-05",
    )
    assert result["status"] == "V4_OOS_RESEARCH_ARCHIVED_NO_EXECUTION"
    assert called
    assert pd.DatetimeIndex(called[0]).min() > pd.Timestamp("2026-01-30")
    assert result["real_orders_enabled"] is False
    assert result["historical_decision_eligible"] is False
