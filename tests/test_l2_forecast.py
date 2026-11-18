"""P4 style-leading forecasts: verified-label timing, baselines and walk-forward."""
import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import (
    FEATURES, INPUT_FEATURES, HORIZONS, STYLE_IDS, ForecastConfig,
    forecast_asof_v1, score_oos_v1, validate_forward_labels_v1,
    walk_forward_oos_v1,
)


def _fixture(n=170):
    clock = TradingClock()
    sessions = clock.calendar.sessions_in_range("2024-01-02", "2026-12-31")[:n]
    rows = []
    for style_i, style in enumerate(STYLE_IDS):
        for i, day in enumerate(sessions):
            base = (i - 70) * 0.00015 + style_i * 0.0003
            rows.append({
                "date": day,
                "style_id": style,
                "available_at": pd.Timestamp(clock.close(day)) + pd.Timedelta(minutes=5),
                "relative_return_5d": base + np.sin(i * 0.17 + style_i) * 0.006,
                "relative_return_20d": base * 2 + np.sin(i * 0.08 + style_i) * 0.014,
                "relative_return_60d": base * 3 + np.sin(i * 0.03 + style_i) * 0.022,
                "relative_acceleration_5d": np.cos(i * 0.13 + style_i) * 0.004,
                "relative_up_days_10": float(5 + ((i + style_i) % 5)),
                "relative_volatility_20d": 0.008 + style_i * 0.0004 + (i % 9) * 0.0001,
                "relative_drawdown_20d": -0.002 * (1 + (i + style_i) % 5),
                "relative_drawdown_60d": -0.003 * (1 + (i + 2 * style_i) % 7),
            })
    observations = pd.DataFrame(rows)
    labels = []
    obs_index = observations.set_index(["date", "style_id"])
    for day in sessions[:-5]:
        for style_i, style in enumerate(STYLE_IDS):
            x = obs_index.loc[(day, style)]
            for horizon in HORIZONS:
                window = clock.window(day, horizon)
                target = (
                    0.28 * float(x.relative_return_5d)
                    + 0.16 * float(x.relative_acceleration_5d)
                    - 0.08 * float(x.relative_volatility_20d)
                    + horizon * 0.00015
                    + style_i * 0.00003
                )
                labels.append({
                    "date": day,
                    "style_id": style,
                    "horizon": horizon,
                    "forward_relative_return": target,
                    "label_available_at": pd.Timestamp(window.exit_time) + pd.Timedelta(minutes=20),
                    "label_kind": "VERIFIED_RAW_RELATIVE_RETURN",
                    "signal_time": pd.Timestamp(window.signal_time),
                    "entry_time": pd.Timestamp(window.entry_time),
                    "exit_time": pd.Timestamp(window.exit_time),
                })
    return clock, sessions, observations, pd.DataFrame(labels)


def test_forecast_returns_21_explicit_style_horizon_rows_and_three_baselines():
    clock, sessions, observations, labels = _fixture()
    day = sessions[-1]
    result = forecast_asof_v1(
        observations, labels, sessions, day, clock,
        config=ForecastConfig(min_training_sessions=60, embargo_sessions=5),
    )
    assert len(result) == len(STYLE_IDS) * len(HORIZONS) == 21
    assert set(result.style_id) == set(STYLE_IDS)
    assert set(result.horizon) == set(HORIZONS)
    assert set(result.forecast_status) == {"RESEARCH_ONLY"}
    assert result.predicted_relative_return.notna().all()
    assert result.zero_baseline.eq(0).all()
    assert result.mean_baseline.notna().all()
    assert result.momentum_baseline.notna().all()
    assert result.train_sessions.ge(60).all()
    assert not result.decision_eligible.any()
    assert not result.real_orders_enabled.any()
    first = result.iloc[0]
    assert set(first.feature_values) == set(FEATURES)
    assert set(first.standardized_coefficients) == set(FEATURES)


def test_exploratory_or_badly_timed_labels_fail_closed():
    clock, sessions, observations, labels = _fixture()
    invalid = labels.copy()
    invalid.loc[0, "label_kind"] = "EXPLORATORY_ETF_PRICE_PROXY"
    with pytest.raises(ValueError, match="cannot train"):
        validate_forward_labels_v1(invalid, clock)

    invalid = labels.copy()
    invalid.loc[0, "entry_time"] = invalid.loc[0, "signal_time"]
    with pytest.raises(ValueError, match="timing"):
        validate_forward_labels_v1(invalid, clock)

    invalid = labels.copy()
    invalid.loc[0, "label_available_at"] = invalid.loc[0, "signal_time"]
    with pytest.raises(ValueError, match="before its exit"):
        validate_forward_labels_v1(invalid, clock)


