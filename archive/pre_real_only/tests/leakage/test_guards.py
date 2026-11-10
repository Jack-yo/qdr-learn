from datetime import datetime, timedelta, timezone

import pytest

from quant_research.clock import TradingClock
from quant_research.contracts import Observation, require_asof, require_entry, require_pit_universe

SIGNAL = datetime(2024, 11, 27, 21, 15, tzinfo=timezone.utc)


def observation(event, available, name="close"):
    return Observation(security_id="SYNTH-SPY", name=name, value=100,
                       event_time=event, available_at=available, source="fixture", version="v1")


def test_future_close_blocked():
    future = SIGNAL + timedelta(days=2)
    with pytest.raises(ValueError, match="Future information"):
        require_asof([observation(future, future)], SIGNAL, SIGNAL)


def test_backdated_future_financial_disclosure_blocked():
    with pytest.raises(ValueError, match="Future information"):
        require_asof([observation(SIGNAL - timedelta(days=90), SIGNAL + timedelta(days=1), "ROA")], SIGNAL, SIGNAL)


def test_cutoff_and_boundary():
    row = observation(SIGNAL, SIGNAL)
    assert require_asof([row], SIGNAL, SIGNAL) == [row]
    with pytest.raises(ValueError):
        require_asof([row], SIGNAL, SIGNAL - timedelta(seconds=1))
    with pytest.raises(ValueError):
        require_asof([], SIGNAL, SIGNAL + timedelta(seconds=1))


def test_same_close_fill_blocked():
    clock = TradingClock()
    window = clock.window("2024-11-27", 1)
    with pytest.raises(ValueError, match=r"T\+1"):
        require_entry(window, clock.close("2024-11-27"), "raw")
    with pytest.raises(ValueError):
        require_entry(window, window.entry_time, "adjusted")
    require_entry(window, window.entry_time, "raw")


def test_current_universe_cannot_be_historical():
    with pytest.raises(ValueError, match="Contemporary"):
        require_pit_universe("current_constituents", SIGNAL - timedelta(days=1), SIGNAL)
    with pytest.raises(ValueError, match="Future universe"):
        require_pit_universe("historical_pit", SIGNAL + timedelta(days=1), SIGNAL)
    require_pit_universe("historical_pit", SIGNAL, SIGNAL)


@pytest.mark.parametrize("event,available", [(SIGNAL.replace(tzinfo=None), SIGNAL), (SIGNAL, SIGNAL.replace(tzinfo=None))])
def test_naive_timestamp_rejected(event, available):
    with pytest.raises(ValueError, match="Timezone-aware"):
        observation(event, available)
