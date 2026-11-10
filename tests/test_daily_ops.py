from datetime import timedelta

import pytest

from quant_research.clock import TradingClock
from quant_research.data.close_snapshot import latest_ready_session
from quant_research.policy import PolicyError
from quant_research.workflow.daily_ops import _window


def test_g5_window_uses_xnys_close_plus_twenty_minutes():
    clock = TradingClock()
    day = clock.session("2026-11-06")
    next_day = clock.calendar.next_session(day)
    ready = clock.close(day) + timedelta(minutes=20)
    next_open = clock.calendar.session_open(next_day).to_pydatetime()

    selected, selected_ready, selected_open = _window(ready, clock)
    assert selected == day
    assert selected_ready == ready
    assert selected_open == next_open
    assert latest_ready_session(clock, ready).date().isoformat() == "2026-11-06"


def test_g5_window_rejects_after_next_open():
    clock = TradingClock()
    day = clock.session("2026-11-06")
    next_open = clock.calendar.session_open(clock.calendar.next_session(day)).to_pydatetime()
    with pytest.raises(PolicyError) as error:
        _window(next_open, clock)
    assert error.value.code == "DAILY_WINDOW_CLOSED"


def test_g5_uses_early_close_and_rejects_before_ready():
    clock = TradingClock()
    session = clock.session("2024-11-29")
    close = clock.close(session)
    assert close.hour == 18
    with pytest.raises(PolicyError, match="window is not open"):
        _window(close + timedelta(minutes=19), clock)
    assert _window(close + timedelta(minutes=20), clock)[0] == session
