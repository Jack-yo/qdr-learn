"""P4 label builder tests: exact timing, basket math and fail-closed action evidence."""
import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.research.l2_labels import (
    REQUIRED_PRICE_BASIS, build_verified_style_labels_v1,
)
from quant_research.research.l2_style_rotation import REQUIRED_SYMBOLS


def _evidence(n=18):
    clock = TradingClock()
    sessions = clock.calendar.sessions_in_range("2025-01-02", "2025-03-31")[:n]
    opens = pd.DataFrame(index=sessions, columns=REQUIRED_SYMBOLS, dtype=float)
    closes = pd.DataFrame(index=sessions, columns=REQUIRED_SYMBOLS, dtype=float)
    availability = pd.DataFrame(index=sessions, columns=REQUIRED_SYMBOLS, dtype=object)
    actions = pd.DataFrame(True, index=sessions, columns=REQUIRED_SYMBOLS)
    for s_i, symbol in enumerate(REQUIRED_SYMBOLS):
        for i, day in enumerate(sessions):
            value = 90 + s_i * 2 + i * (0.2 + s_i * 0.002)
            opens.loc[day, symbol] = value
            closes.loc[day, symbol] = value * (1 + 0.001 * ((i + s_i) % 4 - 1))
            availability.loc[day, symbol] = (
                pd.Timestamp(clock.close(day)) + pd.Timedelta(minutes=20)
            )
    return clock, sessions, opens, closes, availability, actions


def test_label_builder_creates_all_seven_styles_and_horizons_with_exact_clock():
    clock, sessions, opens, closes, availability, actions = _evidence()
    labels = build_verified_style_labels_v1(
        opens, closes, availability, actions, sessions, clock,
        price_basis=REQUIRED_PRICE_BASIS,
        action_evidence_version="fixture-actions-v1",
    )
    first_day = sessions[0].date().isoformat()
    day = labels.loc[labels.date.eq(first_day)]
    assert len(day) == 21
    assert day.forward_relative_return.notna().all()
    assert set(day.label_kind) == {"VERIFIED_RAW_RELATIVE_RETURN"}
    assert not day.decision_eligible.any()
    assert not day.real_orders_enabled.any()
    for row in day.itertuples(index=False):
        window = clock.window(pd.Timestamp(row.date), row.horizon)
        assert pd.Timestamp(row.signal_time) == pd.Timestamp(window.signal_time)
        assert pd.Timestamp(row.entry_time) == pd.Timestamp(window.entry_time)
        assert pd.Timestamp(row.exit_time) == pd.Timestamp(window.exit_time)
        assert pd.Timestamp(row.label_available_at) >= pd.Timestamp(row.exit_time)


def test_pair_math_uses_next_open_to_horizon_close_relative_return():
    clock, sessions, opens, closes, availability, actions = _evidence()
    labels = build_verified_style_labels_v1(
        opens, closes, availability, actions, sessions, clock,
        price_basis=REQUIRED_PRICE_BASIS,
        action_evidence_version="fixture-actions-v1",
    )
    signal = sessions[0]
    row = labels.loc[
        labels.date.eq(signal.date().isoformat())
        & labels.style_id.eq("size")
        & labels.horizon.eq(3)
    ].iloc[0]
    entry, exit_ = sessions[1], sessions[3]
    iwm = closes.loc[exit_, "IWM"] / opens.loc[entry, "IWM"] - 1
    spy = closes.loc[exit_, "SPY"] / opens.loc[entry, "SPY"] - 1
    expected = (1 + iwm) / (1 + spy) - 1
    assert row.forward_relative_return == pytest.approx(expected)


def test_cyclical_defensive_label_is_fixed_equal_weight_at_entry():
    clock, sessions, opens, closes, availability, actions = _evidence()
    labels = build_verified_style_labels_v1(
        opens, closes, availability, actions, sessions, clock,
        price_basis=REQUIRED_PRICE_BASIS,
        action_evidence_version="fixture-actions-v1",
    )
    row = labels.loc[
        labels.date.eq(sessions[0].date().isoformat())
        & labels.style_id.eq("cyc_def")
        & labels.horizon.eq(5)
    ].iloc[0]
    entry, exit_ = sessions[1], sessions[5]
    cyc = ["XLI", "XLY", "XLB", "XLF"]
    defensive = ["XLP", "XLU", "XLV"]
    cyc_ret = (closes.loc[exit_, cyc].to_numpy() / opens.loc[entry, cyc].to_numpy() - 1).mean()
    def_ret = (
        closes.loc[exit_, defensive].to_numpy()
        / opens.loc[entry, defensive].to_numpy() - 1
    ).mean()
    assert row.forward_relative_return == pytest.approx((1 + cyc_ret) / (1 + def_ret) - 1)


def test_missing_action_evidence_blocks_only_affected_holding_window():
    clock, sessions, opens, closes, availability, actions = _evidence()
    actions.loc[sessions[2], "XLY"] = False
    labels = build_verified_style_labels_v1(
        opens, closes, availability, actions, sessions, clock,
        price_basis=REQUIRED_PRICE_BASIS,
        action_evidence_version="fixture-actions-v1",
    )
    first = labels.loc[labels.date.eq(sessions[0].date().isoformat())]
    cyc_h3 = first.loc[first.style_id.eq("cyc_def") & first.horizon.eq(3)].iloc[0]
    size_h3 = first.loc[first.style_id.eq("size") & first.horizon.eq(3)].iloc[0]
    assert cyc_h3.forward_relative_return is None or pd.isna(cyc_h3.forward_relative_return)
    assert cyc_h3.label_kind == "BLOCKED"
    assert cyc_h3.block_reason == "INCOMPLETE_CORPORATE_ACTION_EVIDENCE"
    assert pd.notna(size_h3.forward_relative_return)


def test_current_vintage_or_unverified_price_basis_is_rejected():
    clock, sessions, opens, closes, availability, actions = _evidence()
    with pytest.raises(ValueError, match="action-consistent"):
        build_verified_style_labels_v1(
            opens, closes, availability, actions, sessions, clock,
            price_basis="yahoo_split_adjusted",
            action_evidence_version="fixture-actions-v1",
        )


def test_source_available_before_exit_is_not_promoted_to_verified_label():
    clock, sessions, opens, closes, availability, actions = _evidence()
    availability.loc[:, :] = [
        [pd.Timestamp(clock.close(day)) - pd.Timedelta(minutes=1)] * len(REQUIRED_SYMBOLS)
        for day in sessions
    ]
    labels = build_verified_style_labels_v1(
        opens, closes, availability, actions, sessions, clock,
        price_basis=REQUIRED_PRICE_BASIS,
        action_evidence_version="fixture-actions-v1",
    )
    first = labels.iloc[0]
    assert pd.isna(first.forward_relative_return)
    assert first.label_kind == "BLOCKED"
    assert first.block_reason == "LABEL_SOURCE_AVAILABLE_BEFORE_EXIT"
