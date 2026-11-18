"""Verified historical L2 style-feature construction for P4/P5 training.

This path is separate from the daily Yahoo observation desk. Historical model
features are admitted only when each contributing close has explicit source
availability and corporate-action evidence, and the completed feature is known
no later than the T-day signal.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_research.research.l2_forecast import INPUT_FEATURES
from quant_research.research.l2_style_rotation import (
    REQUIRED_SYMBOLS,
    STYLE_REGISTRY,
    style_observations_v1,
)


FEATURE_PROTOCOL_VERSION = "qdr-l2-verified-feature-v1"
REQUIRED_FEATURE_PRICE_BASIS = "VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS"


def _matrix(name: str, frame: pd.DataFrame, sessions: pd.DatetimeIndex) -> None:
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(name + " requires a session-indexed DataFrame")
    index = (
        frame.index.tz_localize(None).normalize()
        if frame.index.tz is not None else frame.index.normalize()
    )
    if not index.equals(sessions):
        raise ValueError(name + " must use the exact exchange-session index")
    if frame.columns.has_duplicates:
        raise ValueError(name + " contains duplicate symbols")
    missing = sorted(set(REQUIRED_SYMBOLS) - set(frame.columns))
    if missing:
        raise ValueError(name + " missing symbols: " + ",".join(missing))


def build_verified_style_features_v1(
    close_prices: pd.DataFrame,
    availability: pd.DataFrame,
    action_verified: pd.DataFrame,
    exchange_sessions,
    trading_clock,
    *,
    price_basis: str,
    action_evidence_version: str,
) -> pd.DataFrame:
    """Build causal P1-style features with per-row historical PIT eligibility."""
    if price_basis != REQUIRED_FEATURE_PRICE_BASIS:
        raise ValueError(
            "L2 historical features require verified action-consistent source history"
        )
    if not isinstance(action_evidence_version, str) or not action_evidence_version.strip():
        raise ValueError("action_evidence_version is required")
    sessions = pd.DatetimeIndex(exchange_sessions)
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    sessions = sessions.normalize()
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("exchange_sessions must be unique and increasing")
    for name, frame in (
        ("close_prices", close_prices),
        ("availability", availability),
        ("action_verified", action_verified),
    ):
        _matrix(name, frame, sessions)
    if not (
        close_prices.columns.equals(availability.columns)
        and close_prices.columns.equals(action_verified.columns)
    ):
        raise ValueError("L2 feature evidence matrices must have identical columns")

    closes = close_prices.loc[:, REQUIRED_SYMBOLS].apply(
        pd.to_numeric, errors="coerce"
    )
    known = availability.loc[:, REQUIRED_SYMBOLS].apply(
        pd.to_datetime, utc=True, errors="coerce"
    )
    verified = action_verified.loc[:, REQUIRED_SYMBOLS].fillna(False).astype(bool)
    if (closes.notna() & closes.le(0)).any().any():
        raise ValueError("Verified historical closes must be positive")

    # A close without corporate-action coverage is unusable, rather than
    # silently trusting a revised adjusted-price history.
    gated_closes = closes.where(verified)
    gated_availability = known.where(verified)
    observations = style_observations_v1(gated_closes, gated_availability)

    signal_times = {}
    for day in sessions:
        signal_times[day] = pd.Timestamp(
            trading_clock.signal(day)
        ).tz_convert("UTC")
    observations["signal_time"] = observations["date"].map(signal_times)
    observations["feature_pit_eligible"] = (
        observations["complete_historical_window"].eq(True)
        & observations["available_at"].notna()
        & observations["available_at"].le(observations["signal_time"])
    )
    observations["feature_status"] = np.where(
        observations["feature_pit_eligible"],
        "VERIFIED_PIT_FEATURE",
        "BLOCKED",
    )
    observations["feature_block_reason"] = None
    warmup = observations["relative_return_60d"].isna()
    observations.loc[
        ~observations.feature_pit_eligible & warmup,
        "feature_block_reason",
    ] = "INCOMPLETE_60D_OR_ACTION_COVERAGE_WINDOW"
    observations.loc[
        ~observations.feature_pit_eligible
        & observations["available_at"].isna()
        & ~warmup,
        "feature_block_reason",
    ] = "MISSING_SOURCE_AVAILABILITY"
    observations.loc[
        ~observations.feature_pit_eligible
        & observations["available_at"].notna()
        & observations["available_at"].gt(observations["signal_time"]),
        "feature_block_reason",
    ] = "FEATURE_AVAILABLE_AFTER_SIGNAL"
    observations["feature_protocol_version"] = FEATURE_PROTOCOL_VERSION
    observations["feature_price_basis"] = REQUIRED_FEATURE_PRICE_BASIS
    observations["action_evidence_version"] = action_evidence_version
    observations["historical_pit_attested"] = observations["feature_pit_eligible"]
    observations["decision_eligible"] = False
    observations["real_orders_enabled"] = False

    # Make the model-facing inputs explicit. Derived P4 features are rebuilt
    # from these columns by _prepare_observations under the same date/style rows.
    required = {
        "date", "style_id", "available_at",
        *INPUT_FEATURES,
        "signal_time", "feature_pit_eligible", "feature_status",
        "feature_block_reason", "feature_protocol_version",
        "feature_price_basis", "action_evidence_version",
        "historical_pit_attested", "decision_eligible",
        "real_orders_enabled",
    }
    return observations.loc[:, [
        column for column in observations.columns if column in required
    ]].sort_values(["date", "style_id"], kind="stable").reset_index(drop=True)
