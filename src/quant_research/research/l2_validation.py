"""QDR L2 P5 validation, ablation and scoped qualification.

P5 evaluates the P4 continuous relative-return forecast. It does not invent
probability targets. MODEL_ADMITTED is impossible unless the explicit config
switch is enabled *and* both OOS and genuine-forward gates pass.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.research.l2_forecast import (
    FEATURES,
    ForecastConfig,
    walk_forward_oos_v1,
    score_oos_v1,
)
from quant_research.research.l2_forecast_archive import load_frozen_forecast_v1


VALIDATION_PROTOCOL_VERSION = "qdr-l2-validation-v1"
PROBABILITY_CALIBRATION_STATUS = "NOT_APPLICABLE_CONTINUOUS_RETURN_ONLY"

ABLATION_FEATURE_SETS = {
    "returns_only": (
        "relative_return_5d",
        "relative_return_20d",
        "relative_return_60d",
    ),
    "returns_dynamics": (
        "relative_return_5d",
        "relative_return_20d",
        "relative_return_60d",
        "relative_acceleration_5d",
        "relative_up_days_10",
    ),
    "returns_dynamics_risk": (
        "relative_return_5d",
        "relative_return_20d",
        "relative_return_60d",
        "relative_acceleration_5d",
        "relative_up_days_10",
        "relative_volatility_20d",
        "relative_drawdown_20d",
        "relative_drawdown_60d",
    ),
    "full": FEATURES,
}


@dataclass(frozen=True)
class ValidationConfig:
    min_oos_sessions: int = 126
    min_relative_mse_gain_vs_best_baseline: float = 0.02
    min_directional_accuracy: float = 0.52
    min_rank_ic: float = 0.05
    min_positive_subperiod_fraction: float = 0.67
    min_subperiods: int = 3
    max_subperiod_relative_mse_loss: float = 0.10
    min_forward_frozen_sessions_for_admission: int = 60
    min_forward_relative_mse_gain_vs_best_baseline: float = 0.0
    min_forward_directional_accuracy: float = 0.50
    require_all_baselines_beaten: bool = True
    model_admission_enabled: bool = False

    def validate(self) -> None:
        if self.min_oos_sessions < 30:
            raise ValueError("min_oos_sessions must be at least 30")
        if self.min_subperiods < 2 or self.min_subperiods > 12:
            raise ValueError("min_subperiods must be between 2 and 12")
        for name, value in (
            ("min_directional_accuracy", self.min_directional_accuracy),
            ("min_positive_subperiod_fraction", self.min_positive_subperiod_fraction),
            ("min_forward_directional_accuracy", self.min_forward_directional_accuracy),
        ):
            if not 0 <= value <= 1:
                raise ValueError(name + " must be between 0 and 1")
        if self.min_rank_ic < -1 or self.min_rank_ic > 1:
            raise ValueError("min_rank_ic must be between -1 and 1")
        if self.max_subperiod_relative_mse_loss < 0:
            raise ValueError("max_subperiod_relative_mse_loss must be nonnegative")
        if self.min_forward_frozen_sessions_for_admission < 20:
            raise ValueError("forward admission requires at least 20 sessions")
        for value in (
            self.min_relative_mse_gain_vs_best_baseline,
            self.min_forward_relative_mse_gain_vs_best_baseline,
        ):
            if not math.isfinite(value):
                raise ValueError("relative MSE thresholds must be finite")


def run_ablation_oos_v1(
    observations: pd.DataFrame,
    labels: pd.DataFrame,
    exchange_sessions,
    evaluation_dates,
    trading_clock,
    *,
    forecast_config: ForecastConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run predeclared nested feature sets on identical OOS dates."""
    predictions = []
    scores = []
    for variant, columns in ABLATION_FEATURE_SETS.items():
        result = walk_forward_oos_v1(
            observations,
            labels,
            exchange_sessions,
            evaluation_dates,
            trading_clock,
            config=forecast_config,
            feature_columns=tuple(columns),
        )
        if result.empty:
            continue
        result = result.copy()
        result["variant"] = variant
        predictions.append(result)
        scored = score_oos_v1(result)
        if not scored.empty:
            scored = scored.copy()
            scored["variant"] = variant
            scores.append(scored)
    return (
        pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame(),
        pd.concat(scores, ignore_index=True) if scores else pd.DataFrame(),
    )


