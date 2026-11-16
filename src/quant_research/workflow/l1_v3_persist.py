"""Small, verified L1 V3 model bundles. No pickles, warehouse or unverifiable binary.

Each bundle contains seven feature scalers, all three multinomial class logits,
temperature, frozen train/calibration evidence and retrospective OOS metrics.
Model updates are immutable; inference is standard NumPy, not sklearn retraining.
"""
from __future__ import annotations
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import math

import numpy as np

from quant_research.data.l1_light_sources import SourceUnavailable
from quant_research.workflow.l1_probability_v3 import (
    HORIZONS, CLASSES, FEATURES, FEATURE_NAMES, PARAMS,
    _fit_with_calibration, _labels, analyze_l1_v3,
    build_scores, normalize_bars, _market_observations
)

BUNDLE_SCHEMA="qdr.l1.v3.model.v1"
MODEL_FAMILY="LOGISTIC_TEMPERATURE_ETF7"
CORE_SYMBOLS=("SPY","RSP","IWM","HYG","LQD")
RETRAIN_AFTER_SESSIONS=21


def canonical(payload):
    return json.dumps(payload,sort_keys=True,ensure_ascii=False,
                      separators=(",",":"),allow_nan=False).encode("utf-8")


def _stamp(session):
    s=date.fromisoformat(str(session)).isoformat()
    if s!=str(session):
        raise ValueError("Invalid session date")
    return s


def _validated_source_bars(bars, asof):
    """Fail closed on missing/stale core ETF bars or excessive gaps."""
    frame=normalize_bars(bars) if isinstance(bars,dict) else bars.copy()
    frame=frame[frame.date<=str(asof)]
    if frame.empty or frame.duplicated(["date","symbol"]).any():
        raise SourceUnavailable("V3_DUPLICATE_OR_EMPTY_HISTORY")
    symbols=set(frame.symbol)
    if not set(CORE_SYMBOLS)<=symbols:
        raise SourceUnavailable("V3_MISSING_CORE_SYMBOLS")
    if not all(str(frame.loc[frame.symbol.eq(sym),"date"].max())==str(asof)
               for sym in CORE_SYMBOLS):
        raise SourceUnavailable("V3_STALE_CORE_ETF_BAR")
    close=frame.pivot(index="date",columns="symbol",values="close").sort_index()
    if close.index[-1]!=str(asof):
        raise SourceUnavailable("V3_STALE_SPY")
    recent=close[list(CORE_SYMBOLS)].tail(min(80,len(close)))
    if recent.isna().any().any():
        raise SourceUnavailable("V3_CORE_ETF_SESSION_GAPS")
    if len(close)<160:
        raise SourceUnavailable("V3_TOO_FEW_RECENT_SESSIONS")
    return frame


def build_model_bundle(bars, *, receipts, asof):
    """One heavy training job; no binary estimator files."""
    asof=_stamp(asof)
    if not receipts:
        raise SourceUnavailable("V3_SOURCE_RECEIPTS_MISSING")
    frame=_validated_source_bars(bars,asof)
    study=analyze_l1_v3(frame,receipts=receipts,asof_limit=asof)
    if study["asof_session"]!=asof:
        raise SourceUnavailable("V3_TRAINING_ASOF_MISMATCH")
    features,close,open_,_,_=build_scores(frame)
    x=features[list(FEATURE_NAMES)].to_numpy(dtype=float)
    trained={}
    for h in HORIZONS:
        record=study["horizons"][str(h)]
        if record.get("status")!="RESEARCH_ONLY" or not record.get("trace"):
            raise SourceUnavailable("V3_MODEL_NOT_TRAINABLE_H"+str(h))
        y,_,_=_labels(features,open_,close,h)
        scaler,model,temp,prior,n_train,n_cal=_fit_with_calibration(x,y,len(x),h)
        spec={
            "horizon":h,
            "features":list(FEATURE_NAMES),
            "classes":list(CLASSES),
            "scaler_mean":[float(v) for v in scaler.mean_],
            "scaler_scale":[float(v) for v in scaler.scale_],
            "coef":[[float(z) for z in row] for row in model.coef_],
            "intercept":[float(z) for z in model.intercept_],
            "temperature":float(temp),
            "train_samples":int(n_train),
            "calibration_samples":int(n_cal),
            "baseline_probabilities":record["baseline_probabilities"],
            "validation":record["validation"],
            "qualified":False
        }
        trace=infer_saved_model(spec,x[-1])
        original=record["research_estimates"]
        for k in CLASSES:
            if abs(trace["calibrated_probabilities"][k]-original[k])>1e-5:
                raise SourceUnavailable("V3_SAVED_MODEL_REPLAY_MISMATCH")
        trained[str(h)]=spec
    sources=[{k:r.get(k) for k in ("sha256","feed","adjustment","start","end","page")}
             for r in receipts]
    return {
        "schema":BUNDLE_SCHEMA,"status":"RESEARCH_MODEL_ONLY",
        "execution_eligible":False,"historical_pit_verified":False,
        "model_family":MODEL_FAMILY,"model_version":"L1_V3_ETF7.3",
        "minimum_embargo_sessions":5,
        "feature_version":PARAMS["feature_version"],
        "asof_session":asof,
        "training_rows":len(close),
        "input_basis":receipts[-1].get("adjustment","unknown"),
        "feed":receipts[-1].get("feed","unknown"),
        "source_receipts":sources,
        "models":trained
    }


