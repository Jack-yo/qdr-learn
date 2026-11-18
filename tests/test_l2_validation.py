"""P5 validation tests: baseline gates, stability, genuine-forward timing and admission."""
import numpy as np
import pandas as pd

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.research.l2_validation import (
    ABLATION_FEATURE_SETS,
    PROBABILITY_CALIBRATION_STATUS,
    ValidationConfig,
    qualify_models_v1,
    score_genuine_forward_v1,
    validate_oos_v1,
)


def _oos(days=150, *, noisy=False):
    dates = pd.bdate_range("2025-01-02", periods=days)
    rows = []
    for d_i, day in enumerate(dates):
        for s_i, style in enumerate(STYLE_IDS):
            signal = (s_i - 3) * 0.002 + np.sin(d_i * 0.09 + s_i) * 0.003
            for horizon in HORIZONS:
                actual = signal + horizon * 0.0001
                prediction = actual * (0.92 if not noisy else -0.4)
                rows.append({
                    "date": day,
                    "style_id": style,
                    "horizon": horizon,
                    "forward_relative_return": actual,
                    "predicted_relative_return": prediction,
                    "zero_baseline": 0.0,
                    "mean_baseline": 0.0002,
                    "momentum_baseline": signal * 0.45,
                })
    return pd.DataFrame(rows)


def test_strong_oos_result_passes_all_predeclared_gates():
    result = validate_oos_v1(_oos())
    assert len(result) == 21
    assert set(result.status) == {"OOS_VALIDATED"}
    assert result.validation_passed.all()
    assert result.all_baselines_beaten.all()
    assert result.relative_mse_gain_vs_best_baseline.gt(0.02).all()
    assert result.directional_accuracy.ge(0.52).all()
    assert result.rank_ic.ge(0.05).all()
    assert result.positive_subperiod_fraction.ge(0.67).all()
    assert set(result.probability_calibration_status) == {
        PROBABILITY_CALIBRATION_STATUS
    }
    assert not result.decision_eligible.any()
    assert not result.real_orders_enabled.any()


def test_bad_model_stays_research_only_with_reasons():
    result = validate_oos_v1(_oos(noisy=True))
    assert set(result.status) == {"RESEARCH_ONLY"}
    assert not result.validation_passed.any()
    assert all(len(reasons) > 0 for reasons in result.block_reasons)
    assert any(
        "DOES_NOT_BEAT_ALL_BASELINES" in reasons
        for reasons in result.block_reasons
    )


def test_insufficient_oos_history_does_not_validate_even_when_fit_is_good():
    result = validate_oos_v1(_oos(days=60))
    assert set(result.status) == {"RESEARCH_ONLY"}
    assert all(
        "INSUFFICIENT_OOS_SESSIONS" in reasons
        for reasons in result.block_reasons
    )


def _forward_evidence(days=70):
    dates = pd.bdate_range("2026-01-02", periods=days)
    forecasts, labels = [], []
    for d_i, day in enumerate(dates):
        signal_time = pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=21)
        entry_time = signal_time + pd.Timedelta(hours=12)
        for s_i, style in enumerate(STYLE_IDS):
            value = (s_i - 3) * 0.0015 + np.sin(d_i * 0.11 + s_i) * 0.002
            for horizon in HORIZONS:
                actual = value + horizon * 0.0001
                forecasts.append({
                    "date": day,
                    "style_id": style,
                    "horizon": horizon,
                    "signal_time": signal_time,
                    "frozen_at_utc": signal_time + pd.Timedelta(minutes=5),
                    "predicted_relative_return": actual * 0.9,
                    "zero_baseline": 0.0,
                    "mean_baseline": 0.0001,
                    "momentum_baseline": value * 0.4,
                    "forecast_status": "RESEARCH_ONLY",
                })
                exit_time = entry_time + pd.Timedelta(days=horizon)
                labels.append({
                    "date": day,
                    "style_id": style,
                    "horizon": horizon,
                    "forward_relative_return": actual,
                    "label_available_at": exit_time + pd.Timedelta(minutes=20),
                    "entry_time": entry_time,
                    "exit_time": exit_time,
                })
    return pd.DataFrame(forecasts), pd.DataFrame(labels)


def test_genuine_forward_score_excludes_predictions_frozen_after_entry():
    frozen, labels = _forward_evidence()
    late = frozen.copy()
    mask = late.style_id.eq("size") & late.horizon.eq(1)
    merged_entry = labels.loc[mask, ["date", "style_id", "horizon", "entry_time"]]
    lookup = {
        (row.date, row.style_id, row.horizon): row.entry_time
        for row in merged_entry.itertuples(index=False)
    }
    for idx in late.index[mask]:
        row = late.loc[idx]
        late.loc[idx, "frozen_at_utc"] = lookup[
            (row.date, row.style_id, row.horizon)
        ] + pd.Timedelta(minutes=1)

    scored = score_genuine_forward_v1(late, labels)
    size_h1 = scored.loc[
        scored.style_id.eq("size") & scored.horizon.eq(1)
    ]
    assert size_h1.empty
    other = scored.loc[
        scored.style_id.eq("quality") & scored.horizon.eq(3)
    ].iloc[0]
    assert other.genuine_forward_sessions == 70
    assert other.relative_mse_gain_vs_best_baseline > 0
    assert other.directional_accuracy >= 0.5


def test_default_admission_switch_never_promotes_model():
    oos = validate_oos_v1(_oos())
    frozen, labels = _forward_evidence()
    forward = score_genuine_forward_v1(frozen, labels)
    qualified = qualify_models_v1(oos, forward)
    assert len(qualified) == 21
    assert set(qualified.qualification_status) == {"OOS_VALIDATED"}
    assert qualified.oos_gate_passed.all()
    assert qualified.forward_gate_passed.all()
    assert not qualified.model_admitted.any()
    assert all(
        "MODEL_ADMISSION_SWITCH_DISABLED" in reasons
        for reasons in qualified.reasons
    )


def test_explicit_admission_requires_both_oos_and_forward_gates():
    oos = validate_oos_v1(_oos())
    frozen, labels = _forward_evidence()
    forward = score_genuine_forward_v1(frozen, labels)
    config = ValidationConfig(model_admission_enabled=True)
    qualified = qualify_models_v1(oos, forward, config=config)
    assert set(qualified.qualification_status) == {"MODEL_ADMITTED"}
    assert qualified.model_admitted.all()
    assert not qualified.decision_eligible.any()
    assert not qualified.real_orders_enabled.any()

    short_forward = forward.copy()
    short_forward["genuine_forward_sessions"] = 10
    blocked = qualify_models_v1(oos, short_forward, config=config)
    assert set(blocked.qualification_status) == {"OOS_VALIDATED"}
    assert not blocked.model_admitted.any()


def test_ablation_sets_are_nested_and_full_matches_p4_features():
    names = list(ABLATION_FEATURE_SETS)
    assert names == [
        "returns_only",
        "returns_dynamics",
        "returns_dynamics_risk",
        "full",
    ]
    previous = set()
    for name in names:
        current = set(ABLATION_FEATURE_SETS[name])
        assert previous <= current
        previous = current