def _mse(prediction: np.ndarray, truth: np.ndarray) -> float:
    return float(np.mean((prediction - truth) ** 2))


def _relative_gain(model_mse: float, baseline_mse: float) -> float | None:
    if not math.isfinite(baseline_mse) or baseline_mse <= 0:
        return None
    return float((baseline_mse - model_mse) / baseline_mse)


def _horizon_rank_ic(frame: pd.DataFrame) -> dict[int, dict]:
    """Cross-style Spearman IC by date, aggregated per horizon."""
    rows = {}
    for horizon, horizon_rows in frame.groupby("horizon"):
        daily = []
        for _, group in horizon_rows.groupby("date"):
            group = group.dropna(
                subset=["predicted_relative_return", "forward_relative_return"]
            )
            if len(group) < 3:
                continue
            predicted = group.predicted_relative_return.rank(method="average")
            actual = group.forward_relative_return.rank(method="average")
            if predicted.nunique() < 2 or actual.nunique() < 2:
                continue
            value = predicted.corr(actual)
            if pd.notna(value):
                daily.append(float(value))
        if not daily:
            rows[int(horizon)] = {
                "rank_ic": None,
                "rank_icir": None,
                "rank_ic_sessions": 0,
            }
            continue
        values = np.asarray(daily, dtype=float)
        std = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        rows[int(horizon)] = {
            "rank_ic": float(values.mean()),
            "rank_icir": (
                float(values.mean() / std * np.sqrt(len(values)))
                if std > 0 else None
            ),
            "rank_ic_sessions": int(len(values)),
        }
    return rows