def test_missing_current_feature_and_late_observation_create_blocked_rows():
    clock, sessions, observations, labels = _fixture()
    day = sessions[-1]
    broken = observations.copy()
    mask = broken.date.eq(day) & broken.style_id.eq("size")
    broken.loc[mask, "relative_return_60d"] = np.nan
    mask2 = broken.date.eq(day) & broken.style_id.eq("quality")
    broken.loc[mask2, "available_at"] = (
        pd.Timestamp(clock.window(day, 1).signal_time) + pd.Timedelta(minutes=1)
    )
    result = forecast_asof_v1(
        broken, labels, sessions, day, clock,
        config=ForecastConfig(min_training_sessions=60),
    )
    size = result.loc[result.style_id.eq("size")]
    quality = result.loc[result.style_id.eq("quality")]
    assert set(size.forecast_status) == {"BLOCKED"}
    assert set(size.block_reason) == {"INCOMPLETE_CURRENT_FEATURE_VECTOR"}
    assert set(quality.forecast_status) == {"BLOCKED"}
    assert set(quality.block_reason) == {"CURRENT_OBSERVATION_AVAILABLE_AFTER_SIGNAL"}
    assert result.loc[result.style_id.eq("momentum"), "forecast_status"].eq("RESEARCH_ONLY").all()


def test_training_uses_only_labels_known_before_signal_and_embargo_cutoff():
    clock, sessions, observations, labels = _fixture()
    day = sessions[-1]
    config = ForecastConfig(min_training_sessions=60, embargo_sessions=5)
    baseline = forecast_asof_v1(observations, labels, sessions, day, clock, config=config)

    changed = labels.copy()
    # Modify labels whose exits lie inside the embargo region or in the future.
    cutoff_session = sessions[sessions.get_loc(day) - config.embargo_sessions]
    cutoff = pd.Timestamp(clock.calendar.session_close(cutoff_session))
    leaked = pd.to_datetime(changed.exit_time, utc=True).gt(cutoff)
    changed.loc[leaked, "forward_relative_return"] = 999.0
    recomputed = forecast_asof_v1(observations, changed, sessions, day, clock, config=config)
    pd.testing.assert_series_equal(
        baseline.predicted_relative_return,
        recomputed.predicted_relative_return,
        check_names=False,
    )
    pd.testing.assert_series_equal(
        baseline.mean_baseline,
        recomputed.mean_baseline,
        check_names=False,
    )


def test_future_observations_do_not_change_earlier_forecast():
    clock, sessions, observations, labels = _fixture()
    day = sessions[-10]
    config = ForecastConfig(min_training_sessions=60)
    baseline = forecast_asof_v1(observations, labels, sessions, day, clock, config=config)
    changed = observations.copy()
    changed.loc[changed.date.gt(day), list(INPUT_FEATURES)] = 123.0
    recomputed = forecast_asof_v1(changed, labels, sessions, day, clock, config=config)
    pd.testing.assert_series_equal(
        baseline.predicted_relative_return,
        recomputed.predicted_relative_return,
        check_names=False,
    )


def test_walk_forward_scoring_reports_model_against_all_three_baselines():
    clock, sessions, observations, labels = _fixture()
    config = ForecastConfig(min_training_sessions=60)
    evaluation = sessions[-12:-5]
    oos = walk_forward_oos_v1(
        observations, labels, sessions, evaluation, clock, config=config
    )
    assert not oos.empty
    assert oos.forward_relative_return.notna().all()
    scores = score_oos_v1(oos, min_oos_sessions=5)
    assert len(scores) == 21
    assert scores.sessions.ge(5).all()
    for column in (
        "oos_mse", "zero_mse", "mean_mse", "momentum_mse",
        "mse_gain_vs_zero", "mse_gain_vs_mean", "mse_gain_vs_momentum",
        "directional_accuracy",
    ):
        assert scores[column].notna().all()
    assert not scores.decision_eligible.any()
    assert not scores.real_orders_enabled.any()


def test_insufficient_verified_history_is_explicitly_blocked_not_omitted():
    clock, sessions, observations, labels = _fixture()
    result = forecast_asof_v1(
        observations, labels, sessions, sessions[-1], clock,
        config=ForecastConfig(min_training_sessions=169),
    )
    assert len(result) == 21
    assert set(result.forecast_status) == {"BLOCKED"}
    assert set(result.block_reason) == {"INSUFFICIENT_VERIFIED_TRAINING_SESSIONS"}
    assert result.train_sessions.gt(0).all()
