"""Causal four-quadrant L2 rotation states over verified ETF style observations.

Descriptive state machine only: no fitted thresholds, trading signals, or forecasts.
A missing observation breaks the current streak instead of bridging the gap.
"""
from __future__ import annotations

import math

import pandas as pd


ROTATION_PROTOCOL_VERSION = "qdr-l2-rotation-v1"
STATES = (
    "STRONG_ACCELERATING",
    "STRONG_DECELERATING",
    "WEAK_IMPROVING",
    "WEAK_DETERIORATING",
)
UNKNOWN = "UNKNOWN"
_REQUIRED = (
    "date", "style_id", "relative_return_20d",
    "relative_acceleration_5d", "relative_return_20d_available_at",
)


def rotation_states_v1(observations: pd.DataFrame, *,
                       cutoff_utc: str | None = None) -> pd.DataFrame:
    """Create a date-indexed, replayable state and genuine transition ledger.

    Strength is a 20-session ETF excess/relative return; acceleration is the
    latest five-session relative return minus the previous five. Positive
    and negative are strict; an exact zero boundary is neutral/UNKNOWN.
    All inputs must be contemporaneously available under the specified cutoff.
    A transition exists only after two consecutive known, differing states.
    """
    if not isinstance(observations, pd.DataFrame):
        raise TypeError("observations must be a DataFrame")
    missing = set(_REQUIRED) - set(observations.columns)
    if missing:
        raise ValueError("Missing L2 rotation columns: " + ", ".join(sorted(missing)))
    frame = observations.loc[:, _REQUIRED].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    if frame["date"].isna().any() or frame["style_id"].isna().any():
        raise ValueError("Rotation dates and style IDs must be present")
    if frame.duplicated(["date", "style_id"]).any():
        raise ValueError("Duplicate L2 style/session rows")
    frame["relative_return_20d_available_at"] = pd.to_datetime(
        frame["relative_return_20d_available_at"], utc=True, errors="coerce"
    )
    cutoff = None
    if cutoff_utc is not None:
        cutoff = pd.Timestamp(cutoff_utc)
        if cutoff.tzinfo is None:
            raise ValueError("Rotation cutoff must include a timezone")
        cutoff = cutoff.tz_convert("UTC")

    output = []
    for style_id, group in frame.sort_values(
        ["style_id", "date"], kind="stable"
    ).groupby("style_id", sort=False):
        last_state = UNKNOWN
        state_start = None
        last_transition = None
        previous_state = None
        consecutive = 0
        for row in group.itertuples(index=False):
            strength = row.relative_return_20d
            acceleration = row.relative_acceleration_5d
            available = row.relative_return_20d_available_at
            reason = None
            if pd.isna(strength) or not math.isfinite(float(strength)):
                reason = "MISSING_OR_NONFINITE_20D_STRENGTH"
            elif pd.isna(acceleration) or not math.isfinite(float(acceleration)):
                reason = "MISSING_OR_NONFINITE_5D_ACCELERATION"
            elif pd.isna(available):
                reason = "MISSING_20D_SOURCE_AVAILABILITY"
            elif cutoff is not None and available > cutoff:
                reason = "SOURCE_AVAILABLE_AFTER_CUTOFF"
            elif float(strength) == 0.0 or float(acceleration) == 0.0:
                reason = "NEUTRAL_ZERO_BOUNDARY"

            if reason:
                state = UNKNOWN
            elif strength > 0 and acceleration > 0:
                state = STATES[0]
            elif strength > 0 and acceleration < 0:
                state = STATES[1]
            elif strength < 0 and acceleration > 0:
                state = STATES[2]
            else:
                state = STATES[3]

            session = row.date.date().isoformat()
            transitioned = state != UNKNOWN and last_state != UNKNOWN and state != last_state
            if state == UNKNOWN:
                state_start = None
                last_transition = None
                previous_state = None
                consecutive = 0
            elif state != last_state:
                state_start = session
                consecutive = 1
                if transitioned:
                    previous_state = last_state
                    last_transition = session
                else:
                    previous_state = None
                    last_transition = None
            else:
                consecutive += 1

            output.append({
                "date": session,
                "style_id": style_id,
                "rotation_state": state,
                "rotation_state_start_session": state_start,
                "previous_state": previous_state,
                "last_transition_session": last_transition,
                "transitioned_on_session": bool(transitioned),
                "consecutive_sessions": consecutive,
                "strength_relative_return_20d": (
                    float(strength) if pd.notna(strength) and math.isfinite(float(strength))
                    else None
                ),
                "acceleration_relative_return_5d": (
                    float(acceleration) if pd.notna(acceleration) and math.isfinite(float(acceleration))
                    else None
                ),
                "source_available_at_utc": available.isoformat() if pd.notna(available) else None,
                "block_reason": reason,
                "status": "OBSERVATION_ONLY" if state != UNKNOWN else "BLOCKED",
                "research_status": "OBSERVATION_ONLY",
                "forecast_eligible": False,
                "decision_eligible": False,
                "protocol_version": ROTATION_PROTOCOL_VERSION,
            })
            last_state = state

    return pd.DataFrame.from_records(
        output,
        columns=(
            "date", "style_id", "rotation_state", "rotation_state_start_session",
            "previous_state", "last_transition_session", "transitioned_on_session",
            "consecutive_sessions", "strength_relative_return_20d",
            "acceleration_relative_return_5d", "source_available_at_utc",
            "block_reason", "status", "research_status", "forecast_eligible",
            "decision_eligible", "protocol_version"
        )
    ).sort_values(["date", "style_id"], kind="stable").reset_index(drop=True)
