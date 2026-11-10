import numpy as np
import pandas as pd


def finite(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def summarize(curve,trades,initial_cash):
    if curve.empty:
        return {"status":"NO_DATA"}
    equity = curve.equity.astype(float)
    returns = curve.daily_return if "daily_return" in curve else equity.pct_change(fill_method=None).fillna(equity.iloc[0]/initial_cash-1)
    growth = float((1+returns).prod())
    annual = growth**(252/len(returns))-1 if growth>0 else -1
    deviation = returns.std(ddof=1)
    base = equity.iloc[0]/(1+returns.iloc[0]) if returns.iloc[0]>-1 else initial_cash
    peaks = pd.Series(np.maximum.accumulate(np.r_[base,equity.to_numpy()])[1:],index=equity.index)
    drawdown = equity/peaks-1
    gross_profit = float(curve.gross_equity_same_fills.iloc[-1]-initial_cash)
    costs = float(curve.cumulative_costs.iloc[-1])
    return {"net_total_return":growth-1,"net_annualized_return":annual,
        "daily_sharpe_annualized":finite(returns.mean()/deviation*np.sqrt(252)) if deviation>0 else None,
        "annualized_volatility":finite(deviation*np.sqrt(252)),"max_drawdown":float(drawdown.min()),
        "calmar":annual/abs(float(drawdown.min())) if drawdown.min()<0 else None,
        "worst_1d":float(returns.min()),"worst_5d":finite((1+returns).rolling(5).apply(np.prod,raw=True).min()-1),
        "closed_lot_slices":len(trades),"average_holding_sessions":finite(trades.holding_sessions.mean()) if len(trades) else None,
        "median_holding_sessions":finite(trades.holding_sessions.median()) if len(trades) else None,
        "costs":costs,"cost_to_positive_gross_profit":costs/gross_profit if gross_profit>0 else None,
        "gross_profit_nonpositive":gross_profit<=0,"average_capital_utilization":finite(curve.observed_gross_exposure.mean()),
        "average_close_exposure":finite(curve.gross_exposure.mean()),"average_open_exposure":finite(curve.opening_gross_exposure.mean()),
        "capital_utilization_definition":"mean(max(observed_open_exposure,close_exposure)); not exact intraday time-weighted",
        "final_equity":float(equity.iloc[-1]),"status":"MODELED_HISTORICAL_FILLS_NOT_BROKER_ORDERS"}
