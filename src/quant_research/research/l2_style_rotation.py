"""L2 seven-style ETF proxy registry and causal observation calculations.

This module consumes already-verified adjusted close and availability matrices.
It does not fetch, persist, repair, or substitute market data.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


PROTOCOL_VERSION = "qdr-l2-style-observation-v1"
WINDOWS = (5, 20, 60)


@dataclass(frozen=True)
class StyleDefinition:
    style_id: str
    name: str
    kind: str
    numerator: tuple[str, ...]
    denominator: tuple[str, ...]
    benchmark: str
    note: str


STYLE_REGISTRY: tuple[StyleDefinition, ...] = (
    StyleDefinition("size", "规模 Size", "pair", ("IWM",), ("SPY",), "SPY",
                    "小盘 ETF 相对大盘 ETF；不是历史小盘股票组合。"),
    StyleDefinition("value", "价值 Value", "pair", ("IWD",), ("IWF",), "IWF",
                    "价值 ETF 相对成长 ETF。"),
    StyleDefinition("growth", "成长 Growth", "pair", ("IWF",), ("SPY",), "SPY",
                    "成长 ETF 相对大盘 ETF。"),
    StyleDefinition("momentum", "动量 Momentum", "pair", ("MTUM",), ("SPY",), "SPY",
                    "规则化动量 ETF 相对大盘 ETF。"),
    StyleDefinition("quality", "质量 Quality", "pair", ("QUAL",), ("SPY",), "SPY",
                    "质量 ETF 代理，不等同 French RMW。"),
    StyleDefinition("low_vol", "低波动 Low Vol", "pair", ("USMV",), ("SPY",), "SPY",
                    "低波动 ETF 相对大盘 ETF。"),
    StyleDefinition("cyc_def", "周期/防御 Cyclical / Defensive", "basket",
                    ("XLI", "XLY", "XLB", "XLF"), ("XLP", "XLU", "XLV"),
                    "equal_weight_defensive_sector_basket",
                    "两侧均为固定成分、等权行业 ETF 组合；周期减防御。"),
)

STYLE_REGISTRY_VERSION = "seven-style-etf-proxy-v1"
REQUIRED_SYMBOLS = tuple(sorted({
    symbol
    for style in STYLE_REGISTRY
    for symbol in (*style.numerator, *style.denominator)
}))


def registry_payload() -> dict:
    """JSON-safe, immutable-by-convention registry payload for API/UI consumers."""
    return {
        "schema": "qdr.l2.style-registry.v1",
        "registry_version": STYLE_REGISTRY_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "styles": [
            {
                "style_id": style.style_id,
                "name": style.name,
                "kind": style.kind,
                "numerator": list(style.numerator),
                "denominator": list(style.denominator),
                "benchmark": style.benchmark,
                "note": style.note,
            }
            for style in STYLE_REGISTRY
        ],
        "required_symbols": list(REQUIRED_SYMBOLS),
    }


def _validate_inputs(prices: pd.DataFrame, availability: pd.DataFrame) -> None:
    if not isinstance(prices, pd.DataFrame) or not isinstance(availability, pd.DataFrame):
        raise TypeError("prices and availability must be pandas DataFrames")
    if not isinstance(prices.index, pd.DatetimeIndex):
        raise ValueError("Prices require a DatetimeIndex of exchange sessions")
    if (not prices.index.equals(availability.index)
            or not prices.columns.equals(availability.columns)):
        raise ValueError("Prices and availability must have identical index and columns")
    if prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValueError("Exchange sessions must be unique and increasing")
    if prices.columns.has_duplicates:
        raise ValueError("Duplicate symbols are not allowed")
    missing = sorted(set(REQUIRED_SYMBOLS) - set(prices.columns))
    if missing:
        raise ValueError("Missing required style proxy symbols: " + ",".join(missing))
    numeric = prices.loc[:, REQUIRED_SYMBOLS].apply(pd.to_numeric, errors="coerce")
    if numeric.where(numeric.notna()).le(0).any().any():
        raise ValueError("Observed adjusted close prices must be positive")


def _daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple close-to-close returns; missing sessions remain missing."""
    return prices.loc[:, REQUIRED_SYMBOLS].pct_change(fill_method=None)


def _basket_return(daily: pd.DataFrame, symbols: tuple[str, ...]) -> pd.Series:
    """Equal-weight daily basket return; all constituents must be observed."""
    values = daily.loc[:, list(symbols)]
    complete = values.notna().all(axis=1)
    return values.mean(axis=1).where(complete)


