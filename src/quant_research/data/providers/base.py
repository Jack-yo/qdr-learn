from typing import Protocol

from quant_research.contracts import DailyBar
from quant_research.data.schema import PriceRecord


class DailyBarProvider(Protocol):
    """Adapters preserve event, availability and ingestion times; never fabricate gaps."""

    def bars(self, start: str, end: str) -> list[DailyBar]: ...


class PriceProvider(Protocol):
    """Normalized P1 interface, shared by live Alpaca and offline fixture adapters."""

    def bars(self, symbols: list[str], start: str, end: str) -> list[PriceRecord]: ...
