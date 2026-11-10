"""Causal market observations and tradable ETF style proxies, not pure FF factors."""
import numpy as np
import pandas as pd

from .context import rolling_available

STYLE_PAIRS = {"small":("IWM","SPY"),"value":("IWD","IWF"),"momentum":("MTUM","SPY"),
               "quality":("QUAL","SPY"),"low_vol":("USMV","SPY")}
SECTORS = ["XLK","XLF","XLE","XLV","XLI","XLP","XLY","XLU","XLB","XLRE"]


def observations(context):
    by_symbol = {symbol:sid for sid,symbol in context.symbols.items()}
    close = context.close.rename(columns=context.symbols)
    returns = close.pct_change(fill_method=None)
    result = pd.DataFrame(index=close.index)
    for window in (1,5,20):
        result[f"market_return_{window}"] = close.SPY/close.SPY.shift(window)-1
    for window in (5,20):
        result[f"market_vol_{window}"] = returns.SPY.rolling(window,min_periods=window).std()*np.sqrt(252)
    result["market_vol_ratio"] = result.market_vol_5/result.market_vol_20.replace(0,np.nan)
    for name,a,b in [("concentration","RSP","SPY"),("credit","HYG","LQD")]:
        for window in (5,20):
            result[f"market_{name}_{window}"] = (close[a]/close[a].shift(window)-1)-(close[b]/close[b].shift(window)-1) if a in close and b in close else np.nan
    existing = [s for s in SECTORS if s in close]
    if len(existing)>=2:
        result["market_sector_dispersion"] = (close[existing]/close[existing].shift(5)-1).std(axis=1)
        correlations = []
        for i,a in enumerate(existing):
            for b in existing[i+1:]:
                correlations.append(returns[a].rolling(20,min_periods=20).corr(returns[b]))
        result["market_sector_mean_correlation"] = pd.concat(correlations,axis=1).mean(axis=1)
        result["market_breadth_etf_proxy"] = close[existing].gt(close[existing].rolling(20,min_periods=20).mean()).mean(axis=1).where(close[existing].notna().all(axis=1)&close[existing].rolling(20,min_periods=20).count().eq(20).all(axis=1))
    for name,(a,b) in STYLE_PAIRS.items():
        if a not in close or b not in close:
            for field in ("relative_return_5d","relative_return_20d","relative_acceleration","positive_days_10","relative_volatility_20d"):
                result[f"style_{name}_{field}"] = np.nan
            continue
        ratio = close[a]/close[b]
        daily = ratio.pct_change(fill_method=None)
        result[f"style_{name}_relative_return_5d"] = ratio/ratio.shift(5)-1
        result[f"style_{name}_relative_return_20d"] = ratio/ratio.shift(20)-1
        result[f"style_{name}_relative_acceleration"] = result[f"style_{name}_relative_return_5d"]/5-result[f"style_{name}_relative_return_20d"]/20
        result[f"style_{name}_positive_days_10"] = daily.gt(0).astype(float).where(daily.notna()).rolling(10,min_periods=10).sum()
        result[f"style_{name}_relative_volatility_20d"] = daily.rolling(20,min_periods=20).std()
    # Conservative union of all 21-session observed inputs, preserving first observation times.
    available = context.available(21).max(axis=1)
    complete = close.notna().rolling(21,min_periods=21).sum().eq(21).all(axis=1)
    result.loc[~complete,:] = np.nan
    result["state_available_at"] = available
    result.index.name = "date"
    return result.replace([np.inf,-np.inf],np.nan)


def frozen_states(observed, train_end, quantile=0.5):
    training = observed.loc[observed.index<=pd.Timestamp(train_end)]
    threshold = training.market_vol_20.quantile(quantile)
    result = observed.copy()
    result["market_state"] = np.where(result.market_return_20>=0,"UP","DOWN")+pd.Series(np.where(result.market_vol_20>=threshold,"_HIGH_VOL","_LOW_VOL"),index=result.index)
    result.loc[result.market_return_20.isna()|result.market_vol_20.isna(),"market_state"] = "UNKNOWN"
    thresholds = {"market_vol_20":None if pd.isna(threshold) else float(threshold)}
    threshold_available = training.state_available_at.max()
    result["threshold_available_at"] = threshold_available
    result["state_available_at"] = pd.concat([result.state_available_at,pd.Series(threshold_available,index=result.index)],axis=1).max(axis=1)
    for name in STYLE_PAIRS:
        level = f"style_{name}_relative_return_20d"
        acceleration = f"style_{name}_relative_acceleration"
        center = training[level].median()
        accel = training[acceleration].median()
        thresholds[name] = {"level":None if pd.isna(center) else float(center),"acceleration":None if pd.isna(accel) else float(accel)}
        strong,improving = result[level]>=center,result[acceleration]>=accel
        result[f"style_{name}_state"] = np.select([strong&improving,strong&~improving,~strong&improving],["强势加速","强势减速","弱势改善"],default="弱势恶化")
        result.loc[result[level].isna()|result[acceleration].isna(),f"style_{name}_state"] = "UNKNOWN"
    return result,thresholds
