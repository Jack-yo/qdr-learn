"""Real-price, gated historical simulation.

No invented bars, security identities, availability times or corporate actions.
This is a hypothetical fill model, never a broker-execution record.
"""
from math import isfinite

import pandas as pd

from quant_research.policy import PolicyError
from .engine import PortfolioEngine
from .metrics import summarize


def candidates(rows, engine, config, day, end, horizon, baseline=False):
    result = []
    if rows.empty:
        return result
    ranking = "reversal_5d" if baseline else "expected_excess_return"
    rows = rows.sort_values(ranking, ascending=False, kind="stable")
    for _, row in rows.iterrows():
        if len(result) >= config.top_n:
            break
        if not bool(row.decision_eligible) or pd.Timestamp(row.feature_available_at) > pd.Timestamp(row.signal_time):
            continue
        if any(not isfinite(float(row[c])) for c in ("adv20", "atr20", "reference_close")):
            continue
        if row.adv20 < config.minimum_adv20 or row.reference_close < config.minimum_price:
            continue
        if str(pd.Timestamp(row.exit_time).date()) > str(end):
            continue
        estimate = engine.cost.round_trip_fraction(config.max_stock_weight * engine.equity(), row.adv20)
        if not baseline and (not isfinite(float(row.predicted_return)) or row.predicted_return <= estimate
                             or not isfinite(float(row.downside_quantile))
                             or row.downside_quantile < -config.max_unconditional_downside):
            continue
        result.append({
            "security_id": str(row.security_id), "symbol": str(row.symbol), "sector": str(row.sector),
            "signal_time": str(row.signal_time), "feature_available_at": str(row.feature_available_at),
            "fit_time": str(row.fit_time), "exit_date": str(pd.Timestamp(row.exit_time).date()),
            "adv20": float(row.adv20), "atr20": float(row.atr20),
            "decision_eligible": True, "adjustment_basis": "raw",
        })
    return result


def _frame(items):
    return pd.DataFrame(items)


