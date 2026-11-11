"""V4 matured-research-plan settlement sweep.

Safe default is a read-only preview. --freeze-outcomes runs ONLY verified
warehouse H3 price-path research review; never executes or marks paper fills.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.workflow.v4_candidate_bridge import read_indicative_review
from quant_research.workflow.v4_plan_outcomes import read_research_outcomes
from quant_research.workflow.v4_warehouse_outcomes import run_warehouse_outcome_review


_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_ID = re.compile(r"[0-9a-f]{16}")


def sweep_matured_research_plans(root: Path, *, max_plans: int = 100,
                                freeze_outcomes: bool = False,
                                now_utc=None) -> dict:
    if type(max_plans) is not int or not 1<=max_plans<=1000:
        raise ValueError("SETTLEMENT_SWEEP_LIMIT_INVALID")
    now=pd.Timestamp(now_utc if now_utc is not None
                     else datetime.now(timezone.utc))
    if now.tzinfo is None:
        raise ValueError("SETTLEMENT_SWEEP_REQUIRES_AWARE_TIME")
    now=now.tz_convert("UTC")
    clock=TradingClock()
    base=Path(root).resolve()/"outputs/v4_research_plans"
    entries=[]
    if base.is_dir():
        for day in sorted(base.iterdir()):
            if not day.is_dir() or not _DAY.fullmatch(day.name):
                continue
            for folder in sorted(day.iterdir()):
                if folder.is_dir() and _ID.fullmatch(folder.name):
                    entries.append((day.name,folder.name))
    total=len(entries)
    rows=[]
    for day,identity in entries[:max_plans]:
        item={"session_date_et":day,"plan_identity":identity}
        try:
            review=read_indicative_review(root,day,identity)
            if review.get("execution_eligible") is not False or review.get("real_orders_enabled") is not False:
                raise ValueError("RESEARCH_PLAN_TRADING_STATUS_INVALID")
            if not review.get("plans"):
                item["status"]="NO_ACCEPTED_RESEARCH_PLANS"
            else:
                expected=clock.window(day,int(review["horizon"]))
                if now < pd.Timestamp(expected.exit_time)+pd.Timedelta(minutes=15):
                    item["status"]="PENDING_FUTURE_PRICE_WINDOW"
                    item["expected_exit_utc"]=pd.Timestamp(expected.exit_time).isoformat()
                else:
                    try:
                        frozen=read_research_outcomes(root,day,identity)
                    except FileNotFoundError:
                        frozen=None
                    if frozen is not None:
                        item["status"]="ALREADY_FROZEN"
                        item["evaluated_trades"]=len(frozen["evaluated"])
                    elif not freeze_outcomes:
                        item["status"]="READY_TO_TRY_WAREHOUSE_RECEIPTS"
                        item["note"]="Only a readiness preview, source coverage has not been checked"
                    else:
                        result=run_warehouse_outcome_review(
                            root,session_date=day,plan_identity=identity)
                        item["status"]=result["status"]
                        item["evaluated_trades"]=result.get("evaluated_trades",0)
                        if result.get("code"):
                            item["code"]=result["code"]
        except (OSError,ValueError,TypeError,KeyError) as exc:
            item["status"]="BLOCKED_NO_OUTCOME_ARCHIVE_WRITE"
            item["code"]=getattr(exc,"code",None) or str(exc)[:160] or type(exc).__name__
        rows.append(item)
    blocked=sum(x["status"]=="BLOCKED_NO_OUTCOME_ARCHIVE_WRITE" for x in rows)
    return {"status":"READ_ONLY_SETTLEMENT_PREVIEW" if not freeze_outcomes
                else "RESEARCH_OUTCOME_SETTLEMENT_SWEEP_ONLY",
            "checked_at_utc":now.isoformat(),"found_plans":total,
            "checked_plans":len(rows),"truncated":total>len(rows),
            "blocked_plans":blocked,"records":rows,
            "paper_ledger_advanced":False,"broker_fills_observed":False,
            "real_orders_enabled":False}


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Bulk V4 H3 research outcome review; never places or records orders")
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument("--max-plans",type=int,default=100)
    parser.add_argument("--freeze-outcomes",action="store_true",
                        help="Write verified modeled outcome archives, never paper fills")
    args=parser.parse_args(argv)
    result=sweep_matured_research_plans(
        args.root,max_plans=args.max_plans,freeze_outcomes=args.freeze_outcomes)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 4 if result["blocked_plans"] or result["truncated"] else 0


if __name__=="__main__":
    raise SystemExit(main())
