"""P2 state-machine tests use deterministic fixtures, never demo UI numbers."""
import pandas as pd
import pytest

from quant_research.research.l2_rotation import (
    ROTATION_PROTOCOL_VERSION, STATES, UNKNOWN, rotation_states_v1,
)


def _observations(strength, acceleration, *, style="size"):
    sessions = pd.bdate_range("2025-01-02", periods=len(strength))
    return pd.DataFrame({
        "date": sessions,
        "style_id": style,
        "relative_return_20d": strength,
        "relative_acceleration_5d": acceleration,
        "relative_return_20d_available_at": [
            pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=22)
            for day in sessions
        ],
    })


def test_all_four_quadrants_are_causal_and_transitions_are_genuine():
    rows = _observations([0.03, 0.04, -0.03, -0.02],
                         [0.01, -0.01, 0.02, -0.01])
    result = rotation_states_v1(rows)
    assert list(result.rotation_state) == list(STATES)
    assert list(result.transitioned_on_session) == [False, True, True, True]
    assert result.loc[0, "previous_state"] is None
    assert result.loc[1, "previous_state"] == STATES[0]
    assert result.loc[1, "last_transition_session"] == result.loc[1, "date"]
    assert set(result.protocol_version) == {ROTATION_PROTOCOL_VERSION}
    assert not result.forecast_eligible.any()
    assert not result.decision_eligible.any()


def test_state_streak_uses_session_counts_and_carries_last_transition():
    rows = _observations([0.03] * 5, [0.01, 0.01, -0.01, -0.01, -0.01])
    result = rotation_states_v1(rows)
    assert list(result.consecutive_sessions) == [1, 2, 1, 2, 3]
    assert result.loc[4, "rotation_state_start_session"] == result.loc[2, "date"]
    assert result.loc[4, "last_transition_session"] == result.loc[2, "date"]
    assert result.loc[4, "previous_state"] == STATES[0]
    assert result.loc[4, "transitioned_on_session"] == False


def test_missing_and_zero_boundary_are_unknown_and_break_transition_chain():
    rows = _observations([0.04, 0.04, None, -0.04, 0.0, -0.03],
                         [0.01, -0.01, 0.01, 0.01, 0.01, -0.01])
    result = rotation_states_v1(rows)
    assert list(result.rotation_state) == [
        STATES[0], STATES[1], UNKNOWN, STATES[2], UNKNOWN, STATES[3]
    ]
    assert list(result.transitioned_on_session) == [
        False, True, False, False, False, False
    ]
    assert result.loc[2, "block_reason"] == "MISSING_OR_NONFINITE_20D_STRENGTH"
    assert result.loc[4, "block_reason"] == "NEUTRAL_ZERO_BOUNDARY"
    assert result.loc[3, "previous_state"] is None
    assert result.loc[3, "consecutive_sessions"] == 1


def test_source_availability_missing_or_after_cutoff_blocks_state():
    rows = _observations([0.03, 0.03, 0.03], [0.01] * 3)
    rows.loc[1, "relative_return_20d_available_at"] = pd.NaT
    rows.loc[2, "relative_return_20d_available_at"] = pd.Timestamp("2025-06-01T00:00:00Z")
    cutoff = "2025-01-10T23:00:00+00:00"
    result = rotation_states_v1(rows, cutoff_utc=cutoff)
    assert list(result.rotation_state) == [STATES[0], UNKNOWN, UNKNOWN]
    assert result.loc[1, "block_reason"] == "MISSING_20D_SOURCE_AVAILABILITY"
    assert result.loc[2, "block_reason"] == "SOURCE_AVAILABLE_AFTER_CUTOFF"


def test_future_input_does_not_change_historical_states_or_transitions():
    rows = _observations([0.03, 0.02, -0.04, -0.03], [0.01, -0.01, 0.01, -0.01])
    baseline = rotation_states_v1(rows)
    altered = rows.copy()
    altered.loc[len(rows) - 1, "relative_return_20d"] = 12.0
    changed = rotation_states_v1(altered)
    pd.testing.assert_frame_equal(
        baseline.iloc[:-1].reset_index(drop=True),
        changed.iloc[:-1].reset_index(drop=True),
    )


def test_duplicate_sessions_and_ambiguous_cutoff_are_rejected():
    rows = _observations([0.03, 0.02], [0.01, -0.01])
    with pytest.raises(ValueError, match="Duplicate"):
        rotation_states_v1(pd.concat([rows, rows.iloc[:1]], ignore_index=True))
    with pytest.raises(ValueError, match="timezone"):
        rotation_states_v1(rows, cutoff_utc="2025-01-03T23:00:00")
