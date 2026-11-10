from datetime import datetime, timezone

import pytest

from quant_research.clock import TradingClock, utc


@pytest.fixture(scope="module")
def clock():
    return TradingClock()


def test_thanksgiving_and_early_close(clock):
    with pytest.raises(ValueError, match="Not an XNYS"):
        clock.session("2024-11-28")
    window = clock.window("2024-11-27", 1)
    assert window.entry_time.isoformat() == "2024-11-29T14:30:00+00:00"
    assert window.exit_time.isoformat() == "2024-11-29T18:00:00+00:00"


@pytest.mark.parametrize("horizon,day", [(1, "2024-11-29"), (3, "2024-12-03"), (5, "2024-12-05")])
def test_holding_period(clock, horizon, day):
    assert str(clock.window("2024-11-27", horizon).exit_time.date()) == day


def test_dst(clock):
    assert clock.window("2024-03-07", 1).entry_time.hour == 14
    assert clock.window("2024-03-08", 1).entry_time.hour == 13
    assert clock.window("2024-11-01", 1).entry_time.hour == 14


@pytest.mark.parametrize("day", ["2024-11-30", "2024-12-25", "2025-01-09"])
def test_closures(clock, day):
    with pytest.raises(ValueError):
        clock.session(day)


def test_before_close(clock):
    with pytest.raises(ValueError, match="not closed"):
        clock.signal("2024-11-27", datetime(2024, 11, 27, 20, tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="not closed"):
        clock.signal("2024-11-27", datetime(2024, 11, 27, 21, 10, tzinfo=timezone.utc))


def test_aware_and_horizon(clock):
    with pytest.raises(ValueError):
        utc(datetime(2024, 1, 1))
    for horizon in (0, 2, 10, True):
        with pytest.raises(ValueError):
            clock.window("2024-11-27", horizon)
    with pytest.raises(ValueError):
        clock.session("2024-11-27T12:00:00")


def test_signal_cannot_follow_entry():
    with pytest.raises(ValueError, match="next session open"):
        TradingClock(delay_minutes=3000).window("2024-11-27", 1)