def simulate(prices, context, clock, config, predictions, variant, horizon, cost,
             baseline=None, *, bundle=None, corporate_events=None):
    """Execute audited, historically timestamped signals against verified raw OHLCV.

    ``bundle.require('historical_backtest')`` is mandatory, *not* an opt-in boolean.
    ``corporate_events`` must cover the entire interval (empty event lists permitted
    only when the bundle independently certifies the action calendar as complete).
    Pending orders fill at the following session's observed raw open, with modeled
    slippage/fees, while positions are marked at raw closes.
    """
    if bundle is None:
        raise PolicyError("BACKTEST_EVIDENCE_REQUIRED", "Verified DatasetBundle is required")
    bundle.require("historical_backtest")
    if corporate_events is None:
        raise PolicyError("ACTION_LEDGER_REQUIRED", "Accepted event calendar required, including empty sessions")
    if horizon not in (1, 3, 5):
        raise ValueError("Horizon must be 1/3/5")
    if prices.empty or predictions.empty:
        raise PolicyError("BACKTEST_INPUT_EMPTY", "No real bars or eligible predictions")
    if set(prices.adjustment_basis) != {"raw"} or set(prices.source) != {"ALPACA"}:
        raise PolicyError("RAW_PRICES_REQUIRED", "Unadjusted, source-verified execution prices required")
    # Prevent callers from switching the accepted price dataset after admission.
    from quant_research.data.bundle import frame_hash
    if frame_hash(prices) != bundle.metadata["snapshot_sha256"]:
        raise PolicyError("BACKTEST_PRICE_MUTATED", "Price frame differs from accepted snapshot")
    required = {"date", "security_id", "symbol", "sector", "horizon", "variant", "decision_eligible",
                "signal_time", "feature_available_at", "fit_time", "exit_time", "adv20", "atr20",
                "reference_close", "predicted_return", "expected_excess_return", "downside_quantile", "reversal_5d"}
    if missing := required - set(predictions.columns):
        raise PolicyError("BACKTEST_PREDICTIONS_INCOMPLETE", "Missing signal fields", sorted(missing))
    relevant = predictions.loc[predictions.horizon.eq(horizon) & predictions.variant.eq(variant)].copy()
    if relevant.empty or not relevant.decision_eligible.all():
        raise PolicyError("NO_ELIGIBLE_HISTORICAL_SIGNALS", "Only validated historical signals may be replayed")
    if relevant.duplicated(["date", "security_id", "horizon"]).any():
        raise PolicyError("DUPLICATE_SIGNALS", "One frozen signal per security and date")
    for field in ("feature_available_at", "fit_time", "signal_time"):
        relevant[field] = pd.to_datetime(relevant[field], utc=True)
    if ((relevant.feature_available_at > relevant.signal_time)
            | (relevant.fit_time > relevant.signal_time)).any():
        raise PolicyError("FUTURE_SIGNAL_INPUT", "Model/features were not available when signals were frozen")
    if relevant.signal_time.isna().any() or relevant.fit_time.isna().any():
        raise PolicyError("SIGNAL_TIME_MISSING", "Every signal needs an observed fit/signal time")
    if prices.duplicated(["date", "security_id"]).any():
        raise PolicyError("DUPLICATE_PRICE_BARS", "Duplicate execution price keys")
    engine = PortfolioEngine(config, clock, cost, True, benchmark=False)
    sessions = sorted(pd.Timestamp(d).date().isoformat() for d in prices.date.unique())
    if not sessions:
        raise PolicyError("NO_REAL_DATA", "No real trading sessions")
    # A missing entire trading day must never be silently skipped in the engine.
    for previous, current in zip(sessions, sessions[1:]):
        if str(clock.calendar.next_session(previous).date()) != current:
            raise PolicyError("MISSING_TRADING_SESSION", "Historical execution date gap", [previous, current])
    if set(sessions) - set(corporate_events):
        raise PolicyError("ACTION_COVERAGE_INCOMPLETE", "Event calendar missing sessions",
                          sorted(set(sessions) - set(corporate_events))[:10])
    last_day = sessions[-1]
    grouped_prices = {str(pd.Timestamp(day).date()): group for day, group in prices.groupby("date")}
    grouped_signals = {str(pd.Timestamp(day).date()): group for day, group in relevant.groupby("date")}
    for day in sessions:
        bars = {
            str(row.security_id): {"open": float(row.open), "high": float(row.high),
                                   "low": float(row.low), "close": float(row.close), "volume": int(row.volume)}
            for row in grouped_prices[day].itertuples(index=False)
        }
        rows = grouped_signals.get(day)
        orders = candidates(rows, engine, config, day, last_day, horizon, baseline=bool(baseline)) if rows is not None else []
        for order in orders:
            if str(pd.Timestamp(order["signal_time"]).date()) != day and pd.Timestamp(order["signal_time"]).tz_convert("America/New_York").date().isoformat() != day:
                raise PolicyError("SIGNAL_DAY_MISMATCH", "Frozen signal belongs to another session")
        engine.step(day, bars, orders, corporate_events[day])
    engine.reconcile()
    curve = _frame(engine.curve)
    trades = _frame(engine.trades)
    metrics = summarize(curve, trades, config.initial_cash)
    return {
        "status": "HISTORICAL_MODELED_FILLS_NOT_REAL_ORDERS",
        "curve": curve, "trades": trades, "fills": _frame(engine.fills),
        "orders": _frame(engine.orders), "positions": _frame(engine.position_history),
        "exposures": _frame(engine.exposures), "actions": _frame(engine.actions),
        "metrics": metrics, "flags": sorted(engine.flags),
        "data_sha256": bundle.metadata["snapshot_sha256"],
        "estimated_cost_bps_per_side": cost,
    }
