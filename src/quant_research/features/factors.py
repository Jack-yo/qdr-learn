"""Extensible causal factor registry; missing PIT inputs are explicit outputs."""
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from .context import FactorContext


class Factor(Protocol):
    name: str
    version: str
    lookback: int  # sessions before current date
    dependency: str  # self, market, sector
    missing_reason: str | None

    def compute(self, context: FactorContext) -> pd.DataFrame: ...


@dataclass(frozen=True)
class FunctionalFactor:
    name: str
    lookback: int
    function: Callable[[FactorContext], pd.DataFrame]
    definition: str
    dependency: str = "self"
    missing_reason: str | None = None
    version: str = "v1"

    def compute(self, context):
        return self.function(context).replace([np.inf, -np.inf], np.nan)


def empty(context):
    return context.close * np.nan


def market_beta(context):
    returns = context.returns
    benchmark = returns[context.benchmark_id]
    variance = benchmark.rolling(60, min_periods=60).var(ddof=1).replace(0, np.nan)
    return returns.apply(lambda x: x.rolling(60, min_periods=60).cov(benchmark) / variance)


def sector_feature(context, residual):
    if context.sector_proxy is None or context.sector_available_at is None:
        return empty(context)
    output = empty(context)
    returns, close = context.returns, context.close
    for security in close:
        proxies = context.sector_proxy[security].dropna().unique()
        for proxy in proxies:
            if proxy not in close:
                continue
            relative = close[security] / close[security].shift(5) - 1
            proxy_return = close[proxy] / close[proxy].shift(5) - 1
            if residual:
                variance = returns[proxy].rolling(60, min_periods=60).var().replace(0, np.nan)
                beta = returns[security].rolling(60, min_periods=60).cov(returns[proxy]) / variance
                value = -(relative - beta * proxy_return)
            else:
                value = relative - proxy_return
            mask = context.sector_proxy[security].eq(proxy) & context.sector_available_at[security].notna()
            output.loc[mask, security] = value.loc[mask]
    return output


def builtin_factors():
    factors = []
    for window in (1, 5, 10):
        factors.append(FunctionalFactor(f"reversal_{window}d", window,
            lambda c, w=window: -(c.close / c.close.shift(w) - 1), f"-(close/close.shift({window})-1)"))
    factors += [
        FunctionalFactor("momentum_12_1", 252, lambda c: c.close.shift(21) / c.close.shift(252) - 1, "close[t-21]/close[t-252]-1"),
        FunctionalFactor("sector_residual_5d", 60, lambda c: sector_feature(c, True), "-(stock_ret5-beta_sector60*sector_ret5)", "sector"),
        FunctionalFactor("realized_vol_20", 20, lambda c: c.returns.rolling(20, min_periods=20).std(ddof=1) * np.sqrt(252), "sample std of 20 daily returns * sqrt(252)"),
        FunctionalFactor("vol_ratio_5_20", 20, lambda c: c.returns.rolling(5,min_periods=5).std() / c.returns.rolling(20,min_periods=20).std().replace(0,np.nan), "std(ret,5)/std(ret,20), ddof=1"),
        FunctionalFactor("adv20", 19, lambda c: (c.close*c.panels["volume"]).rolling(20,min_periods=20).mean(), "mean(close*volume,20); Yahoo scale is vendor basis"),
        FunctionalFactor("amihud20", 20, lambda c: (c.returns.abs()/(c.close*c.panels["volume"]).replace(0,np.nan)).rolling(20,min_periods=20).mean(), "mean(abs(ret)/(close*volume),20), unscaled USD^-1"),
        FunctionalFactor("close_location", 0, lambda c: (c.close-c.panels["low"])/(c.panels["high"]-c.panels["low"]).replace(0,np.nan), "(close-low)/(high-low)"),
        FunctionalFactor("rel_strength_sector_5d", 5, lambda c: sector_feature(c,False), "stock_ret5-sector_ret5", "sector"),
        FunctionalFactor("beta_60", 60, market_beta, "cov(stock_ret,SPY_ret,60)/var(SPY_ret,60)", "market"),
        FunctionalFactor("size_pit", 0, empty, "-log(PIT market_cap); gated", missing_reason="PIT_MARKET_CAP_UNAVAILABLE"),
        FunctionalFactor("quality_pit", 0, empty, "PIT profitability; gated", missing_reason="PIT_FUNDAMENTALS_UNAVAILABLE"),
    ]
    return factors
