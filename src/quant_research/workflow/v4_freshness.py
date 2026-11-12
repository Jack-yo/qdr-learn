"""Read-only V4 clock and source freshness, without model admission.

Observation currency and forecast eligibility are separate facts. A newly
fetched historical bar cannot be backdated to the post-close decision cutoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from quant_research.clock import TradingClock, utc
from quant_research.policy import SYMBOLS


def _utc_text(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return utc(value).isoformat()


def current_v4_freshness(root: Path, *, now_utc: datetime | None = None) -> dict:
    """Describe the latest completed XNYS session and actual local evidence.

    All timestamps in this contract are UTC-aware. No module becomes CURRENT
    merely because the warehouse contains a row dated for the session.
    """
    moment = utc(now_utc or datetime.now(timezone.utc))
    clock = TradingClock()
    completed = next((s for s in reversed(clock.calendar.sessions)
                      if clock.close(s) <= moment), None)
    if completed is None:
        raise ValueError("No completed XNYS session in configured calendar")
    asof = completed.date().isoformat()
    signal = clock.close(completed) + clock.delay
    common = {"asof_session": asof,
              "knowledge_cutoff_utc": _utc_text(signal),
              "generated_at_utc": _utc_text(moment)}
    database = Path(root) / "data/real_v21.duckdb"
    price_date = arrival = None
    covered = 0
    if database.is_file():
        with duckdb.connect(str(database), read_only=True) as con:
            con.execute("SET TimeZone='UTC'")
            row = con.execute("""SELECT max(date) FROM prices_daily
                WHERE source='ALPACA' AND feed='sip' AND adjustment_basis='raw'
                AND date<=? AND available_at<=?""", [asof, moment]).fetchone()
            price_date = row[0].isoformat() if row and row[0] else None
            if price_date:
                row = con.execute("""SELECT count(DISTINCT symbol), max(available_at)
                    FROM prices_daily WHERE date=? AND source='ALPACA'
                    AND feed='sip' AND adjustment_basis='raw'
                    AND available_at<=? AND symbol IN (SELECT unnest(?))""", [price_date, moment, SYMBOLS]).fetchone()
                covered, arrival = row
    source_status = ("BLOCKED" if price_date is None else
                     "CURRENT" if price_date == asof and covered == len(SYMBOLS) else "STALE")
    source_reason = (None if source_status == "CURRENT" else
                     "NO_ALPACA_SIP_RAW_BARS" if price_date is None else
                     "LATEST_COMPLETED_SESSION_INCOMPLETE_OR_OLDER")
    arrived_by_decision = bool(arrival and utc(arrival) <= signal)
    observation = {**common, "source_data_asof": price_date,
                   "source_available_at_utc": _utc_text(arrival),
                   "known_by_decision_cutoff": arrived_by_decision,
                   "model_version": None, "freshness_status": source_status,
                   "blocked_reason": source_reason,
                   "covered_symbols": covered, "required_symbols": len(SYMBOLS)}
    french_date = french_available = None
    french = Path(root) / "data/managed/classic_factors/factors.duckdb"
    if french.is_file():
        with duckdb.connect(str(french), read_only=True) as con:
            row = con.execute("SELECT max(date), max(available_at) FROM factor_returns WHERE date<=?", [asof]).fetchone()
            if row:
                french_date = row[0].isoformat() if row[0] else None
                french_available = _utc_text(row[1])
    def blocked(reason, source_date=price_date, status="BLOCKED"):
        return {**common, "source_data_asof": source_date,
                "model_version": None, "freshness_status": status,
                "blocked_reason": reason}
    modules = {
        "market_observation": observation,
        "L1_market_prediction": blocked("NO_APPROVED_CURRENT_MARKET_FORECAST" +
                                         ("; PRICE_ARRIVED_AFTER_DECISION_CUTOFF" if not arrived_by_decision else "")),
        "L2_style_prediction": {**blocked("NO_ADMITTED_STYLE_FORECAST; FRENCH_PUBLICATION_LAG",
                                            french_date, "HISTORICAL_ONLY" if french_date else "BLOCKED"),
                                "french_available_at_utc": french_available,
                                "etf_source_data_asof": price_date},
        "L3_alpha_prediction": blocked("NO_PIT_STOCK_UNIVERSE_OR_CURRENT_FROZEN_ALPHA", None),
        "L4_portfolio_risk": blocked("NO_RECONCILED_CURRENT_HOLDINGS_AND_CASH", None),
        "overview": blocked("FOUR_LAYER_BATCH_NOT_ADMITTED"),
    }
    return {"now_utc": _utc_text(moment),
            "now_america_new_york": moment.astimezone(ZoneInfo("America/New_York")).isoformat(),
            "asof_session": asof,
            "knowledge_cutoff_utc": _utc_text(signal),
            "latest_available_price_session": price_date,
            "modules": modules,
            "real_orders_enabled": False}
