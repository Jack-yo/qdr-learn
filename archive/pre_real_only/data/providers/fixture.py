"""Deterministic artificial prices for engineering tests only."""
from datetime import timedelta
from random import Random

from quant_research.contracts import DailyBar, validate_bars

SYMBOLS = "SPY RSP IWM IWD IWF MTUM QUAL USMV HYG LQD XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE".split()


class FixtureProvider:
    def __init__(self, clock, seed=42):
        self.clock, self.seed = clock, seed

    def bars(self, start, end):
        rng = Random(self.seed)
        result = []
        for index, symbol in enumerate(SYMBOLS):
            price = 50.0 + 5 * index
            for day in self.clock.calendar.sessions_in_range(start, end):
                opening = round(price * (1 + rng.uniform(-0.01, 0.01)), 4)
                price = round(opening * (1 + rng.uniform(-0.02, 0.02)), 4)
                event = self.clock.close(day)
                result.append(DailyBar(
                    security_id=f"SYNTH-{symbol}", date=day.date(), open=opening,
                    high=round(max(opening, price) * 1.01, 4),
                    low=round(min(opening, price) * 0.99, 4), close=price,
                    volume=rng.randint(100000, 1000000), event_time=event,
                    available_at=event + timedelta(minutes=5),
                    ingested_at=event + timedelta(minutes=10),
                ))
        validate_bars(result, self.clock)
        return result


class NormalizedFixtureProvider:
    def __init__(self, clock, seed=42):
        self.provider = FixtureProvider(clock, seed)

    def bars(self, symbols, start, end):
        from quant_research.data.normalize import normalize_fixture
        if not set(symbols).issubset(SYMBOLS):
            raise ValueError("Unknown fixture symbol")
        records, _ = normalize_fixture(self.provider.bars(start, end))
        return [r for r in records if r.symbol in symbols]
