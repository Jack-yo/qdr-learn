"""Forward outcome settlement for immutable L1 V3 research estimates.

Only after the labelled horizon's exchange close+delay. Outcome records are
append-only, separate from frozen estimates; no retroactive edits.
"""
from __future__ import annotations
from hashlib import sha256
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.workflow.l1_v2 import normalize_bars


def _json_bytes(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def settle_due_research(root, bars, *, latest_session, limit=30, action_checker=None):
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
    written, checked, blocked_actions = 0, 0, 0
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
                if action_checker is None:
                    blocked_actions += 1
                    continue
                evidence=action_checker(entry_day,exit_day)
                if not isinstance(evidence,list) or not evidence or any(
                        not isinstance(v,str) or len(v)!=64 or
                        any(ch not in '0123456789abcdef' for ch in v)
                        for v in evidence):
                    blocked_actions += 1
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
                    "source":"ALPACA_RAW_DAILY_PRICES_CURRENT_VINTAGE",
                    "corporate_action_status":"VERIFIED_NO_ACTION_CURRENT_VINTAGE",
                    "corporate_action_receipts_sha256":evidence,
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
            "blocked_action_evidence":blocked_actions}


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
                r.get("corporate_action_status")!="VERIFIED_NO_ACTION_CURRENT_VINTAGE" or
                not r.get("corporate_action_receipts_sha256")):
                continue
            rows.append({k:r[k] for k in
                ("asof_session","horizon","exit_session","actual_scenario",
                 "actual_return","brier_3class","frozen_sha256")})
        except (ValueError,KeyError,TypeError,OSError):
            continue
        if len(rows)>=limit:
            break
    return rows
