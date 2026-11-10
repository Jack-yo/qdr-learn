"""Factor plugins share alignment, dependency availability and strict decision gating."""
import numpy as np
import pandas as pd

from .factors import builtin_factors


def validate_causality(factor, context, values):
    """Prefix recomputation rejects common future-shift/full-sample transforms."""
    from .context import FactorContext
    length = len(context.close)
    for stop in sorted({max(1,length//2),max(1,length-5)}):
        prefix = FactorContext({k:v.iloc[:stop].copy() for k,v in context.panels.items()},
            context.availability.iloc[:stop].copy(),context.symbols,context.benchmark_id,
            None if context.sector_proxy is None else context.sector_proxy.iloc[:stop].copy(),
            None if context.sector_available_at is None else context.sector_available_at.iloc[:stop].copy())
        try:
            pd.testing.assert_frame_equal(factor.compute(prefix),values.iloc[:stop],check_exact=False,rtol=1e-10,atol=1e-12)
        except AssertionError:
            raise ValueError(f"Non-causal factor rejected by prefix check: {factor.name}") from None


def compute_features(context, clock, factors=None, mode="strict", exclude_symbols=()):
    if mode not in ("strict", "retrospective"):
        raise ValueError("Unknown research mode")
    factors = list(builtin_factors() if factors is None else factors)
    if len({f.name for f in factors}) != len(factors):
        raise ValueError("Duplicate factor registry name")
    columns = [sid for sid in context.close if context.symbols[sid] not in exclude_symbols]
    signals = pd.Series([clock.signal(day) for day in context.close.index], index=context.close.index)
    results = []
    for factor in factors:
        if factor.lookback < 0 or factor.dependency not in ("self", "market", "sector"):
            raise ValueError("Invalid factor dependency declaration")
        values = factor.compute(context)
        if not values.index.equals(context.close.index) or not values.columns.equals(context.close.columns):
            raise ValueError("Factor must preserve context index and columns")
        validate_causality(factor,context,values)
        values = values[columns].replace([np.inf,-np.inf],np.nan)
        available = context.available(factor.lookback + 1)[columns].copy()
        if factor.dependency == "market":
            benchmark = context.available(factor.lookback+1)[context.benchmark_id]
            available = available.apply(lambda x: pd.concat([x, benchmark], axis=1).max(axis=1))
        if factor.dependency == "sector" and context.sector_proxy is not None and context.sector_available_at is not None:
            for security in columns:
                for proxy in context.sector_proxy[security].dropna().unique():
                    if proxy in context.availability:
                        mask = context.sector_proxy[security].eq(proxy)
                        combined = pd.concat([available[security], context.available(factor.lookback+1)[proxy], context.sector_available_at[security]], axis=1).max(axis=1)
                        available.loc[mask,security] = combined.loc[mask]
        # Require complete calendar windows for each declared dependency.
        complete = context.close[columns].notna().rolling(factor.lookback+1,min_periods=factor.lookback+1).sum().eq(factor.lookback+1)
        if factor.dependency == "market":
            complete = complete.mul(context.close[context.benchmark_id].notna().rolling(factor.lookback+1,min_periods=factor.lookback+1).sum().eq(factor.lookback+1),axis=0)
        if factor.dependency == "sector" and context.sector_proxy is not None:
            for security in columns:
                for proxy in context.sector_proxy[security].dropna().unique():
                    mask = context.sector_proxy[security].eq(proxy)
                    good = context.close[proxy].notna().rolling(factor.lookback+1,min_periods=factor.lookback+1).sum().eq(factor.lookback+1) if proxy in context.close else False
                    complete.loc[mask,security] &= good.loc[mask] if hasattr(good,"loc") else good
        values = values.where(complete)
        eligible = available.le(signals,axis=0) & values.notna()
        reason = pd.DataFrame("",index=values.index,columns=values.columns)
        reason = reason.mask(values.isna(), "INSUFFICIENT_HISTORY_OR_UNDEFINED")
        if factor.missing_reason:
            reason.loc[:,:] = factor.missing_reason
        if factor.dependency == "sector" and (context.sector_proxy is None or context.sector_available_at is None):
            reason.loc[:,:] = "PIT_SECTOR_MAPPING_UNAVAILABLE"
        if mode == "strict":
            reason = reason.mask(values.notna() & ~eligible,"INPUT_NOT_AVAILABLE_AT_SIGNAL")
            values = values.where(eligible)
        # Retrospective values never become historical trading features.
        eligible = eligible if mode == "strict" else eligible & False
        index = pd.MultiIndex.from_product([values.index,columns],names=["date","security_id"])
        part = pd.DataFrame({"value":values.to_numpy().reshape(-1),
                             "available_at":available.to_numpy().reshape(-1),
                             "decision_eligible":eligible.to_numpy().reshape(-1),
                             "missing_reason":reason.to_numpy().reshape(-1)},index=index).reset_index()
        part["feature_name"], part["version"], part["research_mode"] = factor.name, factor.version, mode
        part["signal_time"] = part.date.map(signals)
        results.append(part)
    if not results:
        raise ValueError("No factors registered")
    return pd.concat(results,ignore_index=True)
