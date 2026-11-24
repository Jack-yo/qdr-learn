"""Raw-price event ledger, shared by batch simulation and persisted paper replay."""

from dataclasses import asdict, dataclass
from math import floor, isfinite

import pandas as pd

from quant_research.risk.limits import allocation_notional, stop_or_target

from .costs import CostModel


@dataclass
class Position:
    security_id: str
    symbol: str
    sector: str
    quantity: int
    entry_time: str
    entry_cash: float
    raw_entry_price: float
    exit_date: str
    stop: float | None
    adv20: float
    dividends: float = 0.0


class PortfolioEngine:
    def __init__(self, config, clock, cost_bps=10, risk_enabled=True, state=None, benchmark=False):
        self.config, self.clock = config, clock
        self.cost = CostModel(cost_bps, config.fee_bps_per_side, config.impact_bps_per_full_adv)
        self.risk_enabled, self.benchmark = risk_enabled, benchmark
        self.cash = config.initial_cash
        self.positions, self.pending, self.last_prices = {}, [], {}
        self.fills, self.trades, self.orders, self.curve, self.exposures, self.actions = [], [], [], [], [], []
        self.flags, self.total_costs, self.last_date = set(), 0.0, None
        self.position_history, self.opening_position_history, self.blocked_securities = [], [], set()
        self.kill_switch_reason = None
        if state:
            self.cash, self.total_costs, self.last_date = state["cash"], state["total_costs"], state["last_date"]
            self.positions = {key: Position(**value) for key, value in state["positions"].items()}
            self.pending, self.last_prices = state["pending"], state["last_prices"]
            self.flags = set(state["flags"])
            self.blocked_securities = set(state.get("blocked_securities", []))
            self.kill_switch_reason = state.get("kill_switch_reason")

    def state(self):
        return {
            "cash": self.cash,
            "total_costs": self.total_costs,
            "last_date": self.last_date,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "pending": self.pending,
            "last_prices": self.last_prices,
            "flags": sorted(self.flags),
            "blocked_securities": sorted(self.blocked_securities),
            "kill_switch_reason": self.kill_switch_reason,
        }

    def kill_switch(self, reason):
        self.kill_switch_reason = str(reason)
        self.flags.add("KILL_SWITCH_NEW_ENTRIES_DISABLED")
        self.pending = [o for o in self.pending if o["side"] != "BUY"]

    def equity(self, prices=None):
        marks = self.last_prices if prices is None else {**self.last_prices, **prices}
        return self.cash + sum(p.quantity * marks.get(sid, p.raw_entry_price) for sid, p in self.positions.items())

    def _sell(self, sid, quantity, price, time, reason):
        position = self.positions[sid]
        quantity = min(quantity, position.quantity)
        fill, fee, cost = self.cost.fill("SELL", price, quantity, position.adv20)
        proceeds = fill * quantity - fee
        self.cash += proceeds
        self.total_costs += cost
        share = quantity / position.quantity
        entry_cash, dividend = position.entry_cash * share, position.dividends * share
        self.fills.append(
            {
                "date": str(pd.Timestamp(time).date()),
                "security_id": sid,
                "side": "SELL",
                "quantity": quantity,
                "raw_price": price,
                "fill_price": fill,
                "fee": fee,
                "cost": cost,
                "fill_time": str(time),
                "reason": reason,
                "cash_change": proceeds,
            }
        )
        entry_day = pd.Timestamp(position.entry_time).tz_convert("America/New_York").date()
        exit_day = pd.Timestamp(time).tz_convert("America/New_York").date()
        holding = len(self.clock.calendar.sessions_in_range(entry_day, exit_day))
        self.trades.append(
            {
                "security_id": sid,
                "entry_time": position.entry_time,
                "exit_time": str(time),
                "quantity": quantity,
                "net_pnl": proceeds + dividend - entry_cash,
                "holding_sessions": holding,
                "reason": reason,
            }
        )
        self.orders.append(
            {
                "security_id": sid,
                "side": "SELL",
                "quantity": quantity,
                "fill_time": str(time),
                "status": "FILLED",
                "reason": reason,
            }
        )
        position.quantity -= quantity
        position.entry_cash -= entry_cash
        position.dividends -= dividend
        if position.quantity == 0:
            del self.positions[sid]

    def _actions(self, day, events, bars):
        for action in events:
            sid = action["security_id"]
            kind, value = action["action_type"], float(action["value"])
            if not isfinite(value) or value < 0:
                raise ValueError("Corporate action amount/factor must be finite and nonnegative")
            if action["action_type"] == "delist":
                self.blocked_securities.add(sid)
            if kind == "split":
                if value <= 0:
                    raise ValueError("Invalid split factor")
                for order in self.pending:
                    if order["security_id"] == sid:
                        if order["side"] == "SELL":
                            quantity = order["quantity"] * value
                            if abs(quantity - round(quantity)) > 1e-8:
                                raise ValueError("Fractional split order requires cash-in-lieu policy")
                            order["quantity"] = round(quantity)
                        else:
                            order["atr20"] /= value
            if sid not in self.positions:
                continue
            p = self.positions[sid]
            if kind == "split":
                quantity = p.quantity * value
                if value <= 0 or abs(quantity - round(quantity)) > 1e-8:
                    raise ValueError("Fractional split requires verified cash-in-lieu; not fabricated")
                p.quantity = round(quantity)
                p.raw_entry_price /= value
                if p.stop is not None:
                    p.stop /= value
                if sid in self.last_prices:
                    self.last_prices[sid] /= value
            elif kind == "dividend":
                from quant_research.policy import PolicyError

                raise PolicyError(
                    "DIVIDEND_ENTITLEMENT_HISTORY_REQUIRED",
                    "Legacy direct cash dividend path disabled; use ex-date receivable and pay-date settlement",
                )
            elif kind == "delist":
                if not action.get("settlement_verified") or not isfinite(value) or value < 0:
                    raise ValueError("Delisting settlement must be explicit and verified")
                cash = p.quantity * value
                self.cash += cash
                self.actions.append({"date": day, "security_id": sid, "action_type": kind, "cash_change": cash})
                self.trades.append(
                    {
                        "security_id": sid,
                        "entry_time": p.entry_time,
                        "exit_time": str(self.clock.close(day)),
                        "quantity": p.quantity,
                        "net_pnl": cash + p.dividends - p.entry_cash,
                        "holding_sessions": len(
                            self.clock.calendar.sessions_in_range(pd.Timestamp(p.entry_time).date(), day)
                        ),
                        "reason": "VERIFIED_DELIST_SETTLEMENT",
                    }
                )
                del self.positions[sid]
            else:
                raise ValueError("Unsupported corporate action")

    def step(self, day, bars, signals=(), events=()):
        day = str(pd.Timestamp(day).date())
        self.clock.session(day)
        self._validate_session_sequence(day)
        self._actions(day, events, bars)
        open_prices = self._tradable_opens(bars)
        freeze_today = self._should_freeze(open_prices)
        self._execute_pending_orders(day, bars, open_prices, freeze_today)
        opening_exposure = self._record_opening_positions(day, open_prices)
        self._check_stops_and_exits(day, bars)
        self._update_close_prices(bars)
        self._record_equity_curve(day, opening_exposure)
        self._rebalance_risk_limits(day)
        self._accept_new_signals(signals, freeze_today)
        self._validate_cash()
        self.last_date = day

    def _validate_session_sequence(self, day):
        if self.last_date is not None:
            expected = str(self.clock.calendar.next_session(self.last_date).date())
            if day != expected:
                raise ValueError("Portfolio replay must advance exactly one exchange session")

    @staticmethod
    def _tradable_opens(bars):
        return {sid: float(bar["open"]) for sid, bar in bars.items() if bar.get("volume", 0) > 0 and bar["open"] > 0}

    def _should_freeze(self, open_prices):
        freeze_today = any(sid not in open_prices for sid in self.positions) or self.kill_switch_reason is not None
        if freeze_today:
            self.flags.add("UNPRICED_OR_KILLED_PORTFOLIO_NEW_ENTRY_FREEZE")
        return freeze_today

    def _execute_pending_orders(self, day, bars, open_prices, freeze_today):
        pending, self.pending = self.pending, []
        for order in sorted(pending, key=lambda o: 0 if o["side"] == "SELL" else 1):
            sid = order["security_id"]
            if sid in self.blocked_securities:
                continue
            bar = bars.get(sid)
            if bar is None or bar.get("volume", 0) <= 0 or bar["open"] <= 0:
                self.flags.add("MISSING_OR_HALTED_BAR")
                if order["side"] == "SELL":
                    self.pending.append(order)
                else:
                    self.orders.append({**order, "status": "CANCELLED_NO_TRADABLE_OPEN"})
                continue
            open_time = self.clock.calendar.session_open(day).to_pydatetime()
            if order["side"] == "SELL":
                if sid in self.positions:
                    self._sell(sid, order["quantity"], float(bar["open"]), open_time, order["reason"])
                continue
            if freeze_today:
                self.orders.append({**order, "status": "CANCELLED_PORTFOLIO_FREEZE"})
                continue
            if sid in self.positions:
                continue
            if pd.Timestamp(order["signal_time"]) >= pd.Timestamp(open_time):
                raise ValueError("Signal must precede next-session opening fill")
            price, adv, atr = float(bar["open"]), order["adv20"], order["atr20"]
            gross = sum(
                p.quantity * open_prices.get(k, self.last_prices.get(k, p.raw_entry_price))
                for k, p in self.positions.items()
            )
            sector_value = sum(
                p.quantity * open_prices.get(k, self.last_prices.get(k, p.raw_entry_price))
                for k, p in self.positions.items()
                if p.sector == order["sector"]
            )
            equity = self.equity(open_prices)
            if self.benchmark:
                notional = min(order.get("target_weight", 1) * equity, self.cash, self.config.max_participation * adv)
            else:
                notional = allocation_notional(
                    self.config, equity, self.cash, gross, sector_value, price, adv, atr, self.risk_enabled
                )
            buffer = (
                1
                + (
                    self.cost.slippage_bps
                    + self.cost.fee_bps
                    + self.cost.impact_bps_per_full_adv * self.config.max_participation
                )
                / 10000
            )
            quantity = max(0, floor(notional / (price * buffer)))
            if quantity == 0:
                self.orders.append({**order, "status": "REJECTED_RISK_CASH_OR_LIQUIDITY"})
                continue
            fill, fee, cost = self.cost.fill("BUY", price, quantity, adv)
            cash = quantity * fill + fee
            if cash > self.cash + 1e-8:
                raise ValueError("Cash budget violated")
            self.cash -= cash
            self.total_costs += cost
            self.positions[sid] = Position(
                sid,
                order["symbol"],
                order["sector"],
                quantity,
                str(open_time),
                cash,
                price,
                order["exit_date"],
                price - self.config.stop_atr_multiple * atr if self.risk_enabled and not self.benchmark else None,
                adv,
            )
            self.fills.append(
                {
                    "date": day,
                    "security_id": sid,
                    "side": "BUY",
                    "quantity": quantity,
                    "raw_price": price,
                    "fill_price": fill,
                    "fee": fee,
                    "cost": cost,
                    "fill_time": str(open_time),
                    "reason": "NEXT_OPEN",
                    "signal_time": order["signal_time"],
                    "cash_change": -cash,
                }
            )
            self.orders.append({**order, "status": "FILLED_WITH_LIQUIDITY_CASH_CAP", "quantity": quantity})

    def _record_opening_positions(self, day, open_prices):
        open_equity = self.equity(open_prices)
        open_gross = sum(
            p.quantity * open_prices.get(sid, self.last_prices.get(sid, p.raw_entry_price))
            for sid, p in self.positions.items()
        )
        opening_exposure = open_gross / open_equity if open_equity > 0 else 0.0
        for sid, p in self.positions.items():
            price = open_prices.get(sid, self.last_prices.get(sid, p.raw_entry_price))
            self.opening_position_history.append(
                {
                    "date": day,
                    "security_id": sid,
                    "sector": p.sector,
                    "quantity": p.quantity,
                    "mark_price": price,
                    "weight": p.quantity * price / open_equity,
                    "stop": p.stop,
                }
            )
        for sector in {p.sector for p in self.positions.values()}:
            self.exposures.append(
                {
                    "date": day,
                    "sector": sector,
                    "phase": "OPEN",
                    "weight": sum(
                        p.quantity * open_prices.get(sid, self.last_prices.get(sid, p.raw_entry_price))
                        for sid, p in self.positions.items()
                        if p.sector == sector
                    )
                    / open_equity,
                }
            )
        return opening_exposure

    def _check_stops_and_exits(self, day, bars):
        for sid, p in list(self.positions.items()):
            bar = bars.get(sid)
            if bar is None or bar.get("volume", 0) <= 0:
                self.flags.add("STALE_VALUATION_UNRESOLVED_POSITION")
                continue
            trigger, reason = stop_or_target(bar, p.stop)
            if trigger is not None:
                if reason == "STOP_FIRST_UNKNOWN_PATH":
                    self.flags.add("INTRABAR_TIME_UNKNOWN_BOOKED_AT_CLOSE")
                time = (
                    self.clock.calendar.session_open(day).to_pydatetime()
                    if reason == "GAP_STOP"
                    else self.clock.close(day)
                )
                self._sell(sid, p.quantity, trigger, time, reason)
            elif day >= p.exit_date:
                self._sell(
                    sid,
                    p.quantity,
                    float(bar["close"]),
                    self.clock.close(day),
                    "HORIZON_CLOSE" if day == p.exit_date else "DELAYED_EXIT_AFTER_HALT",
                )

    def _update_close_prices(self, bars):
        self.last_prices.update(
            {sid: float(b["close"]) for sid, b in bars.items() if b.get("volume", 0) > 0 and b["close"] > 0}
        )

    def _record_equity_curve(self, day, opening_exposure):
        equity = self.equity()
        gross = sum(p.quantity * self.last_prices.get(sid, p.raw_entry_price) for sid, p in self.positions.items())
        self.curve.append(
            {
                "date": day,
                "cash": self.cash,
                "equity": equity,
                "gross_equity_same_fills": equity + self.total_costs,
                "cumulative_costs": self.total_costs,
                "gross_exposure": gross / equity if equity > 0 else None,
                "opening_gross_exposure": opening_exposure,
                "observed_gross_exposure": max(opening_exposure, gross / equity if equity > 0 else 0),
                "positions": len(self.positions),
            }
        )

    def _rebalance_risk_limits(self, day):
        equity = self.equity()
        targets = {
            sid: min(p.quantity * self.last_prices[sid], self.config.max_stock_weight * equity)
            for sid, p in self.positions.items()
        }
        sectors = {p.sector for p in self.positions.values()}
        for sector in sectors:
            ids = [sid for sid, p in self.positions.items() if p.sector == sector]
            value = sum(targets[sid] for sid in ids)
            cap = self.config.max_sector_weight * equity
            if value > cap and not self.benchmark:
                for sid in ids:
                    targets[sid] *= cap / value
        value = sum(targets.values())
        if value > self.config.max_total_weight * equity and not self.benchmark:
            targets = {sid: v * self.config.max_total_weight * equity / value for sid, v in targets.items()}
        if not self.benchmark:
            for sid, p in self.positions.items():
                keep = floor(targets[sid] / self.last_prices[sid] + 1e-9)
                if keep < p.quantity:
                    self.pending.append(
                        {
                            "side": "SELL",
                            "security_id": sid,
                            "quantity": p.quantity - keep,
                            "reason": "PRIOR_CLOSE_RISK_REBALANCE",
                        }
                    )
                    self.flags.add("MARK_TO_MARKET_LIMIT_DRIFT_NEXT_OPEN_TRIM")
        for sector in sectors:
            self.exposures.append(
                {
                    "date": day,
                    "sector": sector,
                    "phase": "CLOSE",
                    "weight": sum(
                        p.quantity * self.last_prices[sid] for sid, p in self.positions.items() if p.sector == sector
                    )
                    / equity,
                }
            )
        for sid, p in self.positions.items():
            self.position_history.append(
                {
                    "date": day,
                    "security_id": sid,
                    "sector": p.sector,
                    "quantity": p.quantity,
                    "mark_price": self.last_prices[sid],
                    "weight": p.quantity * self.last_prices[sid] / equity,
                    "stop": p.stop,
                }
            )

    def _accept_new_signals(self, signals, freeze_today):
        for signal in signals:
            if freeze_today:
                continue
            sid = signal["security_id"]
            if sid in self.blocked_securities:
                continue
            if sid in self.positions or any(o["security_id"] == sid and o["side"] == "BUY" for o in self.pending):
                continue
            if not signal.get("decision_eligible", False) or signal.get("adjustment_basis", "raw") != "raw":
                raise ValueError("Non-PIT or non-raw research signal cannot create paper order")
            if pd.Timestamp(signal["feature_available_at"]) > pd.Timestamp(signal["signal_time"]):
                raise ValueError("Future feature cannot create order")
            if signal.get("fit_time") is not None and pd.Timestamp(signal["fit_time"]) > pd.Timestamp(
                signal["signal_time"]
            ):
                raise ValueError("Future fitted model cannot create order")
            self.pending.append({**signal, "side": "BUY"})

    def _validate_cash(self):
        if self.cash < -1e-8:
            raise ValueError("Negative cash or leverage not allowed")

    def reconcile(self):
        cash = (
            self.config.initial_cash
            + sum(f["cash_change"] for f in self.fills)
            + sum(a["cash_change"] for a in self.actions)
        )
        # For an incremental persisted replay, global reconciliation is performed by the durable ledger.
        if abs(cash - self.cash) > 1e-6:
            raise ValueError("Cash does not reconcile with fills/actions")
        if self.curve and abs(self.curve[-1]["equity"] - self.equity()) > 1e-6:
            raise ValueError("Equity does not reconcile with positions")
