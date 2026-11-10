"""Calendar-aligned inputs; no filling gaps or retroactive knowledge timestamps."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


def rolling_available(panel, window):
    """Exact integer timestamp rolling max, avoiding float nanosecond rounding."""
    from collections import deque
    result = pd.DataFrame(index=panel.index, columns=panel.columns, dtype="datetime64[ns, UTC]")
    for column in panel:
        values = pd.to_datetime(panel[column], utc=True).dt.as_unit("ns").astype("int64").to_numpy()
        queue, output = deque(), []
        for i, value in enumerate(values):
            while queue and queue[0] <= i - window:
                queue.popleft()
            while queue and values[queue[-1]] <= value:
                queue.pop()
            queue.append(i)
            output.append(values[queue[0]])
        result[column] = pd.to_datetime(output, utc=True)
    return result


@dataclass
class FactorContext:
    panels: dict[str, pd.DataFrame]
    availability: pd.DataFrame
    symbols: dict[str, str]
    benchmark_id: str
    # Optional date-specific, timestamped classification. No current sector backfill.
    sector_proxy: pd.DataFrame | None = None
    sector_available_at: pd.DataFrame | None = None
    _available_cache: dict = field(default_factory=dict, repr=False)

    @property
    def close(self):
        return self.panels["close"]

    @property
    def returns(self):
        return self.close.pct_change(fill_method=None)

    def available(self, window):
        if window not in self._available_cache:
            self._available_cache[window] = rolling_available(self.availability, window)
        return self._available_cache[window]


def make_context(prices, clock, benchmark="SPY", start=None, end=None):
    from quant_research.policy import require_real_frame
    require_real_frame(prices)
    if prices.empty:
        raise ValueError("No input prices available")
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    if prices.duplicated(["date", "security_id"]).any():
        raise ValueError("Duplicate normalized price key")
    if len(prices["adjustment_basis"].unique()) != 1 or len(prices["source"].unique()) != 1 or len(prices["feed"].unique()) != 1:
        raise ValueError("Do not mix source/feed/adjustment bases")
    sessions = clock.calendar.sessions_in_range(start or prices.date.min(), end or prices.date.max())
    if not prices.date.isin(sessions).all():
        raise ValueError("Input price outside requested calendar sessions")
    symbols = prices.drop_duplicates("security_id").set_index("security_id")["symbol"].to_dict()
    ids = [key for key, value in symbols.items() if value == benchmark]
    if len(ids) != 1:
        raise ValueError("Exactly one benchmark identity required")
    panels = {name: prices.pivot(index="date", columns="security_id", values=name).reindex(sessions).sort_index(axis=1)
              for name in ["open", "high", "low", "close", "volume"]}
    prices["available_at"] = pd.to_datetime(prices.available_at, utc=True)
    availability = prices.pivot(index="date", columns="security_id", values="available_at").reindex(sessions).reindex(columns=panels["close"].columns)
    return FactorContext(panels, availability, symbols, ids[0])
