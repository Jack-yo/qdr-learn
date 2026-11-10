from datetime import datetime, timezone

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.policy import require_real_source
from quant_research.data.bundle import load_real_bundle
from quant_research.data.store import Warehouse
from quant_research.features.context import make_context
from quant_research.features.context import FactorContext
from quant_research.features.engine import compute_features
from quant_research.features.states import observations
from quant_research.research.labels import make_labels

ALPHA_COLUMNS = ["reversal_1d","reversal_5d","reversal_10d","momentum_12_1","realized_vol_20","vol_ratio_5_20","adv20","amihud20","close_location","beta_60"]


def prepare_market(context, observed, clock, horizons, basis):
    """Build one SPY outcome per signal session and horizon."""
    other_symbols = [symbol for sid, symbol in context.symbols.items()
                     if sid != context.benchmark_id]
    labels = make_labels(context, clock, horizons, basis, other_symbols)
    labels = labels.rename(columns={"available_at": "label_available_at",
                                    "proxy_benchmark_return": "benchmark_target"})
    market_features = [name for name in observed if name.startswith("market_")]
    features = observed[market_features + ["state_available_at"]].dropna()
    frame = labels.merge(features, left_on="date", right_index=True, validate="many_to_one")
    frame["signal_time"] = frame.date.map({day: clock.signal(day) for day in features.index})
    return frame


def load_panel(source,db,config,end=None,capability='exploratory_price_factors'):
    clock = TradingClock()
    end = str(end or config.validation_end)
    require_real_source(source)
    bundle=load_real_bundle(db,source,end,start=str(config.start))
    bundle.require(capability)
    prices=bundle.prices
    return prices,make_context(prices,clock,"SPY",str(config.start),end),clock


def prepare(context,clock,mode,basis,label_end=None,forecast_dates=()):
    features = compute_features(context,clock,mode=mode,exclude_symbols=["SPY","HYG","LQD"])
    wide = features.pivot(index=["date","security_id"],columns="feature_name",values="value").reset_index()
    availability = features.groupby(["date","security_id"]).available_at.max().rename("feature_available_at").reset_index()
    wide = wide.merge(availability,on=["date","security_id"],validate="one_to_one")
    observed = observations(context)
    market_columns = [c for c in observed if c.startswith("market_")]
    style_columns = [c for c in observed if c.startswith("style_")]
    wide = wide.merge(observed.reset_index(),on="date",validate="many_to_one")
    wide["feature_available_at"] = wide[["feature_available_at","state_available_at"]].max(axis=1)
    wide["signal_time"] = wide.date.map({d:clock.signal(d) for d in context.close.index})
    wide["interaction_reversal_market"] = wide.reversal_5d*wide.market_return_20
    momentum_style = "style_momentum_relative_return_5d"
    wide["interaction_momentum_style"] = wide.momentum_12_1*wide.get(momentum_style,np.nan)
    label_context=context
    if label_end is not None:
        label_context=FactorContext({k:v.loc[:str(label_end)] for k,v in context.panels.items()},context.availability.loc[:str(label_end)],context.symbols,context.benchmark_id)
    labels = make_labels(label_context,clock,adjustment_basis=basis,exclude_symbols=["SPY","HYG","LQD"])
    dummy=[]
    for day in pd.DatetimeIndex(forecast_dates):
        if day in label_context.close.index:
            continue
        for sid,symbol in context.symbols.items():
            if symbol in ("SPY","HYG","LQD"):
                continue
            for horizon in (1,3,5):
                window=clock.window(day,horizon)
                dummy.append({"date":day,"security_id":sid,"horizon":horizon,"entry_time":window.entry_time,"exit_time":window.exit_time,
                    "available_at":pd.NaT,"forward_return":np.nan,"benchmark_return":np.nan,"proxy_forward_return":np.nan,"proxy_benchmark_return":np.nan,
                    "net_return":np.nan,"adjustment_basis":basis,"label_kind":"LIVE_FORECAST_NO_OUTCOME_READ","missing_reason":"FUTURE_OUTCOME_NOT_READ",
                    "entry_date":window.entry_time.date(),"exit_date":window.exit_time.date()})
    if dummy:
        extra=pd.DataFrame(dummy,columns=labels.columns)
        for column in ("entry_time","exit_time","available_at"):
            extra[column]=pd.to_datetime(extra[column],utc=True)
        extra=extra.astype(labels.dtypes.to_dict())
        labels=pd.concat([labels,extra],ignore_index=True)
    labels["target"] = labels.forward_return.fillna(labels.proxy_forward_return)
    labels["benchmark_target"] = labels.benchmark_return.fillna(labels.proxy_benchmark_return)
    labels["excess_target"] = labels.target-labels.benchmark_target
    labels = labels.rename(columns={"available_at":"label_available_at"})
    frame = wide.merge(labels,on=["date","security_id"],validate="one_to_many")
    previous = context.close.shift(1)
    tr = pd.DataFrame(np.maximum.reduce([(context.panels["high"]-context.panels["low"]).to_numpy(),
        (context.panels["high"]-previous).abs().to_numpy(),(context.panels["low"]-previous).abs().to_numpy()]),index=context.close.index,columns=context.close.columns)
    atr = tr.rolling(20,min_periods=20).mean().stack(future_stack=True).rename("atr20").rename_axis(["date","security_id"]).reset_index()
    frame = frame.merge(atr,on=["date","security_id"],validate="many_to_one")
    frame["reference_close"] = [context.close.loc[d,sid] for d,sid in zip(frame.date,frame.security_id)]
    frame["symbol"] = frame.security_id.map(context.symbols)
    # Historical classification is unavailable; never backfill current categories.
    frame["sector"] = "UNKNOWN"
    return frame,observed,market_columns,style_columns
