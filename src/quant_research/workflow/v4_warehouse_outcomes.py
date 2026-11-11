"""Build prospective H3 research outcome paths from already archived raw SIP bars.

No price data is fetched or invented. Both the raw bar receipt chain and every
no-corporate-action session receipt must be verified before the model-only
review archive can be written. This is NOT an execution or broker ledger.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.workflow.v4_candidate_bridge import read_indicative_review
from quant_research.workflow.v4_plan_outcomes import (
    evaluate_research_outcomes, freeze_research_outcomes, read_research_outcomes)


_SHA = re.compile(r"[0-9a-f]{64}")


def _no_action_receipt(db, raw_root: Path, row, cutoff: pd.Timestamp) -> str:
    """Only a single complete, authenticated EMPTY action response is accepted."""
    from quant_research.data.capability_checks import _verified_action_receipt

    day = str(pd.Timestamp(row["date"]).date())
    sid, symbol = str(row["security_id"]), str(row["symbol"])
    matches = db.execute(
        """SELECT source,raw_sha256,available_at,quality_flag
           FROM action_coverage_daily WHERE date=? AND security_id=?""",
        [day, sid]).fetchall()
    if len(matches) != 1:
        raise ValueError("OUTCOME_ACTION_RECEIPT_NOT_UNIQUE_OR_MISSING")
    source,digest,available,quality = matches[0]
    when = pd.Timestamp(available)
    flags = str(quality).split("|")
    if (source != "ALPACA" or not isinstance(digest,str)
            or not _SHA.fullmatch(digest) or when.tzinfo is None
            or when > cutoff or "COMPLETE_VERIFIED" not in flags
            or "UNVERIFIED" in flags):
        raise ValueError("OUTCOME_ACTION_COVERAGE_UNVERIFIED")
    if not _verified_action_receipt(raw_root,digest,symbol,day,when):
        raise ValueError("OUTCOME_ACTION_SOURCE_RECEIPT_UNVERIFIED")
    body=json.loads((raw_root/"objects"/digest).read_bytes())
    groups=body.get("corporate_actions")
    if (not isinstance(groups,dict) or not groups
            or body.get("next_page_token")
            or any(not isinstance(items,list) or items for items in groups.values())):
        # Events, even if there is uncertainty about whether they affect a
        # particular security, require a real entitlement/settlement engine.
        raise ValueError("OUTCOME_ACTION_EVENTS_REQUIRE_SETTLEMENT_ENGINE")
    return digest


def assemble_warehouse_outcome_bars(prices: pd.DataFrame, review: dict,
                                   required_sessions, *, cutoff,
                                   action_checker) -> tuple[pd.DataFrame, list]:
    """Pure coverage validator; production injects only source-receipt checks."""
    cutoff=pd.Timestamp(cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("OUTCOME_CUTOFF_UNZONED")
    cutoff=cutoff.tz_convert("UTC")
    plans=review.get("plans")
    if not isinstance(plans,list) or not plans:
        raise ValueError("OUTCOME_REQUIRES_NONEMPTY_FROZEN_PLANS")
    identities={str(p["security_id"]):str(p["symbol"]) for p in plans}
    if (len(identities)!=len(plans) or len(set(identities.values()))!=len(plans)
            or any(not sid or not sym for sid,sym in identities.items())):
        raise ValueError("OUTCOME_PLAN_IDENTITY_AMBIGUOUS")
    expected_dates={pd.Timestamp(x) for x in required_sessions}
    if len(expected_dates)!=len(required_sessions) or not expected_dates:
        raise ValueError("OUTCOME_SESSION_WINDOW_INVALID")
    if not isinstance(prices,pd.DataFrame):
        raise ValueError("OUTCOME_WAREHOUSE_PRICE_FRAME_INVALID")
    fields={"security_id","symbol","date","open","high","low","close",
            "available_at","raw_sha256","source","feed","adjustment_basis"}
    if fields-set(prices):
        raise ValueError("OUTCOME_RAW_PRICE_COLUMNS_MISSING")
    data=prices.copy()
    data["date"]=pd.to_datetime(data.date)
    if data.date.dt.tz is not None or data.date.isna().any():
        raise ValueError("OUTCOME_SESSION_DATE_INVALID")
    expected={(sid,d) for sid in identities for d in expected_dates}
    observed=list(zip(data.security_id.astype(str),data.date))
    if len(observed)!=len(set(observed)) or set(observed)!=expected:
        raise ValueError("OUTCOME_WAREHOUSE_SESSION_COHORT_INCOMPLETE")
    if (not data.apply(lambda r: identities.get(str(r.security_id))==r.symbol,axis=1).all()
            or not data.source.eq("ALPACA").all()
            or not data.feed.eq("sip").all()
            or not data.adjustment_basis.eq("raw").all()
            or not data.raw_sha256.map(lambda x:isinstance(x,str)
                                       and bool(_SHA.fullmatch(x))).all()):
        raise ValueError("OUTCOME_WAREHOUSE_SOURCE_BASIS_OR_IDENTITY_INVALID")
    times=pd.to_datetime(data.available_at,utc=True)
    if times.isna().any() or not times.le(cutoff).all():
        raise ValueError("OUTCOME_RAW_PRICE_NOT_AVAILABLE_AT_REVIEW")
    for col in ("open","high","low","close"):
        data[col]=pd.to_numeric(data[col],errors="coerce")
    if (data[["open","high","low","close"]].isna().any().any()
            or not (data[["open","high","low","close"]]>0).all().all()
            or not (data.high>=data[["open","close","low"]].max(axis=1)).all()
            or not (data.low<=data[["open","close","high"]].min(axis=1)).all()):
        raise ValueError("OUTCOME_RAW_OHLC_ENVELOPE_INVALID")
    records,actions=[],[]
    for _,row in data.sort_values(["date","security_id"]).iterrows():
        receipt=action_checker(row,cutoff)
        if not isinstance(receipt,str) or not _SHA.fullmatch(receipt):
            raise ValueError("OUTCOME_ACTION_RECEIPT_NOT_PROVEN")
        actions.append({"session_date":str(row.date.date()),
                        "security_id":str(row.security_id),
                        "action_receipt_sha256":receipt})
        records.append({"session_date":row.date,
                        "security_id":str(row.security_id),
                        "open":float(row.open),"high":float(row.high),
                        "low":float(row.low),"close":float(row.close),
                        "available_at":row.available_at,
                        "source_sha256":str(row.raw_sha256),
                        "corporate_action_status":"VERIFIED_NO_ACTION"})
    return pd.DataFrame(records),actions


def run_warehouse_outcome_review(root, *, session_date: str, plan_identity: str,
                                db_path: Path | None=None) -> dict:
    """Read-only warehouse -> modeled future path -> immutable research outcome."""
    from quant_research.data.bundle import load_real_bundle
    from quant_research.policy import PolicyError

    root=Path(root).resolve()
    try:
        already=read_research_outcomes(root,session_date,plan_identity)
    except FileNotFoundError:
        already=None
    if already:
        return {"status":"OBSERVED_RESEARCH_OUTCOMES_ALREADY_FROZEN",
                "evaluated_trades":len(already["evaluated"]),
                "session_date_et":session_date,"plan_identity":plan_identity,
                "real_orders_enabled":False,"paper_ledger_advanced":False}
    review=read_indicative_review(root,session_date,plan_identity)
    if not review.get("plans"):
        return {"status":"NO_TRADE_PLAN_TO_EVALUATE","session_date_et":session_date,
                "plan_identity":plan_identity,"real_orders_enabled":False}
    clock=TradingClock()
    window=clock.window(session_date,int(review["horizon"]))
    cutoff=pd.Timestamp.now(tz="UTC")
    if cutoff < pd.Timestamp(window.exit_time)+pd.Timedelta(minutes=15):
        return {"status":"FUTURE_OUTCOME_NOT_YET_OBSERVED",
                "session_date_et":session_date,"plan_identity":plan_identity,
                "real_orders_enabled":False}
    calendar=clock.calendar.sessions
    first_index=calendar.get_loc(clock.session(session_date))+1
    required=calendar[first_index:first_index+int(review["horizon"])]
    expected_symbols=list(dict.fromkeys(str(p["symbol"]) for p in review["plans"]))
    db=(root/"data/real_v21.duckdb" if db_path is None else Path(db_path).resolve())
    if not db.is_relative_to((root/"data").resolve()):
        raise ValueError("OUTCOME_DATABASE_PATH_OUTSIDE_PROJECT_DATA")
    bundle=load_real_bundle(db,source="alpaca",asof=str(required[-1].date()),
        start=str(required[0].date()),symbols=expected_symbols,
        cutoff=cutoff.to_pydatetime(),raw_root=root/"data/raw")
    if (bundle.capabilities.get("observation",{}).get("status")!="PASS"
            or bundle.capabilities.get("raw_prices",{}).get("status")!="PASS"):
        raise ValueError("OUTCOME_WAREHOUSE_RAW_SIP_BASKET_INCOMPLETE")
    import duckdb
    with duckdb.connect(str(db),read_only=True) as connection:
        bars,actions=assemble_warehouse_outcome_bars(
            bundle.prices,review,required,cutoff=cutoff,
            action_checker=lambda row,cutoff:_no_action_receipt(
                connection,root/"data/raw",row,cutoff))
    outcome=evaluate_research_outcomes(root,session_date,plan_identity,bars,
                                      observed_at_utc=cutoff.isoformat())
    if outcome["status"]!="PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY":
        return {"status":outcome["status"],"session_date_et":session_date,
                "plan_identity":plan_identity,"real_orders_enabled":False}
    outcome["warehouse_snapshot_sha256"]=bundle.metadata["snapshot_sha256"]
    outcome["verified_local_action_receipts"]=actions
    outcome["source_independently_attested"]=False
    outcome.pop("content_sha256",None)
    outcome["content_sha256"]=sha256(json.dumps(outcome,sort_keys=True,
        ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    frozen=freeze_research_outcomes(root,outcome)
    return {"status":"OBSERVED_RESEARCH_OUTCOMES_FROZEN_NO_ORDERS",
            "session_date_et":session_date,"plan_identity":plan_identity,
            "evaluated_trades":len(frozen["evaluated"]),
            "content_sha256":frozen["content_sha256"],
            "price_source_snapshot_sha256":bundle.metadata["snapshot_sha256"],
            "source_independently_attested":False,
            "real_orders_enabled":False,"paper_ledger_advanced":False}
