"""V4 panel uses a causal layered L3 signal after upstream inputs exist."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.models.v4_panel import prepare_v4_alpha_panel


DAY = pd.Timestamp("2026-01-30")


class Clock:
    def signal(self, day):
        return pd.Timestamp("2026-01-30T21:15:00Z")

    def window(self, day, horizon):
        return SimpleNamespace(
            entry_time=pd.Timestamp("2026-02-02T14:30:00Z"),
            exit_time=pd.Timestamp("2026-02-02T21:00:00Z")
            + pd.Timedelta(days=horizon - 1),
        )


def _inputs(state_time="2026-01-30T21:16:00Z"):
    features = pd.DataFrame([{
        "date": DAY,
        "security_id": "AAA",
        "feature_name": "alpha",
        "value": 0.2,
        "available_at": "2026-01-30T21:10:00Z",
        "decision_eligible": True,
    }])
    labels = pd.DataFrame([{
        "date": DAY,
        "security_id": "AAA",
        "horizon": horizon,
        "entry_time": "2026-02-02T14:30:00Z",
        "exit_time": (
            pd.Timestamp("2026-02-02T21:00:00Z")
            + pd.Timedelta(days=horizon - 1)
        ).isoformat(),
        "available_at": None,
        "gross_return": None,
        "excess_return": None,
        "label_kind": "FUTURE_UNOBSERVED",
    } for horizon in (1, 3, 5)])
    states = pd.DataFrame([{
        "date": DAY,
        "state_available_at": state_time,
        "market_regime": 0.1,
        "style_l2_quality_h3": 0.003,
    }])
    return features, labels, states


def test_l3_signal_moves_to_late_l2_state_time_without_backdating():
    features, labels, states = _inputs()
    panel, contract = prepare_v4_alpha_panel(
        features, labels, states, Clock(), expected_factor_names=["alpha"]
    )
    assert set(panel.signal_time) == {pd.Timestamp("2026-01-30T21:16:00Z")}
    assert set(panel.feature_available_at) == {pd.Timestamp("2026-01-30T21:16:00Z")}
    assert set(panel.base_signal_time) == {pd.Timestamp("2026-01-30T21:15:00Z")}
    assert contract["decision_eligible"] is False
    assert contract["real_orders_enabled"] is False


def test_layered_signal_cannot_reach_next_session_entry():
    features, labels, states = _inputs("2026-02-02T14:30:00Z")
    with pytest.raises(ValueError, match="not available before next-session entry"):
        prepare_v4_alpha_panel(
            features, labels, states, Clock(), expected_factor_names=["alpha"]
        )
