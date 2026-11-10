from math import isfinite

import numpy as np
import pandas as pd

from .engine import PortfolioEngine
from .metrics import summarize


def candidates(rows,engine,config,day,end,horizon,baseline=False):
    result = []
    if rows.empty:
        return result
    rows = rows.sort_values("reversal_5d" if baseline else "expected_excess_return",ascending=False,kind="stable")
    for _,row in rows.iterrows():
        if len(result)>=config.top_n:
            break
        if not bool(row.decision_eligible) or row.feature_available_at>row.signal_time:
            continue
        if not all(isfinite(float(row[c])) for c in ["adv20","atr20","reference_close"]):
            continue
        if row.adv20<config.minimum_adv20 or row.reference_close<config.minimum_price:
            continue
        if str(pd.Timestamp(row.exit_time).date())>end:
            continue  # predetermined experiment boundary, not future price availability
        estimate = engine.cost.round_trip_fraction(config.max_stock_weight*engine.equity(),row.adv20)
        if not baseline and (not isfinite(row.predicted_return) or row.predicted_return<=estimate or not isfinite(row.downside_quantile) or row.downside_quantile < -config.max_unconditional_downside):
            continue
        result.append({"security_id":str(row.security_id),"symbol":str(row.symbol),"sector":str(row.sector),
            "signal_time":str(row.signal_time),"feature_available_at":str(row.feature_available_at),"fit_time":str(row.fit_time),
            "exit_date":str(pd.Timestamp(row.exit_time).date()),"adv20":float(row.adv20),"atr20":float(row.atr20),
            "decision_eligible":True,"adjustment_basis":"raw"})
    return result


def simulate(prices,context,clock,config,predictions,variant,horizon,cost,baseline=None):
    from quant_research.policy import execution_blocked
    execution_blocked()
