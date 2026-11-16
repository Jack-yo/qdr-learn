"""Evidence-linked forward scorecard, never a certified trading hit rate.

Only settles when both original immutable prediction digest and append-only
outcome content hash verify. Outcomes are independent of retrospective folds;
short/overlapping H1/H3/H5 samples must not be called independent observations.
"""
from __future__ import annotations
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path

import numpy as np

SCHEMA="qdr.l1.v3.forward.scorecard.v1"
CLASSES=("UP","FLAT","DOWN")


def _probs(p):
    if not isinstance(p,dict) or set(p)!=set(CLASSES):
        return None
    try:
        out=np.asarray([float(p[x]) for x in CLASSES],dtype=float)
        if not np.isfinite(out).all() or np.any(out<0) or abs(out.sum()-1)>.002:
            return None
        return out/out.sum()
    except (TypeError,ValueError):
        return None


def _ece(prob,actual):
    confidence=prob.max(axis=1)
    correct=(prob.argmax(axis=1)==actual).astype(float)
    score=0.
    for lo in np.linspace(0,1,11)[:-1]:
        flag=(confidence>=lo) & (confidence<(lo+.1) if lo<.9 else confidence<=1)
        if flag.any():
            score+=float(flag.mean())*abs(float(confidence[flag].mean())-float(correct[flag].mean()))
    return float(score)


def forward_scorecard(root, *, max_records=1600, minimum_samples=60):
    base=Path(root)/"outputs"
    folder=base/"l1_v3_outcomes"
    groups=defaultdict(list)
    checked=0
    if folder.is_dir():
        for path in sorted(folder.glob("20??-??-??/*.json"))[-max_records:]:
            checked+=1
            # The outcome suffix is a content checksum; older outcomes with no
            # checksum remain visible in individual history but aren't scored.
            suffix=path.stem.rsplit("_",1)[-1]
            if len(suffix)!=16:
                continue
            try:
                body=path.read_bytes()
                if sha256(body).hexdigest()[:16]!=suffix:
                    continue
                row=json.loads(body)
                if (row.get("schema")!="qdr.l1.v3.outcome.v1" or
                    row.get("historical_pit_verified") is not False or
                    row.get("execution_eligible") is not False or
                    row.get("price_basis")!="SPLIT_ADJUSTED_PRICE_RETURN" or
                    row.get("settlement_status")!="VERIFIED_SOURCE_PRICE_ONLY_NOT_TOTAL_RETURN" or
                    row.get("settlement_adjustment")!="split" or
                    not row.get("settlement_receipts_sha256") or
                    row.get("asof_session")!=path.parent.name or
                    row.get("actual_scenario") not in CLASSES):
                    continue
                h=int(row["horizon"])
                if h not in (1,3,5):
                    continue
                pred=_probs(row.get("research_probabilities"))
                if pred is None:
                    continue
                frozen_digest=row.get("frozen_sha256","")
                if not isinstance(frozen_digest,str) or len(frozen_digest)!=64:
                    continue
                frozen=base/"l1_v3_research"/row["asof_session"]/(frozen_digest[:24]+".json")
                raw=frozen.read_bytes()
                if sha256(raw).hexdigest()!=frozen_digest:
                    continue
                freeze=json.loads(raw)
                if freeze.get("minimum_embargo_sessions",0)<5:
                    continue
                horizon=freeze.get("horizons",{}).get(str(h),{})
                prior=_probs(horizon.get("baseline_probabilities"))
                original=_probs(horizon.get("research_estimates"))
                if (prior is None or original is None or
                    not np.allclose(pred,original,atol=2e-5)):
                    continue
                actual=CLASSES.index(row["actual_scenario"])
                groups[h].append((row["asof_session"],pred,prior,actual))
            except (OSError,ValueError,KeyError,TypeError,OverflowError):
                continue
    horizon_result={}
    for h in (1,3,5):
        data=groups[h]
        if not data:
            horizon_result[str(h)]={"horizon":h,"samples":0,
                                    "status":"NO_VERIFIED_SETTLEMENTS",
                                    "admitted":False}
            continue
        dates=[x[0] for x in data]
        p=np.asarray([x[1] for x in data],dtype=float)
        basep=np.asarray([x[2] for x in data],dtype=float)
        actual=np.asarray([x[3] for x in data],dtype=int)
        truth=np.eye(3)[actual]
        brier=float(np.mean(np.square(p-truth).sum(axis=1)))
        baseline_brier=float(np.mean(np.square(basep-truth).sum(axis=1)))
        logloss=float(-np.mean(np.log(np.clip(p[np.arange(len(actual)),actual],1e-12,1))))
        baseline_loss=float(-np.mean(np.log(np.clip(basep[np.arange(len(actual)),actual],1e-12,1))))
        horizon_result[str(h)]={
            "horizon":h,"samples":len(data),
            "status":"FORWARD_RESEARCH_REPORT_ONLY" if len(data)>=minimum_samples
                     else "FORWARD_SAMPLES_INSUFFICIENT",
            "first_session":min(dates),"last_session":max(dates),
            "brier":round(brier,5),"baseline_brier":round(baseline_brier,5),
            "log_loss":round(logloss,5),
            "baseline_log_loss":round(baseline_loss,5),
            "ece":round(_ece(p,actual),5),
            "brier_vs_baseline":round(brier-baseline_brier,5),
            "numeric_edge_observed":bool(brier<baseline_brier and logloss<baseline_loss),
            "admitted":False,
            "reason":"Historical PIT and statistical independence have not been certified."
        }
    return {"schema":SCHEMA,"status":"RESEARCH_FORWARD_ONLY",
            "minimum_samples_per_horizon":minimum_samples,
            "checked_outcome_files":checked,
            "horizons":horizon_result,
            "historical_pit_verified":False,
            "execution_eligible":False,
            "notice":"Forward sample scores are descriptive, not trade execution evidence."}
