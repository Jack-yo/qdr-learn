"""Forward outcome settlement for immutable L1 V3 research estimates.

Only after the labelled horizon's exchange close+delay. Outcome records are
append-only, separate from frozen estimates; no retroactive edits.
"""
from __future__ import annotations
from hashlib import sha256
from datetime import datetime, timezone, date
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.workflow.l1_v2 import normalize_bars


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


PRICE_BASIS = "SPLIT_ADJUSTED_PRICE_RETURN"
# Price-only outcome: split-adjusted open(T+1) -> close(T+H).
# Dividends, distributions, transaction costs and executable P&L excluded.
# This is exactly the same TARGET as the V3 training labels.


def _receipt_evidence(receipts, *, entry_day, exit_day, asof_feed, due_after):
    """Verify *source provenance*, not an unverifiable corporate-action absence.

    Alpaca historical stock-bars adjustment='split' preserves continuity
    through splits; dividend ex-date price changes remain part of the
    price-only target, NOT total shareholder return. Require a freshly
    fetched, complete adjusted-bar window that includes both target days.
    """
    if not isinstance(receipts,list) or not receipts:
        raise ValueError("V3_SPLIT_BAR_RECEIPTS_MISSING")
    hashes=[]; feed=None; fetched=[]
    for item in receipts:
        if not isinstance(item,dict) or item.get("adjustment")!="split":
            raise ValueError("V3_PRICE_BASIS_NOT_SPLIT")
        f=item.get("feed")
        if f not in ("sip","iex") or (feed is not None and f!=feed):
            raise ValueError("V3_SETTLEMENT_FEED_INVALID")
        feed=f
        digest=item.get("sha256")
        if not isinstance(digest,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):
            raise ValueError("V3_SETTLEMENT_RECEIPT_HASH_INVALID")
        if not (date.fromisoformat(str(item["start"]))<=date.fromisoformat(entry_day) and
                date.fromisoformat(str(item["end"]))>=date.fromisoformat(exit_day)):
            raise ValueError("V3_SETTLEMENT_RECEIPT_WINDOW_INCOMPLETE")
        stamp=datetime.fromisoformat(str(item["fetched_at"]).replace("Z","+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("V3_SETTLEMENT_RECEIPT_TIME_INVALID")
        fetched.append(stamp.astimezone(timezone.utc))
        hashes.append(digest)
    if asof_feed not in ("sip","iex") or asof_feed!=feed:
        raise ValueError("V3_SETTLEMENT_FEED_CHANGED")
    if min(fetched)<due_after.astimezone(timezone.utc):
        raise ValueError("V3_SETTLEMENT_BAR_FETCH_PREMATURE")
    return {"feed":feed,"receipt_sha256":hashes,
            "retrieved_at_utc":max(fetched).isoformat(),
            "adjustment":"split","price_basis":PRICE_BASIS}


def settle_due_research(root, bars, *, latest_session, limit=30,
                        price_receipts=None, action_checker=None):
    root = Path(root)
    home = root / "outputs" / "l1_v3_research"
    if not home.is_dir():
        return {"checked": 0, "new_outcomes": 0}
    clock = TradingClock()
    dates = clock.calendar.sessions
    latest = clock.session(latest_session)
    market = normalize_bars(bars) if isinstance(bars, dict) else bars.copy()
    spy = market.loc[(market.symbol == "SPY") & (market.date <= str(latest_session))]
    spy = spy.set_index("date")
    written, checked, blocked_price_evidence = 0, 0, 0
    for path in sorted(home.glob("20??-??-??/*.json"), reverse=True)[:limit]:
        try:
            body = path.read_bytes()
            if path.stem != sha256(body).hexdigest()[:24]:
                continue  # Reject altered/unverified freeze artifacts.
            frozen_digest = sha256(body).hexdigest()
            payload = json.loads(body)
            if (payload.get("schema") != "qdr.l1.probability.v3" or
                payload.get("historical_pit_verified") is not False or
                payload.get("status") != "RESEARCH_ONLY" or
                payload.get("snapshot_status") != "IMMUTABLE_DAILY_FROZEN"):
                continue
            asof = str(payload["asof_session"])
            session = clock.session(asof)
            position = dates.get_loc(session)
            frozen_at=datetime.fromisoformat(payload["frozen_at_utc"])
            if (frozen_at.tzinfo is None or frozen_at.utcoffset() is None or
                frozen_at.astimezone(timezone.utc)>=clock.calendar.session_open(dates[position+1]).to_pydatetime()):
                continue
            checked += 1
            for key,item in payload.get("horizons",{}).items():
                h = int(key)
                if h not in (1,3,5) or item.get("status") != "RESEARCH_ONLY":
                    continue
                if position+h>dates.get_loc(latest):
                    continue
                entry_day = dates[position+1].date().isoformat()
                exit_day = dates[position+h].date().isoformat()
                if entry_day not in spy.index or exit_day not in spy.index:
                    continue
                # Old research freezes without the H1/H3 five-session
                # embargo are retained but excluded from current forward KPIs.
                if payload.get("minimum_embargo_sessions",0)<5:
                    blocked_price_evidence += 1
                    continue
                frozen_receipts=payload.get("source_receipts") or []
                frozen_feed=payload.get("data_feed")
                if (frozen_feed not in ("sip","iex") or not frozen_receipts or
                    any(not isinstance(r,dict) or
                        r.get("feed")!=frozen_feed or
                        r.get("adjustment")!="split"
                        for r in frozen_receipts)):
                    blocked_price_evidence += 1
                    continue
                due_after=clock.close(dates[position+h])+clock.delay
                try:
                    evidence=_receipt_evidence(price_receipts,
                        entry_day=entry_day,exit_day=exit_day,
                        asof_feed=payload.get("data_feed"),
                        due_after=due_after)
                except (ValueError,TypeError,KeyError,OverflowError):
                    blocked_price_evidence += 1
                    continue
                entry = float(spy.loc[entry_day,"open"])
                exit_ = float(spy.loc[exit_day,"close"])
                boundary = float(item.get("boundary_return",np.nan))
                if not all(map(np.isfinite,(entry,exit_,boundary))) or entry<=0 or boundary<=0:
                    continue
                realized = exit_ / entry - 1
                label = "UP" if realized>boundary else "DOWN" if realized<-boundary else "FLAT"
                p = item.get("research_estimates")
                if not isinstance(p,dict) or set(p)!={"UP","FLAT","DOWN"}:
                    continue
                arr = np.array([float(p[k]) for k in ("UP","FLAT","DOWN")])
                if not np.all(np.isfinite(arr)) or min(arr)<0 or abs(arr.sum()-1)>.002:
                    continue
                truth = np.array([float(k==label) for k in ("UP","FLAT","DOWN")])
                outcome = {
                    "schema":"qdr.l1.v3.outcome.v1",
                    "kind":"RESEARCH_ESTIMATE_SETTLEMENT_NOT_TRADING_PERFORMANCE",
                    "frozen_sha256":frozen_digest,
                    "asof_session":asof,"horizon":h,
                    "entry_session":entry_day,"exit_session":exit_day,
                    "boundary_return":boundary,
                    "actual_return":round(realized,8),
                    "actual_scenario":label,
                    "research_probabilities":p,
                    "brier_3class":round(float(np.square(arr-truth).sum()),8),
                    "source":"ALPACA_SPLIT_ADJUSTED_DAILY_CURRENT_VINTAGE",
                    "price_basis":PRICE_BASIS,
                    "settlement_status":"VERIFIED_SOURCE_PRICE_ONLY_NOT_TOTAL_RETURN",
                    "settlement_receipts_sha256":evidence["receipt_sha256"],
                    "settlement_feed":evidence["feed"],
                    "settlement_adjustment":"split",
                    "settlement_fetched_at_utc":evidence["retrieved_at_utc"],
                    "entry_open_split_adjusted":round(entry,8),
                    "exit_close_split_adjusted":round(exit_,8),
                    "cash_dividends_included":False,
                    "market_execution_pnl_verified":False,
                    "historical_pit_verified":False,
                    "execution_eligible":False
                }
                dest=root/"outputs"/"l1_v3_outcomes"/asof
                dest.mkdir(parents=True,exist_ok=True)
                prefix=outcome["frozen_sha256"][:24]+"_H"+str(h)
                outcome_body=_json_bytes(outcome)
                # First verified outcome wins; never retroactively replace
                # the historical label after a later corporate-action update.
                if list(dest.glob(prefix+"*.json")):
                    continue
                outfile=dest/(prefix+"_"+sha256(outcome_body).hexdigest()[:16]+".json")
                try:
                    with outfile.open("xb") as f:
                        f.write(outcome_body)
                    written+=1
                except FileExistsError:
                    pass
        except (OSError,KeyError,ValueError,TypeError,IndexError,OverflowError):
            continue
    return {"checked":checked,"new_outcomes":written,
            "blocked_price_evidence":blocked_price_evidence,
            "price_basis":PRICE_BASIS}


def recent_v3_outcomes(root,limit=30):
    folder=Path(root)/"outputs"/"l1_v3_outcomes"
    if not folder.exists():
        return []
    rows=[]
    for path in sorted(folder.glob("20??-??-??/*.json"),reverse=True):
        try:
            body=path.read_bytes()
            # Show only forward outcomes with their own immutable digest.
            # Legacy unsealed records remain on disk but cannot masquerade
            # as a verified settlement in the UI.
            suffix=path.stem.rsplit("_",1)[-1]
            if len(suffix)!=16 or sha256(body).hexdigest()[:16]!=suffix:
                continue
            r=json.loads(body)
            if (r.get("schema")!="qdr.l1.v3.outcome.v1" or
                r.get("execution_eligible") is not False or
                r.get("settlement_status")!="VERIFIED_SOURCE_PRICE_ONLY_NOT_TOTAL_RETURN" or
                r.get("price_basis")!=PRICE_BASIS or
                r.get("settlement_adjustment")!="split" or
                not r.get("settlement_receipts_sha256")):
                continue
            rows.append({k:r[k] for k in
                ("asof_session","horizon","exit_session","actual_scenario",
                 "actual_return","brier_3class","frozen_sha256")})
        except (ValueError,KeyError,TypeError,OSError):
            continue
        if len(rows)>=limit:
            break
    return rows
