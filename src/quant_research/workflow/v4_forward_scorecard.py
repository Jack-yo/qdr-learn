"""Read-only prospective H3 research scorecard with strictly causal baselines.

Inputs are hash-verified frozen T-day plans and later raw-price-path outcome
archives. This quantifies prediction error, not broker performance or a
validated alpha. Both return predictions and p_up are scored against the
UNCENSORED T+1 open -> T+H close return, never the stop-censored trade P&L.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
import re

import numpy as np

from quant_research.research.v4_forecast_archive import read_research_forecast
from quant_research.workflow.v4_candidate_bridge import read_indicative_review
from quant_research.workflow.v4_plan_outcomes import read_research_outcomes


_DAY=re.compile(r"\d{4}-\d{2}-\d{2}")
_ID=re.compile(r"[0-9a-f]{16}")


def score_frozen_horizon_records(records: list[dict], *, minimum_sessions: int = 60,
                                 baseline_sessions: int = 20, seed: int = 42) -> dict:
    """Each baseline sees ONLY trades whose outcome horizon ended before T."""
    if (type(minimum_sessions) is not int or not 10<=minimum_sessions<=10000
            or type(baseline_sessions) is not int or not 5<=baseline_sessions<=1000
            or type(seed) is not int or seed<0):
        raise ValueError("FORWARD_SCORECARD_PARAMETERS_INVALID")
    if not isinstance(records,list):
        raise ValueError("FORWARD_SCORECARD_RECORDS_INVALID")
    keyed=set()
    grouped=defaultdict(list)
    for item in records:
        try:
            day=date.fromisoformat(item["session_date_et"])
            exit_day=date.fromisoformat(item["horizon_close_session"])
            sid=str(item["security_id"])
            source=str(item["source_forecast_identity"])
            probability=float(item["p_up"])
            predicted=float(item["predicted_gross_return"])
            realized=float(item["horizon_gross_price_return"])
            modeled_net=float(item["modeled_stop_net_return"])
        except (KeyError,ValueError,TypeError) as exc:
            raise ValueError("FORWARD_SCORECARD_RECORD_INVALID") from exc
        if (exit_day<=day or not sid or not _ID.fullmatch(source)
                or not all(map(math.isfinite,[probability,predicted,realized,modeled_net]))
                or not 0<=probability<=1 or min(predicted,realized,modeled_net)<=-1):
            raise ValueError("FORWARD_SCORECARD_RETURN_OR_TIMING_INVALID")
        key=(day,sid)
        if key in keyed:
            raise ValueError("FORWARD_SCORECARD_DUPLICATE_SESSION_SECURITY")
        keyed.add(key)
        grouped[day].append((exit_day,probability,predicted,realized,modeled_net))
    ordered=sorted(grouped)
    history=[]
    comparable=[]
    daily=[]
    for day in ordered:
        # End < T, not end <= T: H3 outcomes closed after today's decision
        # cannot be available as an unconditional prior on the same date.
        eligible=[x for previous,rows in history if previous<day
                  for x in rows]
        eligible_days=sorted({x[0] for x in eligible})
        last_dates=set(eligible_days[-baseline_sessions:])
        available=[x for x in eligible if x[0] in last_dates]
        reference=None
        if len(eligible_days)>=baseline_sessions:
            positives=sum(value[4]>0 for value in available)
            reference=(positives+1)/(len(available)+2)
        todays=grouped[day]
        model_brier=float(np.mean([(p-float(actual>0))**2
                                  for _,p,_,actual,_ in todays]))
        predicted_mse=float(np.mean([(pred-actual)**2
                                    for _,_,pred,actual,_ in todays]))
        row={"session_date_et":day.isoformat(),"candidate_count":len(todays),
             "model_brier":model_brier,"gross_return_mse":predicted_mse}
        if reference is not None:
            base=float(np.mean([(reference-float(actual>0))**2
                               for _,_,_,actual,_ in todays]))
            row.update({"causal_prior_p_up":reference,"causal_baseline_brier":base,
                        "paired_brier_delta":model_brier-base})
            comparable.append(row)
        daily.append(row)
        # The stored signal T outcome joins history under its ACTUAL H3
        # close session, never the original signal session.
        history.append((day,[(day,exit_day,pred,actual,net)
                             for exit_day,p,pred,actual,net in todays]))
    # Build causal prior correctly from earlier rows only, using the
    # underlying H3 close date and the up indicator. No today/future labels.
    # (The loop above directly computes this for session-level scoring.)
    status=("FORWARD_RESEARCH_SAMPLE_SUFFICIENT_FOR_DIAGNOSTICS_ONLY"
            if len(comparable)>=minimum_sessions
            else "INSUFFICIENT_PROSPECTIVE_RESEARCH_SESSIONS")
    result={"status":status,"sessions_with_outcomes":len(ordered),
            "comparable_sessions":len(comparable),"minimum_sessions":minimum_sessions,
            "baseline_lookback_sessions":baseline_sessions,
            "total_candidate_outcomes":len(records),
            "model_mean_brier":None,"causal_baseline_mean_brier":None,
            "paired_daily_brier_delta":None,"paired_block_bootstrap_95ci":None,
            "gross_return_prediction_mse":None,
            "daily_research_scores":daily[-100:],
            "source_independently_attested":False,
            "broker_fills_observed":False,"paper_ledger_advanced":False,
            "real_orders_enabled":False}
    if not comparable:
        return result
    result["model_mean_brier"]=float(np.mean([r["model_brier"] for r in comparable]))
    result["causal_baseline_mean_brier"]=float(np.mean([
        r["causal_baseline_brier"] for r in comparable]))
    result["paired_daily_brier_delta"]=float(np.mean([
        r["paired_brier_delta"] for r in comparable]))
    result["gross_return_prediction_mse"]=float(np.mean([
        r["gross_return_mse"] for r in comparable]))
    if len(comparable)>=minimum_sessions:
        deltas=np.array([r["paired_brier_delta"] for r in comparable])
        block=min(5,len(deltas))
        generator=np.random.default_rng(seed)
        starts=np.arange(len(deltas))
        samples=[]
        for _ in range(500):
            indexes=np.concatenate([
                (s+np.arange(block))%len(deltas)
                for s in generator.choice(starts,size=math.ceil(len(deltas)/block),
                                          replace=True)])[:len(deltas)]
            samples.append(float(deltas[indexes].mean()))
        lo,hi=np.quantile(samples,[.025,.975])
        result["paired_block_bootstrap_95ci"]=[float(lo),float(hi)]
    return result


def _gather_verified_forward_outcomes(root, *, max_plans=5000):
    root=Path(root).resolve()
    base=root/"outputs/v4_research_outcomes"
    records,skipped=[],defaultdict(int)
    if not base.is_dir():
        return records,dict(skipped)
    keys=[]
    for day in sorted(base.iterdir()):
        if not day.is_dir() or not _DAY.fullmatch(day.name):
            continue
        for folder in sorted(day.iterdir()):
            if folder.is_dir() and _ID.fullmatch(folder.name):
                keys.append((day.name,folder.name))
    if len(keys)>max_plans:
        raise ValueError("FORWARD_SCORECARD_PLAN_LIMIT_EXCEEDED")
    for day,identity in keys:
        try:
            outcome=read_research_outcomes(root,day,identity)
            plan=read_indicative_review(root,day,identity)
            forecast_id=plan["source_forecast_identity"]
            original=read_research_forecast(root,day,forecast_id)
            if (original["manifest"]["prospective_before_next_open"] is not True
                    or original["manifest"]["source_snapshot_sha256"]!=plan["source_snapshot_sha256"]
                    or outcome["status"]!="PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY"):
                skipped["NOT_SOURCE_MATCHED_PROSPECTIVE"]+=1
                continue
            expected={str(x["security_id"]):x for x in plan["plans"]}
            observed={str(x["security_id"]):x for x in outcome["evaluated"]}
            if len(expected)!=len(plan["plans"]) or set(expected)!=set(observed):
                skipped["INCOMPLETE_SECURITY_OUTCOMES"]+=1
                continue
            for sid,entry in expected.items():
                result=observed[sid]
                if "horizon_gross_price_return" not in result:
                    skipped["LEGACY_STOP_CENSORED_ONLY"]+=1
                    continue
                records.append({
                    "session_date_et":day,"security_id":sid,
                    "source_forecast_identity":forecast_id,
                    "horizon_close_session":result["horizon_close_session"],
                    "p_up":entry["probability_up"],
                    "predicted_gross_return":entry["expected_gross_return"],
                    "horizon_gross_price_return":result["horizon_gross_price_return"],
                    "modeled_stop_net_return":result["modeled_net_return"]})
        except (OSError,ValueError,KeyError,TypeError):
            skipped["CORRUPT_OR_MISSING_EVIDENCE"]+=1
    return records,dict(skipped)


def score_prospective_research(root, *, minimum_sessions=60,
                               baseline_sessions=20,max_plans=5000):
    records,skipped=_gather_verified_forward_outcomes(root,max_plans=max_plans)
    report=score_frozen_horizon_records(
        records,minimum_sessions=minimum_sessions,
        baseline_sessions=baseline_sessions)
    report["skipped_reasons"]=skipped
    report["scope"]="PROSPECTIVE_H3_SOURCE_HASHED_RESEARCH_DIAGNOSTICS_NOT_A_BROKER_BACKTEST"
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(
        description="Prospective H3 scored outcomes vs causal prior; research only")
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument("--minimum-sessions",type=int,default=60)
    parser.add_argument("--baseline-sessions",type=int,default=20)
    args=parser.parse_args(argv)
    result=score_prospective_research(
        args.root,minimum_sessions=args.minimum_sessions,
        baseline_sessions=args.baseline_sessions)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result["status"]=="FORWARD_RESEARCH_SAMPLE_SUFFICIENT_FOR_DIAGNOSTICS_ONLY" else 4


if __name__=="__main__":
    raise SystemExit(main())
