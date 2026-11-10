import json
from pathlib import Path

import pytest

from quant_research.clock import TradingClock
from quant_research.contracts import DailyBar, validate_bars
from quant_research.data.providers.fixture import FixtureProvider


def test_fixture_reproducible():
    clock = TradingClock()
    a = FixtureProvider(clock).bars("2024-11-27", "2024-11-29")
    assert a == FixtureProvider(clock).bars("2024-11-27", "2024-11-29")
    snapshot = json.loads((Path(__file__).parents[1] / "fixtures" / "bars_synthetic.json").read_text(encoding="utf-8"))
    assert [bar.model_dump(mode="json") for bar in a] == snapshot
    assert len(a) == 40
    assert a != FixtureProvider(clock, 43).bars("2024-11-27", "2024-11-29")
    with pytest.raises(ValueError, match="Duplicate"):
        validate_bars(a + a, clock)
    with pytest.raises(ValueError, match="increase"):
        validate_bars(list(reversed(a)), clock)


@pytest.mark.parametrize("updates", [{"volume": -1}, {"open": -1}, {"high": 1}, {"close": float("nan")}, {"adjustment_basis": "adjusted"}])
def test_bad_bar(updates):
    bar = FixtureProvider(TradingClock()).bars("2024-11-27", "2024-11-27")[0]
    with pytest.raises(ValueError):
        DailyBar.model_validate({**bar.model_dump(), **updates})


def test_event_date_mismatch():
    clock = TradingClock()
    bar = FixtureProvider(clock).bars("2024-11-27", "2024-11-27")[0]
    modified = DailyBar.model_validate({**bar.model_dump(), "date": "2024-11-26"})
    with pytest.raises(ValueError, match="exchange close"):
        validate_bars([modified], clock)


def test_normalized_provider_interface():
    from quant_research.data.providers.fixture import NormalizedFixtureProvider
    from quant_research.data.schema import PriceRecord
    records = NormalizedFixtureProvider(TradingClock()).bars(["SPY"], "2024-11-27", "2024-11-29")
    assert len(records) == 2
    assert all(isinstance(r, PriceRecord) and r.symbol == "SPY" for r in records)
