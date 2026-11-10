"""P1 normalized records; observed historical vintages never become retroactive knowledge."""
from datetime import date, datetime
from math import isfinite
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_research.clock import utc


class PriceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    security_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int = Field(ge=0)
    vwap: float | None = None
    adjustment_basis: Literal["raw", "yahoo_split_adjusted"] = "raw"
    source: Literal["ALPACA", "YAHOO"]
    feed: Literal["iex", "sip", "yahoo"]
    event_time: datetime
    available_at: datetime
    ingested_at: datetime
    availability_basis: Literal["first_observed"]
    raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    quality_flag: str
    adj_close: float | None = None

    @model_validator(mode="after")
    def valid(self):
        if any(word in (self.security_id+' '+self.quality_flag).lower() for word in ('synthetic','fixture','mock','demo')):
            raise ValueError('REAL_ONLY rejects non-real identity/provenance')
        if not all(isfinite(v) and v > 0 for v in (self.open, self.high, self.low, self.close)):
            raise ValueError("Invalid price")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Invalid OHLC envelope")
        if self.adj_close is not None and (not isfinite(self.adj_close) or self.adj_close <= 0):
            raise ValueError("Invalid adjusted close")
        if self.vwap is not None and (not isfinite(self.vwap) or self.vwap <= 0):
            raise ValueError("Invalid VWAP")
        if not utc(self.event_time) <= utc(self.available_at) <= utc(self.ingested_at):
            raise ValueError("Invalid price time ordering")
        if self.source == "ALPACA" and (self.feed not in ("iex", "sip") or self.availability_basis != "first_observed" or self.adjustment_basis != "raw"):
            raise ValueError("Real data cannot claim synthetic historical availability")
        if self.source == "YAHOO" and (self.feed != "yahoo" or self.availability_basis != "first_observed" or self.adjustment_basis != "yahoo_split_adjusted"):
            raise ValueError("Yahoo data cannot claim raw execution prices or synthetic availability")
        return self


class CorporateAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    security_id: str
    event_id: str
    ex_date: date
    action_type: Literal["split", "dividend", "capital_gain"]
    factor_or_cash: float
    announced_at: datetime | None = None
    available_at: datetime
    source: Literal["YAHOO"] = "YAHOO"
    version: str
    quality_flag: str = "EXPLORATORY|AMOUNT_BASIS_UNVERIFIED|FIRST_OBSERVED_NOT_PIT"
    currency: str | None = None

    @model_validator(mode="after")
    def valid(self):
        utc(self.available_at)
        if self.announced_at is not None:
            utc(self.announced_at)
        if not isfinite(self.factor_or_cash) or self.factor_or_cash < 0 or (self.action_type == "split" and self.factor_or_cash == 0):
            raise ValueError("Invalid corporate action")
        return self


class FactorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    date: date
    factor_name: str
    value_decimal: float | None
    source: Literal["KEN_FRENCH"] = "KEN_FRENCH"
    available_at: datetime
    version: str
    use_policy: Literal["ATTRIBUTION_ONLY"] = "ATTRIBUTION_ONLY"

    @model_validator(mode="after")
    def valid(self):
        utc(self.available_at)
        if self.value_decimal is not None and not isfinite(self.value_decimal):
            raise ValueError("Invalid factor return")
        return self