def validate_oos_v1(
    predictions: pd.DataFrame,
    *,
    config: ValidationConfig | None = None,
) -> pd.DataFrame:
    """Validate each style/horizon against three baselines and stability gates."""
    config = config or ValidationConfig()
    config.validate()
    required = {
        "date", "style_id", "horizon", "forward_relative_return",
        "predicted_relative_return", "zero_baseline", "mean_baseline",
        "momentum_baseline",
    }
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError("Missing L2 P5 OOS columns: " + ", ".join(sorted(missing)))
    frame = predictions.loc[:, list(required)].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    if frame.duplicated(["date", "style_id", "horizon"]).any():
        raise ValueError("Duplicate L2 P5 OOS rows")
    for column in (
        "forward_relative_return", "predicted_relative_return",
        "zero_baseline", "mean_baseline", "momentum_baseline",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
        invalid = frame[column].notna() & ~np.isfinite(frame[column])
        if invalid.any():
            raise ValueError("Nonfinite L2 P5 OOS metric input: " + column)

    rank_ic = _horizon_rank_ic(frame)
    output = []
    for (style_id, horizon), group in frame.groupby(["style_id", "horizon"]):
        group = group.sort_values("date", kind="stable").dropna(
            subset=[
                "forward_relative_return", "predicted_relative_return",
                "zero_baseline", "mean_baseline", "momentum_baseline",
            ]
        )
        sessions = int(group.date.nunique())
        if group.empty:
            output.append({
                "style_id": style_id,
                "horizon": int(horizon),
                "status": "RESEARCH_ONLY",
                "validation_passed": False,
                "block_reasons": ["NO_SCORABLE_OOS_ROWS"],
                "oos_sessions": 0,
                "protocol_version": VALIDATION_PROTOCOL_VERSION,
                "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
                "decision_eligible": False,
                "real_orders_enabled": False,
            })
            continue

        truth = group.forward_relative_return.to_numpy(dtype=float)
        model = group.predicted_relative_return.to_numpy(dtype=float)
        baselines = {
            "zero": group.zero_baseline.to_numpy(dtype=float),
            "mean": group.mean_baseline.to_numpy(dtype=float),
            "momentum": group.momentum_baseline.to_numpy(dtype=float),
        }
        model_mse = _mse(model, truth)
        baseline_mse = {name: _mse(value, truth) for name, value in baselines.items()}
        best_name = min(baseline_mse, key=baseline_mse.get)
        best_mse = baseline_mse[best_name]
        relative_gain = _relative_gain(model_mse, best_mse)
        all_beaten = all(model_mse < value for value in baseline_mse.values())
        direction = float(np.mean((model > 0) == (truth > 0)))

        unique_dates = pd.DatetimeIndex(sorted(group.date.unique()))
        date_blocks = [
            pd.DatetimeIndex(x) for x in np.array_split(unique_dates, config.min_subperiods)
            if len(x)
        ]
        subperiod_gains = []
        for block in date_blocks:
            part = group.loc[group.date.isin(block)]
            y = part.forward_relative_return.to_numpy(dtype=float)
            p = part.predicted_relative_return.to_numpy(dtype=float)
            model_part_mse = _mse(p, y)
            best_part = min(
                _mse(part.zero_baseline.to_numpy(dtype=float), y),
                _mse(part.mean_baseline.to_numpy(dtype=float), y),
                _mse(part.momentum_baseline.to_numpy(dtype=float), y),
            )
            gain = _relative_gain(model_part_mse, best_part)
            if gain is not None:
                subperiod_gains.append(gain)

        positive_fraction = (
            float(np.mean(np.asarray(subperiod_gains) > 0))
            if subperiod_gains else None
        )
        worst_subperiod_gain = (
            float(min(subperiod_gains)) if subperiod_gains else None
        )
        horizon_ic = rank_ic.get(int(horizon), {
            "rank_ic": None, "rank_icir": None, "rank_ic_sessions": 0
        })
        reasons = []
        if sessions < config.min_oos_sessions:
            reasons.append("INSUFFICIENT_OOS_SESSIONS")
        if config.require_all_baselines_beaten and not all_beaten:
            reasons.append("DOES_NOT_BEAT_ALL_BASELINES")
        if relative_gain is None or relative_gain < config.min_relative_mse_gain_vs_best_baseline:
            reasons.append("INSUFFICIENT_GAIN_VS_BEST_BASELINE")
        if direction < config.min_directional_accuracy:
            reasons.append("DIRECTIONAL_ACCURACY_BELOW_GATE")
        if horizon_ic["rank_ic"] is None:
            reasons.append("INSUFFICIENT_CROSS_STYLE_RANK_IC")
        elif horizon_ic["rank_ic"] < config.min_rank_ic:
            reasons.append("RANK_IC_BELOW_GATE")
        if len(subperiod_gains) < config.min_subperiods:
            reasons.append("INSUFFICIENT_STABILITY_SUBPERIODS")
        else:
            if positive_fraction < config.min_positive_subperiod_fraction:
                reasons.append("SUBPERIOD_CONSISTENCY_BELOW_GATE")
            if worst_subperiod_gain < -config.max_subperiod_relative_mse_loss:
                reasons.append("SUBPERIOD_DRAWDOWN_BELOW_GATE")

        output.append({
            "style_id": style_id,
            "horizon": int(horizon),
            "status": "OOS_VALIDATED" if not reasons else "RESEARCH_ONLY",
            "validation_passed": not reasons,
            "block_reasons": reasons,
            "oos_sessions": sessions,
            "rows": int(len(group)),
            "model_mse": model_mse,
            "zero_mse": baseline_mse["zero"],
            "mean_mse": baseline_mse["mean"],
            "momentum_mse": baseline_mse["momentum"],
            "best_baseline": best_name,
            "best_baseline_mse": best_mse,
            "relative_mse_gain_vs_best_baseline": relative_gain,
            "all_baselines_beaten": all_beaten,
            "directional_accuracy": direction,
            "rank_ic": horizon_ic["rank_ic"],
            "rank_icir": horizon_ic["rank_icir"],
            "rank_ic_sessions": horizon_ic["rank_ic_sessions"],
            "subperiod_count": len(subperiod_gains),
            "positive_subperiod_fraction": positive_fraction,
            "worst_subperiod_relative_mse_gain": worst_subperiod_gain,
            "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
            "protocol_version": VALIDATION_PROTOCOL_VERSION,
            "decision_eligible": False,
            "real_orders_enabled": False,
        })
    return pd.DataFrame(output).sort_values(
        ["style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)


def collect_frozen_forecasts_v1(root: Path, model_version: str) -> pd.DataFrame:
    """Load all integrity-checked P4 frozen snapshots for one model version."""
    root = Path(root).resolve()
    base = root / "outputs/l2_style_forecasts"
    if not base.is_dir():
        return pd.DataFrame()
    rows = []
    for session in sorted(path.name for path in base.iterdir() if path.is_dir()):
        model_path = base / session / model_version / "manifest.json"
        if not model_path.is_file():
            continue
        record = load_frozen_forecast_v1(root, session, model_version)
        for forecast in record["forecasts"]:
            rows.append({
                **forecast,
                "frozen_at_utc": record["frozen_at_utc"],
                "archive_identity": record["identity"],
                "source_snapshot_sha256": record["source_snapshot_sha256"],
                "label_bundle_sha256": record["label_bundle_sha256"],
            })
    return pd.DataFrame(rows)


def score_genuine_forward_v1(
    frozen_forecasts: pd.DataFrame,
    labels: pd.DataFrame,
) -> pd.DataFrame:
    """Score only snapshots frozen after signal and before T+1 entry."""
    if frozen_forecasts.empty:
        return pd.DataFrame()
    frozen_required = {
        "date", "style_id", "horizon", "signal_time", "frozen_at_utc",
        "predicted_relative_return", "zero_baseline", "mean_baseline",
        "momentum_baseline", "forecast_status",
    }
    label_required = {
        "date", "style_id", "horizon", "forward_relative_return",
        "label_available_at", "entry_time", "exit_time",
    }
    if frozen_required - set(frozen_forecasts.columns):
        raise ValueError("Incomplete frozen L2 forward forecast evidence")
    if label_required - set(labels.columns):
        raise ValueError("Incomplete verified L2 forward label evidence")

    frozen = frozen_forecasts.copy()
    outcome = labels.copy()
    frozen["date"] = pd.to_datetime(frozen.date, errors="raise").dt.tz_localize(None).dt.normalize()
    outcome["date"] = pd.to_datetime(outcome.date, errors="raise").dt.tz_localize(None).dt.normalize()
    for column in ("signal_time", "frozen_at_utc"):
        frozen[column] = pd.to_datetime(frozen[column], utc=True, errors="coerce")
    for column in ("label_available_at", "entry_time", "exit_time"):
        outcome[column] = pd.to_datetime(outcome[column], utc=True, errors="coerce")
    if frozen.duplicated(["date", "style_id", "horizon"]).any():
        raise ValueError("Duplicate frozen L2 forward forecast")
    if outcome.duplicated(["date", "style_id", "horizon"]).any():
        raise ValueError("Duplicate verified L2 forward outcome")

    joined = frozen.merge(
        outcome.loc[:, list(label_required)],
        on=["date", "style_id", "horizon"],
        how="inner",
        validate="one_to_one",
    )
    genuine = joined.loc[
        joined.forecast_status.eq("RESEARCH_ONLY")
        & joined.forward_relative_return.notna()
        & joined.frozen_at_utc.notna()
        & joined.signal_time.notna()
        & joined.entry_time.notna()
        & joined.exit_time.notna()
        & joined.label_available_at.notna()
        & joined.frozen_at_utc.ge(joined.signal_time)
        & joined.frozen_at_utc.lt(joined.entry_time)
        & joined.label_available_at.ge(joined.exit_time)
    ].copy()

    rows = []
    for (style_id, horizon), group in genuine.groupby(["style_id", "horizon"]):
        group = group.dropna(subset=[
            "predicted_relative_return", "zero_baseline",
            "mean_baseline", "momentum_baseline", "forward_relative_return",
        ])
        if group.empty:
            continue
        y = group.forward_relative_return.to_numpy(dtype=float)
        model = group.predicted_relative_return.to_numpy(dtype=float)
        baseline_mse = {
            "zero": _mse(group.zero_baseline.to_numpy(dtype=float), y),
            "mean": _mse(group.mean_baseline.to_numpy(dtype=float), y),
            "momentum": _mse(group.momentum_baseline.to_numpy(dtype=float), y),
        }
        model_mse = _mse(model, y)
        best_name = min(baseline_mse, key=baseline_mse.get)
        rows.append({
            "style_id": style_id,
            "horizon": int(horizon),
            "genuine_forward_sessions": int(group.date.nunique()),
            "genuine_forward_rows": int(len(group)),
            "model_mse": model_mse,
            "best_baseline": best_name,
            "best_baseline_mse": baseline_mse[best_name],
            "relative_mse_gain_vs_best_baseline": _relative_gain(
                model_mse, baseline_mse[best_name]
            ),
            "directional_accuracy": float(
                np.mean((model > 0) == (y > 0))
            ),
            "protocol_version": VALIDATION_PROTOCOL_VERSION,
            "decision_eligible": False,
            "real_orders_enabled": False,
        })
    return pd.DataFrame(rows).sort_values(
        ["style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)


def qualify_models_v1(
    oos_validation: pd.DataFrame,
    forward_validation: pd.DataFrame,
    *,
    config: ValidationConfig | None = None,
) -> pd.DataFrame:
    """Combine OOS and genuine-forward evidence into scoped qualification."""
    config = config or ValidationConfig()
    config.validate()
    if oos_validation.empty:
        return pd.DataFrame()
    required = {"style_id", "horizon", "status", "validation_passed"}
    if required - set(oos_validation.columns):
        raise ValueError("Incomplete OOS qualification evidence")
    forward = {
        (row.style_id, int(row.horizon)): row
        for row in forward_validation.itertuples(index=False)
    } if not forward_validation.empty else {}
    rows = []
    for row in oos_validation.itertuples(index=False):
        reasons = []
        oos_ok = row.status == "OOS_VALIDATED" and bool(row.validation_passed)
        if not oos_ok:
            reasons.append("OOS_GATE_NOT_PASSED")
        fwd = forward.get((row.style_id, int(row.horizon)))
        forward_ok = False
        if fwd is None:
            reasons.append("NO_GENUINE_FORWARD_EVIDENCE")
        else:
            if fwd.genuine_forward_sessions < config.min_forward_frozen_sessions_for_admission:
                reasons.append("INSUFFICIENT_GENUINE_FORWARD_SESSIONS")
            if (
                fwd.relative_mse_gain_vs_best_baseline is None
                or fwd.relative_mse_gain_vs_best_baseline
                < config.min_forward_relative_mse_gain_vs_best_baseline
            ):
                reasons.append("FORWARD_GAIN_VS_BASELINE_BELOW_GATE")
            if fwd.directional_accuracy < config.min_forward_directional_accuracy:
                reasons.append("FORWARD_DIRECTIONAL_ACCURACY_BELOW_GATE")
            forward_ok = not any(reason.startswith(("INSUFFICIENT_GENUINE", "FORWARD_")) for reason in reasons)

        evidence_passed = oos_ok and forward_ok
        if evidence_passed and not config.model_admission_enabled:
            reasons.append("MODEL_ADMISSION_SWITCH_DISABLED")
        admitted = evidence_passed and config.model_admission_enabled
        rows.append({
            "style_id": row.style_id,
            "horizon": int(row.horizon),
            "qualification_status": (
                "MODEL_ADMITTED" if admitted
                else "OOS_VALIDATED" if oos_ok
                else "RESEARCH_ONLY"
            ),
            "oos_gate_passed": oos_ok,
            "forward_gate_passed": forward_ok,
            "model_admitted": admitted,
            "reasons": reasons,
            "protocol_version": VALIDATION_PROTOCOL_VERSION,
            "probability_calibration_status": PROBABILITY_CALIBRATION_STATUS,
            "decision_eligible": False,
            "real_orders_enabled": False,
        })
    return pd.DataFrame(rows).sort_values(
        ["style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)
