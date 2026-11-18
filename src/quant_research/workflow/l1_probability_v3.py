"""L1 V3: auditable, leakage-controlled *research* scenario estimates.

No synthetic market observations. Raw current-vintage ETF bars are not historical
point-in-time verified; this implementation NEVER admits probabilities as a
certified real-time forecast. It makes every research estimate reproducible:
raw inputs -> train-only scaling -> logits -> held-out temperature -> 3 classes.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
import math

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from quant_research.data.l1_light_sources import SourceUnavailable
from quant_research.workflow.l1_v2 import normalize_bars, build_scores

HORIZONS = (1, 3, 5)
CLASSES = ("UP", "FLAT", "DOWN")
# Exact versioned feature sequence; no ad-hoc external-source merging.
FEATURES = (
    ("spy_return_5", "SPY五日收益", "%", 100.0),
    ("breadth_proxy_rsp_spy_5", "RSP相对SPY五日强度", "%", 100.0),
    ("small_cap_relative_5", "IWM相对SPY五日强度", "%", 100.0),
    ("vol_ratio", "五日/二十日波动比", "倍", 1.0),
    ("credit_proxy_hyg_lqd_5", "HYG相对LQD五日强度", "%", 100.0),
    ("downside_rv20", "二十日下行波动", "%", 100.0),
    ("drawdown20", "二十日回撤", "%", 100.0),
)
FEATURE_NAMES = tuple(f[0] for f in FEATURES)
PARAMS = dict(feature_version="L1_V3_ETF7", train_min=450,
              calibration_days=155, oos_days=260, fold_days=52,
              boundary_vol_multiplier=0.60, min_boundary=0.003,
              max_boundary=0.035)


def _safe_probability(values):
    x = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(x)) or np.any(x < 0) or x.sum() <= 0:
        raise SourceUnavailable("INVALID_MODEL_PROBABILITIES")
    x = x / x.sum()
    if np.any(x > 1):  # impossible unless invalid numeric operation
        raise SourceUnavailable("INVALID_MODEL_PROBABILITIES")
    return x


def _temperature_prob(probs, temperature):
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Invalid calibration temperature")
    x = np.asarray(probs, dtype=float)
    if x.ndim == 1:
        x = x.reshape(1, -1)
    z = np.log(np.clip(x, 1e-12, 1.0)) / float(temperature)
    z -= z.max(axis=1, keepdims=True)
    y = np.exp(z)
    return y / y.sum(axis=1, keepdims=True)


def _logloss(p, target):
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1.0)
    y = np.asarray(target, dtype=int)
    return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def _brier(p, target):
    p = np.asarray(p, dtype=float)
    y = np.eye(3)[np.asarray(target, dtype=int)]
    return float(np.mean(np.square(p - y).sum(axis=1)))


def _ece(p, target):
    """Top-class 10-bin absolute calibration error, not guaranteed uncertainty CI."""
    p = np.asarray(p, dtype=float)
    target = np.asarray(target, dtype=int)
    certainty = p.max(axis=1)
    correct = (p.argmax(axis=1) == target).astype(float)
    total = 0.0
    for low in np.linspace(0, 1, 11)[:-1]:
        high = low + .1
        mask = (certainty >= low) & ((certainty < high) if high < 1 else (certainty <= 1))
        if mask.any():
            total += float(mask.mean()) * abs(float(certainty[mask].mean()) - float(correct[mask].mean()))
    return float(total)


def _train_estimator(x, y):
    if len(x) < PARAMS["train_min"] or set(y) != {0, 1, 2}:
        raise SourceUnavailable("V3_TRAINING_CLASSES_INSUFFICIENT")
    # Require nontrivial class support, otherwise baseline is more honest.
    if np.bincount(y, minlength=3).min() < 20:
        raise SourceUnavailable("V3_RARE_CLASS_INSUFFICIENT")
    scaler = StandardScaler().fit(x)
    model = LogisticRegression(C=0.35, solver="lbfgs", max_iter=400,
                               random_state=0).fit(scaler.transform(x), y)
    if tuple(model.classes_) != (0, 1, 2):
        raise SourceUnavailable("V3_CLASS_ORDER_INVALID")
    return scaler, model


def _labels(features, open_, close, horizon):
    """For signal T after close, label realized T+1 open to T+H close.

    Threshold at T depends only on trailing SPY daily realized vol at T.
    """
    if horizon not in HORIZONS:
        raise ValueError("Invalid horizon")
    spy_open = open_["SPY"].to_numpy(dtype=float)
    spy_close = close["SPY"].to_numpy(dtype=float)
    vol = features["rv20"].to_numpy(dtype=float)
    n = len(features)
    labels = np.full(n, -1, dtype=int)
    returns = np.full(n, np.nan, dtype=float)
    thresholds = np.full(n, np.nan, dtype=float)
    for t in range(n - horizon):
        entry = spy_open[t + 1]
        exit_ = spy_close[t + horizon]
        if not all(map(np.isfinite, (entry, exit_, vol[t]))) or entry <= 0:
            continue
        # The same fixed rule, based only on T's trailing observations.
        boundary = float(np.clip(.60 * vol[t] * math.sqrt(horizon), .003, .035))
        realized = float(exit_ / entry - 1)
        returns[t], thresholds[t] = realized, boundary
        labels[t] = 0 if realized > boundary else 2 if realized < -boundary else 1
    return labels, returns, thresholds


def _valid_indices(x, y, horizon, cutoff, low=0):
    """Labels must finish STRICTLY BEFORE the forecast origin/cutoff."""
    ix = np.arange(max(0, low), cutoff - max(horizon, 5), dtype=int)
    return ix[(y[ix] >= 0) & np.isfinite(x[ix]).all(axis=1)]


def _fit_with_calibration(x, y, origin, h):
    """Training vs calibration split by LABEL AVAILABILITY, never random shuffle."""
    cal_start = origin - PARAMS["calibration_days"]
    train = _valid_indices(x, y, h, cal_start, low=40)
    cal = _valid_indices(x, y, h, origin, low=cal_start)
    if len(train) < PARAMS["train_min"] or len(cal) < 110:
        raise SourceUnavailable("V3_INSUFFICIENT_SPLIT_HISTORY")
    scaler, model = _train_estimator(x[train], y[train])
    raw_cal = model.predict_proba(scaler.transform(x[cal]))
    ys = y[cal]
    candidates = np.linspace(.65, 2.5, 38)
    temperature = float(min(candidates, key=lambda t: _logloss(_temperature_prob(raw_cal, t), ys)))
    # Baseline is never fit on calibration or test targets.
    counts = np.bincount(y[train], minlength=3).astype(float)
    prior = (counts + 1) / (counts.sum() + 3)
    return scaler, model, temperature, prior, len(train), len(cal)


def _oos_validation(x, y, h):
    """Quarterly rolling-origin holdouts, 52 sessions each, no train/test leakage."""
    n = len(y)
    start = max(710, n - PARAMS["oos_days"] - h)
    end = n - h
    pred, baseline, actual, fold_scores = [], [], [], []
    for origin in range(start, end, PARAMS["fold_days"]):
        try:
            scaler, model, temp, prior, _, _ = _fit_with_calibration(x, y, origin, h)
        except SourceUnavailable:
            continue
        idx = np.arange(origin, min(origin + PARAMS["fold_days"], end))
        idx = idx[(y[idx] >= 0) & np.isfinite(x[idx]).all(axis=1)]
        if not len(idx):
            continue
        raw = model.predict_proba(scaler.transform(x[idx]))
        prob = _temperature_prob(raw, temp)
        pred.extend(prob.tolist())
        baseline.extend(np.tile(prior, (len(idx), 1)).tolist())
        actual.extend(y[idx].tolist())
        fold_scores.append({"origin": str(origin), "count": len(idx),
                            "brier_model": round(_brier(prob, y[idx]), 5),
                            "brier_baseline": round(_brier(np.tile(prior, (len(idx), 1)), y[idx]), 5)})
    if len(actual) < 1:
        return {"status": "INSUFFICIENT_OOS", "samples": 0, "qualified": False}
    p = np.asarray(pred, dtype=float)
    b = np.asarray(baseline, dtype=float)
    yv = np.asarray(actual, dtype=int)
    lm, lb = _logloss(p, yv), _logloss(b, yv)
    bm, bb = _brier(p, yv), _brier(b, yv)
    ece = _ece(p, yv)
    positive = sum(z["brier_model"] < z["brier_baseline"] for z in fold_scores)
    pass_gates = (len(actual) >= 200 and len(fold_scores) >= 4 and
                  lm < lb * .99 and bm < bb and ece <= .10 and
                  positive >= 3)
    return {"status": "RETROSPECTIVE_OOS_NOT_PIT_ATTESTED",
            "samples": len(actual), "folds": len(fold_scores),
            "model_log_loss": round(lm, 5), "baseline_log_loss": round(lb, 5),
            "model_brier": round(bm, 5), "baseline_brier": round(bb, 5),
            "ece": round(ece, 5), "positive_folds": positive,
            "numeric_gates_passed": bool(pass_gates), "qualified": False,
            "fold_evidence": fold_scores}


def _model_trace(scaler, model, raw_features, temperature):
    transformed = scaler.transform(raw_features.reshape(1, -1))[0]
    raw_prob = _safe_probability(model.predict_proba(transformed.reshape(1, -1))[0])
    cal_prob = _safe_probability(_temperature_prob(raw_prob, temperature)[0])
    # Coefficients describe UP-class LOGIT, not percentages or causal effects.
    contributions = model.coef_[0] * transformed
    inputs = []
    for j, (key, name, unit, scale) in enumerate(FEATURES):
        inputs.append({
            "key": key, "name": name,
            "raw_value": round(float(raw_features[j] * scale), 6),
            "unit": unit, "standardized": round(float(transformed[j]), 5),
            "up_logit_contribution": round(float(contributions[j]), 5)
        })
    logits = model.decision_function(transformed.reshape(1, -1))[0]
    return {"feature_inputs": inputs,
            "up_logit_intercept": round(float(model.intercept_[0]), 5),
            "up_logit_sum": round(float(contributions.sum() + model.intercept_[0]), 5),
            "class_logits": [round(float(z), 5) for z in logits],
            "raw_probabilities": {k: round(float(raw_prob[i]), 6) for i, k in enumerate(CLASSES)},
            "calibrated_probabilities": {k: round(float(cal_prob[i]), 6) for i, k in enumerate(CLASSES)},
            "temperature": round(float(temperature), 5)}


def _market_observations(features, close, asof):
    """Raw as-of metrics and real rolling time series, no reconstructed external data."""
    definitions = (
        ("SPY", "SPY收盘", "price", "美元", 1.0),
        ("IWM", "IWM收盘", "price", "美元", 1.0),
        ("RSP", "RSP收盘", "price", "美元", 1.0),
        ("HYG", "HYG收盘", "credit", "美元", 1.0),
        ("LQD", "LQD收盘", "credit", "美元", 1.0),
        ("spy_return_5", "SPY五日涨跌", "price", "%", 100.0),
        ("breadth_proxy_rsp_spy_5", "RSP−SPY强弱", "breadth", "百分点", 100.0),
        ("small_cap_relative_5", "IWM−SPY强弱", "breadth", "百分点", 100.0),
        ("rv5", "SPY五日实现波动", "volatility", "%", 100.0),
        ("vol_ratio", "短长波动比", "volatility", "倍", 1.0),
        ("credit_proxy_hyg_lqd_5", "HYG−LQD强弱", "credit", "百分点", 100.0),
        ("drawdown20", "SPY二十日回撤", "price", "%", 100.0),
    )
    result = []
    for key, label, category, unit, factor in definitions:
        series = close[key] if key in close.columns else features[key] if key in features.columns else None
        if series is None:
            continue
        tail = series.dropna().iloc[-20:]
        if len(tail) < 2 or str(tail.index[-1]) != asof:
            continue
        values = (tail.astype(float) * factor).tolist()
        if not all(map(math.isfinite, values)):
            continue
        result.append({"id": key, "label": label, "category": category,
                       "value": round(values[-1], 5),
                       "previous": round(values[-2], 5),
                       "delta": round(values[-1] - values[-2], 5),
                       "unit": unit, "observed_date": asof,
                       "source": "ALPACA_DAILY_ETF_PROXY",
                       "history": [round(v, 5) for v in values]})
    return result


def analyze_l1_v3(bars, *, receipts=None, asof_limit=None):
    """Entirely data-driven; returns no admitted live forecast, even if gates pass."""
    frame = normalize_bars(bars) if isinstance(bars, dict) else bars.copy()
    if asof_limit is not None:
        frame = frame[frame["date"] <= str(asof_limit)]
    features, close, open_, high, _ = build_scores(frame)
    n = len(close)
    if n < 900:
        raise SourceUnavailable("V3_NEEDS_LONGER_DAILY_HISTORY")
    if close["SPY"].notna().mean() < .995:
        raise SourceUnavailable("V3_SPY_HISTORY_INCOMPLETE")
    if any(k not in features.columns for k in FEATURE_NAMES):
        raise SourceUnavailable("V3_REQUIRED_FEATURE_MISSING")
    x = features[list(FEATURE_NAMES)].to_numpy(dtype=float)
    if not np.isfinite(x[-1]).all():
        raise SourceUnavailable("V3_LATEST_FEATURES_MISSING")
    asof = str(close.index[-1])
    output = {
        "schema": "qdr.l1.probability.v3", "status": "RESEARCH_ONLY",
        "asof_session": asof, "source": "ALPACA_ETF_DAILY",
        "historical_pit_verified": False, "execution_eligible": False,
        "model_name": "MULTINOMIAL_LOGISTIC_TEMPERATURE",
        "model_version": "L1_V3_ETF7.1",
        "feature_version": PARAMS["feature_version"],
        "label_definition": "NEXT_SESSION_OPEN_TO_HORIZON_CLOSE",
        "scenario_boundary_rule": "CLAMP(0.60*RV20*SQRT(H),0.3%,3.5%)",
        "source_scope": "CURRENT_VINTAGE_RAW_UNADJUSTED_ETF_DAILY_NOT_HISTORICAL_PIT",
        "asof_bar_count": n,
        "source_receipts": receipts or [],
        "raw_observations": _market_observations(features, close, asof),
        "horizons": {},
        "notice": "Historical current-vintage research estimates only; NEVER certified live predictive probabilities."
    }
    for h in HORIZONS:
        target, realized, threshold = _labels(features, open_, close, h)
        evidence = _oos_validation(x, target, h)
        try:
            scaler, model, temperature, prior, n_train, n_cal = _fit_with_calibration(x, target, n, h)
            details = _model_trace(scaler, model, x[-1], temperature)
            p = details["calibrated_probabilities"]
            cutoff = float(np.clip(.60 * features["rv20"].iloc[-1] * math.sqrt(h), .003, .035))
            training_fingerprint = sha256(json.dumps({
                "asof": asof, "horizon": h, "features": list(FEATURE_NAMES),
                "trace": details, "train": n_train, "cal": n_cal
            }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            output["horizons"][str(h)] = {
                "horizon": h, "status": "RESEARCH_ONLY",
                "admitted_probabilities": None, "research_estimates": p,
                "research_estimate_label": "未通过完整历史PIT与前向发布资格",
                "boundary_return": round(cutoff, 6),
                "train_samples": n_train, "calibration_samples": n_cal,
                "baseline_probabilities": {k: round(float(prior[i]), 6)
                                            for i, k in enumerate(CLASSES)},
                "trace": details, "validation": evidence,
                "qualification": {
                    "admitted": False,
                    "reasons": (["HISTORICAL_PIT_UNVERIFIED"] +
                                ([] if evidence.get("numeric_gates_passed") else ["OOS_NUMERIC_GATES_NOT_PASSED"])),
                    "numeric_gates_passed": bool(evidence.get("numeric_gates_passed"))
                },
                "trace_sha256": training_fingerprint
            }
        except (SourceUnavailable, ValueError, FloatingPointError) as exc:
            output["horizons"][str(h)] = {
                "horizon": h, "status": "INSUFFICIENT_RESEARCH_HISTORY",
                "admitted_probabilities": None, "research_estimates": None,
                "reason": getattr(exc, "code", type(exc).__name__),
                "validation": evidence,
                "qualification": {"admitted": False,
                                  "reasons": ["MODEL_DATA_NOT_READY"]}
            }
    return output
