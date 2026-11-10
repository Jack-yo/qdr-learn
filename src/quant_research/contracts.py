"""Validated P0 contracts; event time is distinct from knowledge time."""
from datetime import date, datetime
from math import isfinite
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, model_validator

from .clock import utc


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    security_id: str
    name: str
    value: float
    event_time: datetime
    available_at: datetime
    source: str
    version: str

    @model_validator(mode="after")
    def valid(self):
        if not isfinite(self.value):
            raise ValueError("Non-finite observation")
        if utc(self.available_at) < utc(self.event_time):
            raise ValueError("Availability precedes event")
        return self


def require_asof(rows: Sequence[Observation], signal_time: datetime, cutoff: datetime):
    signal_time, cutoff = utc(signal_time), utc(cutoff)
    if cutoff > signal_time:
        raise ValueError("Data cutoff exceeds signal time")
    for row in rows:
        if utc(row.event_time) > cutoff or utc(row.available_at) > cutoff:
            raise ValueError(f"Future information blocked: {row.security_id}/{row.name}")
    return rows


class DailyBar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    security_id: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    adjustment_basis: Literal["raw"] = "raw"
    event_time: datetime
    available_at: datetime
    ingested_at: datetime
    source: Literal["ALPACA"]

    @model_validator(mode="after")
    def valid(self):
        prices = [self.open, self.high, self.low, self.close]
        if not all(isfinite(x) and x > 0 for x in prices):
            raise ValueError("Invalid price")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Invalid OHLC envelope")
        if self.volume < 0:
            raise ValueError("Negative volume")
        if not utc(self.event_time) <= utc(self.available_at) <= utc(self.ingested_at):
            raise ValueError("Invalid event/availability/ingestion ordering")
        return self


def validate_bars(bars, clock):
    seen = set()
    previous = {}
    for bar in bars:
        key = (bar.security_id, bar.date)
        if key in seen:
            raise ValueError("Duplicate daily-bar primary key")
        seen.add(key)
        if bar.security_id in previous and bar.date <= previous[bar.security_id]:
            raise ValueError("Bars must increase by security date")
        previous[bar.security_id] = bar.date
        if utc(bar.event_time) != clock.close(bar.date):
            raise ValueError("Bar date/event does not match exchange close")


def require_pit_universe(kind: str, available_at: datetime, signal_time: datetime):
    if kind != "historical_pit":
        raise ValueError("Contemporary constituents cannot represent historical PIT universe")
    if utc(available_at) > utc(signal_time):
        raise ValueError("Future universe information")


def require_entry(window, fill_time: datetime, adjustment_basis: str):
    if utc(fill_time) != window.entry_time or adjustment_basis != "raw":
        raise ValueError("Entry contract requires T+1 raw opening price")