def _validate_spec(spec):
    if (spec.get("features")!=list(FEATURE_NAMES) or
        spec.get("classes")!=list(CLASSES) or
        spec.get("qualified") is not False):
        raise SourceUnavailable("V3_MODEL_CONTRACT_INVALID")
    n=len(FEATURE_NAMES)
    z=np.asarray(spec.get("coef"),dtype=float)
    intercept=np.asarray(spec.get("intercept"),dtype=float)
    mean=np.asarray(spec.get("scaler_mean"),dtype=float)
    scale=np.asarray(spec.get("scaler_scale"),dtype=float)
    t=float(spec.get("temperature",float("nan")))
    if (z.shape!=(3,n) or intercept.shape!=(3,) or
        mean.shape!=(n,) or scale.shape!=(n,) or
        not all(np.all(np.isfinite(v)) for v in (z,intercept,mean,scale)) or
        np.any(scale<=0) or not math.isfinite(t) or not .2<=t<=10):
        raise SourceUnavailable("V3_MODEL_NUMERIC_INVALID")
    return z,intercept,mean,scale,t


def infer_saved_model(spec, raw):
    coef,intercept,mean,scale,temp=_validate_spec(spec)
    x=np.asarray(raw,dtype=float)
    if x.shape!=(len(FEATURE_NAMES),) or not np.isfinite(x).all():
        raise SourceUnavailable("V3_LATEST_FEATURES_INVALID")
    std=(x-mean)/scale
    logits=coef@std+intercept
    def softmax(z):
        y=np.exp(z-z.max())
        return y/y.sum()
    raw_p=softmax(logits)
    final=softmax(logits/temp)
    terms=coef[0]*std
    inputs=[{"key":key,"name":name,
             "raw_value":round(float(x[i]*f),6),"unit":unit,
             "standardized":round(float(std[i]),5),
             "up_logit_contribution":round(float(terms[i]),5)}
            for i,(key,name,unit,f) in enumerate(FEATURES)]
    return {
        "feature_inputs":inputs,
        "up_logit_intercept":round(float(intercept[0]),5),
        "up_logit_sum":round(float(logits[0]),5),
        "class_logits":[round(float(z),5) for z in logits],
        "raw_probabilities":{key:round(float(raw_p[i]),6)
                             for i,key in enumerate(CLASSES)},
        "calibrated_probabilities":{key:round(float(final[i]),6)
                                    for i,key in enumerate(CLASSES)},
        "temperature":round(float(temp),5)
    }


def _validated_bundle(data):
    if (not isinstance(data,dict) or data.get("schema")!=BUNDLE_SCHEMA or
        data.get("status")!="RESEARCH_MODEL_ONLY" or
        data.get("execution_eligible") is not False or
        data.get("historical_pit_verified") is not False or
        data.get("feature_version")!=PARAMS["feature_version"] or
        set(data.get("models",{}))!={"1","3","5"}):
        raise SourceUnavailable("V3_MODEL_BUNDLE_UNQUALIFIED")
    _stamp(data.get("asof_session"))
    for h in HORIZONS:
        item=data["models"][str(h)]
        if item.get("horizon")!=h:
            raise SourceUnavailable("V3_MODEL_HORIZON_INVALID")
        _validate_spec(item)
    return data


def save_model_bundle(root,model):
    data=_validated_bundle(model)
    body=canonical(data)
    digest=sha256(body).hexdigest()
    base=Path(root)/"outputs"/"l1_v3_models"/data["asof_session"]
    base.mkdir(parents=True,exist_ok=True)
    path=base/(digest+".json")
    try:
        with path.open("xb") as f:
            f.write(body)
    except FileExistsError:
        if path.read_bytes()!=body:
            raise SourceUnavailable("V3_MODEL_HASH_CONFLICT")
    return {"model_sha256":digest,"path":str(path.relative_to(Path(root))),
            "asof_session":data["asof_session"]}


