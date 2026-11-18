"""QDR L2 P4 style-leading forecast research.

This module never manufactures forward labels from the exploratory Yahoo P1
bundle. It only trains when independently verified T+1-open to T+H-close
relative-return labels are supplied with exact timing evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from quant_research.research.l2_style_rotation import STYLE_REGISTRY


FORECAST_PROTOCOL_VERSION = "qdr-l2-style-forecast-v1"
MODEL_VERSION = "ridge-standardscaler-alpha1-v1"
VERIFIED_LABEL_KIND = "VERIFIED_RAW_RELATIVE_RETURN"
HORIZONS = (1, 3, 5)
INPUT_FEATURES = (
    "relative_return_5d",
    "relative_return_20d",
    "relative_return_60d",
    "relative_acceleration_5d",
    "relative_up_days_10",
    "relative_volatility_20d",
    "relative_drawdown_20d",
    "relative_drawdown_60d",
)
DERIVED_FEATURES = (
    "cross_style_dispersion_20d",
    "state_strong_accelerating",
    "state_strong_decelerating",
    "state_weak_improving",
    "state_weak_deteriorating",
)
FEATURES = INPUT_FEATURES + DERIVED_FEATURES
STYLE_IDS = tuple(style.style_id for style in STYLE_REGISTRY)


@dataclass(frozen=True)
class ForecastConfig:
    min_training_sessions: int = 252
    embargo_sessions: int = 5
    ridge_alpha: float = 1.0

    def validate(self) -> None:
        if not 30 <= self.min_training_sessions <= 4000:
            raise ValueError("min_training_sessions must be between 30 and 4000")
        if self.embargo_sessions < max(HORIZONS):
            raise ValueError("embargo_sessions must be at least five sessions")
        if not math.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0:
            raise ValueError("ridge_alpha must be finite and positive")


def _normalize_sessions(exchange_sessions) -> pd.DatetimeIndex:
    sessions = pd.DatetimeIndex(exchange_sessions)
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    sessions = sessions.normalize()
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("exchange_sessions must be unique, ordered session dates")
    return sessions


def _prepare_observations(observations: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "style_id", "available_at", *INPUT_FEATURES}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError("Missing L2 forecast observation columns: " + ", ".join(sorted(missing)))
    frame = observations.loc[:, ["date", "style_id", "available_at", *INPUT_FEATURES]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="coerce")
    if frame["date"].isna().any() or frame["style_id"].isna().any():
        raise ValueError("Forecast observations require dated style identity")
    if frame.duplicated(["date", "style_id"]).any():
        raise ValueError("Duplicate L2 forecast observations")
    unknown = sorted(set(frame.style_id) - set(STYLE_IDS))
    if unknown:
        raise ValueError("Unknown L2 style IDs: " + ",".join(unknown))
    for feature in INPUT_FEATURES:
        values = pd.to_numeric(frame[feature], errors="coerce")
        invalid = values.notna() & ~np.isfinite(values)
        if invalid.any():
            raise ValueError("Nonfinite L2 forecast feature: " + feature)
        frame[feature] = values
    frame["cross_style_dispersion_20d"] = frame.groupby("date")[
        "relative_return_20d"
    ].transform(lambda values: values.std(ddof=1) if values.notna().sum() >= 2 else np.nan)
    known = frame.relative_return_20d.notna() & frame.relative_acceleration_5d.notna()
    strength = frame.relative_return_20d
    acceleration = frame.relative_acceleration_5d
    definitions = {
        "state_strong_accelerating": (strength > 0) & (acceleration > 0),
        "state_strong_decelerating": (strength > 0) & (acceleration < 0),
        "state_weak_improving": (strength < 0) & (acceleration > 0),
        "state_weak_deteriorating": (strength < 0) & (acceleration < 0),
    }
    for feature, mask in definitions.items():
        frame[feature] = np.where(known, mask.astype(float), np.nan)
    return frame.sort_values(["date", "style_id"], kind="stable").reset_index(drop=True)


def validate_forward_labels_v1(labels: pd.DataFrame, trading_clock) -> pd.DataFrame:
    """Validate immutable-style label evidence and exact T+1-open/T+H-close timing."""
    required = {
        "date", "style_id", "horizon", "forward_relative_return",
        "label_available_at", "label_kind", "signal_time", "entry_time", "exit_time",
    }
    missing = required - set(labels.columns)
    if missing:
        raise ValueError("Missing verified style label columns: " + ", ".join(sorted(missing)))
    frame = labels.loc[:, list(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    frame["horizon"] = pd.to_numeric(frame["horizon"], errors="raise").astype(int)
    if not frame.horizon.isin(HORIZONS).all():
        raise ValueError("Style forecast horizon must be H1/H3/H5")
    if frame.duplicated(["date", "style_id", "horizon"]).any():
        raise ValueError("Duplicate verified style labels")
    unknown = sorted(set(frame.style_id) - set(STYLE_IDS))
    if unknown:
        raise ValueError("Unknown style label IDs: " + ",".join(unknown))
    frame["forward_relative_return"] = pd.to_numeric(
        frame["forward_relative_return"], errors="coerce"
    )
    invalid = frame.forward_relative_return.notna() & ~np.isfinite(frame.forward_relative_return)
    if invalid.any():
        raise ValueError("Nonfinite verified style label")
    observed = frame.forward_relative_return.notna()
    if frame.loc[observed, "label_kind"].ne(VERIFIED_LABEL_KIND).any():
        raise ValueError("Exploratory/current-vintage ETF proxy labels cannot train L2 forecasts")
    for column in ("label_available_at", "signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    if frame.loc[observed, ["label_available_at", "signal_time", "entry_time", "exit_time"]].isna().any().any():
        raise ValueError("Verified style labels require complete timezone-aware timing evidence")
    for row in frame.itertuples(index=False):
        if pd.isna(row.signal_time) or pd.isna(row.entry_time) or pd.isna(row.exit_time):
            continue
        window = trading_clock.window(row.date, int(row.horizon))
        if (row.signal_time != pd.Timestamp(window.signal_time)
                or row.entry_time != pd.Timestamp(window.entry_time)
                or row.exit_time != pd.Timestamp(window.exit_time)):
            raise ValueError("Style label timing violates T close to T+H exit")
        if pd.notna(row.forward_relative_return):
            if pd.isna(row.label_available_at) or row.label_available_at < row.exit_time:
                raise ValueError("Verified style label cannot be available before its exit")
    return frame.sort_values(["date", "style_id", "horizon"], kind="stable").reset_index(drop=True)


def _blocked_row(style_id: str, horizon: int, asof: pd.Timestamp, signal_time,
                 reason: str) -> dict:
    return {
        "date": asof.date().isoformat(),
        "style_id": style_id,
        "horizon": int(horizon),
        "predicted_relative_return": None,
        "zero_baseline": 0.0,
        "mean_baseline": None,
        "momentum_baseline": None,
        "train_sessions": 0,
        "training_start_session": None,
        "training_end_session": None,
        "training_label_exit_cutoff": None,
        "signal_time": pd.Timestamp(signal_time).isoformat(),
        "forecast_status": "BLOCKED",
        "block_reason": reason,
        "model_version": MODEL_VERSION,
        "protocol_version": FORECAST_PROTOCOL_VERSION,
        "research_only": True,
        "decision_eligible": False,
        "real_orders_enabled": False,
        "feature_values": None,
        "standardized_coefficients": None,
        "ridge_intercept": None,
    }


def forecast_asof_v1(observations: pd.DataFrame, labels: pd.DataFrame,
                     exchange_sessions, asof, trading_clock, *,
                     config: ForecastConfig | None = None) -> pd.DataFrame:
    """Fit 21 independent research models and predict one completed signal date.

    Every style/horizon produces a row. Missing evidence becomes BLOCKED rather
    than disappearing from the result.
    """
    config = config or ForecastConfig()
    config.validate()
    obs = _prepare_observations(observations)
    lab = validate_forward_labels_v1(labels, trading_clock)
    sessions = _normalize_sessions(exchange_sessions)
    day = pd.Timestamp(asof)
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    day = day.normalize()
    if day not in sessions:
        raise ValueError("asof must be an exchange session")
    position = sessions.get_loc(day)
    if position <= config.embargo_sessions:
        raise ValueError("Insufficient exchange history before forecast date")

    rows = []
    for horizon in HORIZONS:
        window = trading_clock.window(day, horizon)
        signal_time = pd.Timestamp(window.signal_time)
        embargo_end_session = sessions[position - config.embargo_sessions]
        embargo_exit_cutoff = pd.Timestamp(
            trading_clock.calendar.session_close(embargo_end_session)
        )
        for style_id in STYLE_IDS:
            current = obs.loc[obs.date.eq(day) & obs.style_id.eq(style_id)]
            if current.empty:
                rows.append(_blocked_row(
                    style_id, horizon, day, signal_time, "MISSING_CURRENT_STYLE_OBSERVATION"
                ))
                continue
            current = current.iloc[0]
            if pd.isna(current.available_at):
                rows.append(_blocked_row(
                    style_id, horizon, day, signal_time, "MISSING_CURRENT_OBSERVATION_AVAILABILITY"
                ))
                continue
            if current.available_at > signal_time:
                rows.append(_blocked_row(
                    style_id, horizon, day, signal_time, "CURRENT_OBSERVATION_AVAILABLE_AFTER_SIGNAL"
                ))
                continue
            if current.loc[list(FEATURES)].isna().any():
                rows.append(_blocked_row(
                    style_id, horizon, day, signal_time, "INCOMPLETE_CURRENT_FEATURE_VECTOR"
                ))
                continue

            evidence = lab.loc[
                lab.style_id.eq(style_id)
                & lab.horizon.eq(horizon)
                & lab.forward_relative_return.notna()
                & lab.label_available_at.le(signal_time)
                & lab.exit_time.le(embargo_exit_cutoff)
            ].copy()
            evidence = evidence.merge(
                obs, on=["date", "style_id"], how="inner", validate="one_to_one"
            )
            evidence = evidence.loc[
                evidence.available_at.notna()
                & evidence.available_at.le(evidence.signal_time)
            ].dropna(subset=[*FEATURES, "forward_relative_return"])
            n_sessions = int(evidence.date.nunique())
            if n_sessions < config.min_training_sessions:
                row = _blocked_row(
                    style_id, horizon, day, signal_time, "INSUFFICIENT_VERIFIED_TRAINING_SESSIONS"
                )
                row["train_sessions"] = n_sessions
                if n_sessions:
                    row["training_start_session"] = evidence.date.min().date().isoformat()
                    row["training_end_session"] = evidence.date.max().date().isoformat()
                row["training_label_exit_cutoff"] = embargo_exit_cutoff.isoformat()
                rows.append(row)
                continue

            pipeline = make_pipeline(
                StandardScaler(),
                Ridge(alpha=config.ridge_alpha),
            )
            x_train = evidence.loc[:, FEATURES]
            y_train = evidence.forward_relative_return.astype(float)
            pipeline.fit(x_train, y_train)
            x_now = pd.DataFrame(
                [{feature: float(current[feature]) for feature in FEATURES}],
                columns=FEATURES,
            )
            prediction = float(pipeline.predict(x_now)[0])
            scaler = pipeline.named_steps["standardscaler"]
            ridge = pipeline.named_steps["ridge"]
            rows.append({
                "date": day.date().isoformat(),
                "style_id": style_id,
                "horizon": int(horizon),
                "predicted_relative_return": prediction,
                "zero_baseline": 0.0,
                "mean_baseline": float(y_train.mean()),
                "momentum_baseline": float(current.relative_return_5d) * horizon / 5.0,
                "train_sessions": n_sessions,
                "training_start_session": evidence.date.min().date().isoformat(),
                "training_end_session": evidence.date.max().date().isoformat(),
                "training_label_exit_cutoff": embargo_exit_cutoff.isoformat(),
                "signal_time": signal_time.isoformat(),
                "forecast_status": "RESEARCH_ONLY",
                "block_reason": None,
                "model_version": MODEL_VERSION,
                "protocol_version": FORECAST_PROTOCOL_VERSION,
                "research_only": True,
                "decision_eligible": False,
                "real_orders_enabled": False,
                "feature_values": {
                    feature: float(current[feature]) for feature in FEATURES
                },
                "standardized_coefficients": {
                    feature: float(coef)
                    for feature, coef in zip(FEATURES, ridge.coef_, strict=True)
                },
                "ridge_intercept": float(ridge.intercept_),
                "scaler_mean": {
                    feature: float(value)
                    for feature, value in zip(FEATURES, scaler.mean_, strict=True)
                },
                "scaler_scale": {
                    feature: float(value)
                    for feature, value in zip(FEATURES, scaler.scale_, strict=True)
                },
            })
    return pd.DataFrame(rows).sort_values(
        ["style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)


def walk_forward_oos_v1(observations: pd.DataFrame, labels: pd.DataFrame,
                        exchange_sessions, evaluation_dates, trading_clock, *,
                        config: ForecastConfig | None = None) -> pd.DataFrame:
    """Generate causal date-by-date research predictions and attach later outcomes."""
    config = config or ForecastConfig()
    validated = validate_forward_labels_v1(labels, trading_clock)
    sessions = _normalize_sessions(exchange_sessions)
    dates = pd.DatetimeIndex(evaluation_dates)
    if dates.tz is not None:
        dates = dates.tz_localize(None)
    dates = dates.normalize()
    if dates.has_duplicates or not dates.isin(sessions).all():
        raise ValueError("evaluation_dates must be unique exchange sessions")

    output = []
    actual = validated.loc[validated.forward_relative_return.notna(), [
        "date", "style_id", "horizon", "forward_relative_return",
        "label_available_at", "exit_time",
    ]]
    for day in dates:
        prediction = forecast_asof_v1(
            observations, validated, sessions, day, trading_clock, config=config
        )
        prediction = prediction.loc[prediction.forecast_status.eq("RESEARCH_ONLY")].copy()
        if prediction.empty:
            continue
        prediction["date"] = pd.to_datetime(prediction.date)
        merged = prediction.merge(
            actual, on=["date", "style_id", "horizon"], how="left", validate="one_to_one"
        )
        output.append(merged)
    if not output:
        return pd.DataFrame()
    return pd.concat(output, ignore_index=True).sort_values(
        ["date", "style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)


def score_oos_v1(predictions: pd.DataFrame, *, min_oos_sessions: int = 60) -> pd.DataFrame:
    """Score P4 predictions against zero, expanding mean and momentum baselines."""
    required = {
        "date", "style_id", "horizon", "forward_relative_return",
        "predicted_relative_return", "zero_baseline", "mean_baseline",
        "momentum_baseline",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError("Missing P4 OOS scoring columns: " + ", ".join(sorted(missing)))
    if predictions.duplicated(["date", "style_id", "horizon"]).any():
        raise ValueError("Duplicate P4 OOS predictions")
    rows = []
    for (style_id, horizon), group in predictions.groupby(["style_id", "horizon"]):
        group = group.dropna(subset=[
            "forward_relative_return", "predicted_relative_return",
            "zero_baseline", "mean_baseline", "momentum_baseline",
        ])
        if group.empty:
            continue
        y = group.forward_relative_return.astype(float).to_numpy()
        model = group.predicted_relative_return.astype(float).to_numpy()
        zero = group.zero_baseline.astype(float).to_numpy()
        mean = group.mean_baseline.astype(float).to_numpy()
        momentum = group.momentum_baseline.astype(float).to_numpy()

        def mse(x):
            return float(np.mean((x - y) ** 2))

        model_mse, zero_mse, mean_mse, momentum_mse = map(
            mse, (model, zero, mean, momentum)
        )
        rows.append({
            "style_id": style_id,
            "horizon": int(horizon),
            "sessions": int(group.date.nunique()),
            "rows": int(len(group)),
            "mae": float(np.mean(np.abs(model - y))),
            "rmse": float(np.sqrt(model_mse)),
            "oos_mse": model_mse,
            "zero_mse": zero_mse,
            "mean_mse": mean_mse,
            "momentum_mse": momentum_mse,
            "mse_gain_vs_zero": zero_mse - model_mse,
            "mse_gain_vs_mean": mean_mse - model_mse,
            "mse_gain_vs_momentum": momentum_mse - model_mse,
            "directional_accuracy": float(np.mean((model > 0) == (y > 0))),
            "status": (
                "RESEARCH_ONLY"
                if group.date.nunique() >= min_oos_sessions
                else "INSUFFICIENT_OOS_SESSIONS"
            ),
            "model_version": MODEL_VERSION,
            "protocol_version": FORECAST_PROTOCOL_VERSION,
            "decision_eligible": False,
            "real_orders_enabled": False,
        })
    return pd.DataFrame(rows).sort_values(
        ["style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)