def _rolling_available(availability: pd.DataFrame, symbols: tuple[str, ...],
                       window: int) -> pd.Series:
    """Exact UTC maximum over all window+1 closes without rolling datetime aggregation.

    A return window of N sessions consumes N+1 close prices. Missing any
    constituent availability blocks the complete window. Work with int64 UTC
    nanoseconds to avoid pandas' unsupported datetime rolling.max and float
    timestamp precision loss.
    """
    values = availability.loc[:, list(symbols)]
    complete = values.notna().all(axis=1).to_numpy(dtype=bool)
    latest = pd.to_datetime(values.max(axis=1), utc=True)
    count = window + 1
    out = np.full(len(values), np.iinfo(np.int64).min, dtype=np.int64)
    if len(values) >= count:
        raw = latest.array.asi8
        maxima = np.lib.stride_tricks.sliding_window_view(
            np.where(complete, raw, np.iinfo(np.int64).min), count
        ).max(axis=1)
        valid = np.convolve(
            complete.astype(np.int16), np.ones(count, dtype=np.int16),
            mode="valid"
        ).eq(count) if hasattr(np.ndarray, "eq") else (
            np.convolve(complete.astype(np.int16),
                        np.ones(count, dtype=np.int16), mode="valid") == count
        )
        out[count - 1:] = np.where(valid, maxima, np.iinfo(np.int64).min)
    return pd.Series(pd.to_datetime(out, utc=True), index=values.index)


def _rolling_wealth_drawdown(returns: pd.Series, window: int) -> pd.Series:
    """Current relative-wealth drawdown from the running peak in the window."""
    def calculate(values: np.ndarray) -> float:
        wealth = np.cumprod(1.0 + values)
        peaks = np.maximum.accumulate(np.r_[1.0, wealth])[1:]
        return float(wealth[-1] / peaks[-1] - 1.0)
    return returns.rolling(window, min_periods=window).apply(calculate, raw=True)


def style_observations_v1(prices: pd.DataFrame,
                          availability: pd.DataFrame) -> pd.DataFrame:
    """Calculate seven style observations without forward filling or future data.

    prices must contain a common-session matrix of source-verified,
    split/dividend-adjusted close prices. availability must contain the
    first-known/available timestamp for each corresponding price observation.
    """
    _validate_inputs(prices, availability)
    close = prices.loc[:, REQUIRED_SYMBOLS].apply(pd.to_numeric, errors="coerce")
    source_availability = availability.loc[:, REQUIRED_SYMBOLS].apply(
        pd.to_datetime, utc=True, errors="coerce"
    )
    # A price without its first-known timestamp is not an eligible observation.
    close = close.where(source_availability.notna())
    returns = _daily_returns(close)

    records: list[pd.DataFrame] = []
    for style in STYLE_REGISTRY:
        if style.kind == "pair":
            numerator = returns[style.numerator[0]]
            denominator = returns[style.denominator[0]]
            daily_relative = (1.0 + numerator) / (1.0 + denominator) - 1.0
            required = (*style.numerator, *style.denominator)
        else:
            numerator = _basket_return(returns, style.numerator)
            denominator = _basket_return(returns, style.denominator)
            daily_relative = (1.0 + numerator) / (1.0 + denominator) - 1.0
            required = (*style.numerator, *style.denominator)
        daily_relative = daily_relative.replace([np.inf, -np.inf], np.nan)
        item = pd.DataFrame({
            "date": close.index,
            "style_id": style.style_id,
            "style_name": style.name,
            "benchmark": style.benchmark,
            "daily_relative_return": daily_relative.to_numpy(),
        })
        item["relative_up_days_10"] = daily_relative.gt(0).where(
            daily_relative.notna()
        ).rolling(10, min_periods=10).sum().to_numpy()
        item["relative_volatility_20d"] = daily_relative.rolling(
            20, min_periods=20
        ).std(ddof=1).to_numpy()
        for window in WINDOWS:
            item[f"relative_return_{window}d"] = (
                (1.0 + daily_relative).rolling(window, min_periods=window)
                .apply(np.prod, raw=True) - 1.0
            ).to_numpy()
            item[f"relative_return_{window}d_available_at"] = (
                _rolling_available(source_availability, required, window).to_numpy()
            )
        item["relative_acceleration_5d"] = (
            item["relative_return_5d"] -
            item["relative_return_5d"].shift(5)
        )
        item["relative_drawdown_20d"] = _rolling_wealth_drawdown(
            daily_relative, 20
        ).to_numpy()
        item["relative_drawdown_60d"] = _rolling_wealth_drawdown(
            daily_relative, 60
        ).to_numpy()
        item["available_at"] = item["relative_return_60d_available_at"]
        item["complete_historical_window"] = (
            item["relative_return_60d"].notna() & item["available_at"].notna()
        )
        item["protocol_version"] = PROTOCOL_VERSION
        item["registry_version"] = STYLE_REGISTRY_VERSION
        item["decision_eligible"] = False
        records.append(item)

    output = pd.concat(records, ignore_index=True)
    return output.sort_values(["date", "style_id"], kind="stable").reset_index(drop=True)