def read_model_bundle(path):
    path=Path(path)
    if len(path.stem)!=64 or path.suffix!=".json":
        raise SourceUnavailable("V3_MODEL_PATH_INVALID")
    data=path.read_bytes()
    if sha256(data).hexdigest()!=path.stem:
        raise SourceUnavailable("V3_MODEL_HASH_MISMATCH")
    return _validated_bundle(json.loads(data))


def find_model_bundle(root, *, asof):
    asof=_stamp(asof)
    folder=Path(root)/"outputs"/"l1_v3_models"
    if not folder.is_dir():
        return None
    paths=sorted((p for p in folder.glob("20??-??-??/*.json")
                  if p.parent.name<=asof),reverse=True)
    for path in paths[:40]:
        try:
            model=read_model_bundle(path)
            if model["asof_session"]==path.parent.name and model.get("minimum_embargo_sessions",0)>=5:
                return model,{"model_sha256":path.stem,
                              "path":str(path.relative_to(Path(root))),
                              "asof_session":model["asof_session"]}
        except (OSError,ValueError,TypeError,SourceUnavailable):
            continue
    return None


def should_retrain(model, target_session):
    """Calendar-age upper bound plus per-session age in the caller clock."""
    old=date.fromisoformat(model["asof_session"])
    target=date.fromisoformat(_stamp(target_session))
    return (target-old).days>35


def infer_market_from_bundle(bars, *, model, model_ref, receipts, asof):
    asof=_stamp(asof)
    _validated_bundle(model)
    if asof<model["asof_session"]:
        raise SourceUnavailable("V3_MODEL_FROM_FUTURE")
    frame=_validated_source_bars(bars,asof)
    features,close,open_,high,low=build_scores(frame)
    if close.index[-1]!=asof:
        raise SourceUnavailable("V3_SESSION_MISSING")
    x=features[list(FEATURE_NAMES)].iloc[-1].to_numpy(dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(float(features["rv20"].iloc[-1])):
        raise SourceUnavailable("V3_FEATURES_NOT_READY")
    if model["input_basis"] not in ("split","raw") or any(
            r.get("adjustment")!=model["input_basis"] for r in receipts):
        raise SourceUnavailable("V3_MODEL_PRICE_BASIS_MISMATCH")
    if any(r.get("feed")!=model["feed"] for r in receipts):
        raise SourceUnavailable("V3_MODEL_FEED_MISMATCH")
    study={
        "schema":"qdr.l1.probability.v3","status":"RESEARCH_ONLY",
        "asof_session":asof,"source":"ALPACA_ETF_DAILY",
        "historical_pit_verified":False,"execution_eligible":False,
        "model_name":MODEL_FAMILY,"model_version":model["model_version"],
        "feature_version":model["feature_version"],
        "label_definition":"NEXT_SESSION_OPEN_TO_HORIZON_CLOSE",
        "scenario_boundary_rule":"CLAMP(0.60*RV20*SQRT(H),0.3%,3.5%)",
        "source_scope":"CURRENT_VINTAGE_"+model["input_basis"].upper()+"_ETF_DAILY_NOT_HISTORICAL_PIT",
        "asof_bar_count":len(close),
        "data_feed":model["feed"],
        "fetched_at":receipts[-1].get("fetched_at") if receipts else None,
        "source_receipts":receipts,
        "model_reference":model_ref,
        "minimum_embargo_sessions":model.get("minimum_embargo_sessions",0),
        "outcome_definition":"SPLIT_ADJUSTED_PRICE_RETURN_EXCLUDES_DIVIDENDS",
        "raw_observations":_market_observations(features,close,asof),
        "horizons":{},
        "notice":"Frozen forward research with stored model parameters. Historical PIT and verified trading edge are not established."
    }
    for h in HORIZONS:
        spec=model["models"][str(h)]
        trace=infer_saved_model(spec,x)
        boundary=float(np.clip(.6*features["rv20"].iloc[-1]*math.sqrt(h),.003,.035))
        study["horizons"][str(h)]={
            "horizon":h,"status":"RESEARCH_ONLY",
            "admitted_probabilities":None,
            "research_estimates":trace["calibrated_probabilities"],
            "research_estimate_label":"前向冻结研究估计，尚未获 PIT/正式发布资格",
            "boundary_return":round(boundary,6),
            "train_samples":spec["train_samples"],
            "calibration_samples":spec["calibration_samples"],
            "baseline_probabilities":spec["baseline_probabilities"],
            "trace":trace,"validation":spec["validation"],
            "qualification":{"admitted":False,
               "reasons":["HISTORICAL_PIT_UNVERIFIED","FORWARD_OOS_EVIDENCE_PENDING"],
               "numeric_gates_passed":bool(spec["validation"].get("numeric_gates_passed"))},
            "trace_sha256":sha256(canonical({
                "horizon":h,"model_sha":model_ref["model_sha256"],
                "asof":asof,"trace":trace})).hexdigest()
        }
    return study
