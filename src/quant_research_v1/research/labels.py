"""T+1 open → T+H close outcomes. Proxy prices never populate formal raw labels."""
import numpy as np
import pandas as pd
from quant_research.policy import PolicyError


def make_labels(context, clock, horizons=(1,3,5), adjustment_basis="raw", exclude_symbols=()):
    if set(horizons) != {1,3,5}:
        raise ValueError("Independent H1/H3/H5 experiments required")
    if adjustment_basis == 'raw':
        raise PolicyError('RAW_LABEL_EVIDENCE_MISSING',
                          'Raw OHLC alone cannot establish a corporate-action-consistent outcome',
                          ['accepted corporate-action ledger and settlement treatment'])
    if adjustment_basis not in ("yahoo_split_adjusted", "split_adjusted_price_proxy"):
        raise ValueError("Unsupported label price basis")
    results = []
    index = context.close.index
    for horizon in horizons:
        opening = context.panels["open"].shift(-1)
        closing = context.close.shift(-horizon)
        values = closing/opening - 1
        # Any missing session inside a label window invalidates it.
        complete = context.close.notna().astype(int)
        valid = complete * 0 + 1
        for shift in range(1,horizon+1):
            valid = valid * complete.shift(-shift).fillna(0)
        values = values.where(valid.eq(1) & opening.gt(0))
        benchmark = values[context.benchmark_id]
        availability = context.availability.shift(-1).copy()
        for offset in range(2,horizon+1):
            shifted = context.availability.shift(-offset)
            availability = availability.where(availability.ge(shifted) | shifted.isna(),shifted)
        windows = [clock.window(day,horizon) for day in index]
        entry_times = [w.entry_time for w in windows]
        exit_times = [w.exit_time for w in windows]
        for sid in values:
            if context.symbols[sid] in exclude_symbols:
                continue
            available = pd.concat([availability[sid],availability[context.benchmark_id]],axis=1).max(axis=1)
            part = pd.DataFrame({"date":index,"security_id":sid,"horizon":horizon,
                "entry_time":entry_times,"exit_time":exit_times,"available_at":available.to_numpy(),
                "forward_return":np.nan,"benchmark_return":np.nan,
                "proxy_forward_return":values[sid].to_numpy(),
                "proxy_benchmark_return":benchmark.to_numpy(),
                "net_return":np.nan,"adjustment_basis":adjustment_basis,
                "label_kind":"EXPLORATORY_PRICE_PROXY_NOT_FILL",
                "missing_reason":np.where(values[sid].notna(),"","INCOMPLETE_LABEL_WINDOW")})
            part["entry_date"] = pd.to_datetime(part.entry_time,utc=True).dt.tz_convert("America/New_York").dt.date
            part["exit_date"] = pd.to_datetime(part.exit_time,utc=True).dt.tz_convert("America/New_York").dt.date
            results.append(part)
    return pd.concat(results,ignore_index=True)
