"""Fail-closed current-session research cohort contract.

A file hash is not PIT certification. This independent check ensures that the
current H1/H3/H5 candidate cohort is complete and observable by the published
T-day signal; model training remains separately gated by source provenance.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd


_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _session_dates(series, field):
    dates = pd.to_datetime(series, errors="raise")
    if dates.dt.tz is not None or dates.isna().any() or not dates.eq(dates.dt.normalize()).all():
        raise ValueError(f"V4_{field}_SESSION_DATE_INVALID")
    return dates


def _known_by(series, cutoff, field):
    if series.isna().any():
        raise ValueError(f"V4_{field}_AVAILABILITY_MISSING")
    for value in series:
        if pd.Timestamp(value).tzinfo is None:
            raise ValueError(f"V4_{field}_AVAILABILITY_UNZONED")
    timestamps = pd.to_datetime(series, utc=True)
    if not timestamps.le(cutoff).all():
        raise ValueError(f"V4_{field}_ARRIVED_AFTER_SIGNAL")


def layered_current_signal(
    frames: dict, manifest: dict, session, base_signal, entry_time, *,
    now_utc=None
):
    """Return the causal current L3 cutoff after every required input exists."""
    session=pd.Timestamp(session)
    base=pd.Timestamp(base_signal)
    entry=pd.Timestamp(entry_time)
    if (
        session.tzinfo is not None or session!=session.normalize()
        or base.tzinfo is None or entry.tzinfo is None
    ):
        raise ValueError("V4_LAYER_SIGNAL_CLOCK_INVALID")
    names=manifest.get("factor_names")
    if (
        not isinstance(names,list) or not names
        or len(names)!=len(set(names))
    ):
        raise ValueError("V4_FACTOR_REGISTRY_INVALID")

    required=[]
    metadata=frames.get("candidate_meta")
    if not isinstance(metadata,pd.DataFrame) or metadata.empty:
        raise ValueError("V4_CANDIDATE_META_INPUT_CONTRACT_MISSING")
    meta_dates=_session_dates(metadata["date"],"candidate_meta")
    current_meta=metadata.loc[meta_dates.eq(session)]
    if current_meta.empty or "available_at" not in current_meta:
        raise ValueError("V4_CURRENT_CANDIDATE_AVAILABILITY_MISSING")
    required.extend(current_meta.available_at.tolist())

    factors=frames.get("factors")
    if not isinstance(factors,pd.DataFrame) or factors.empty:
        raise ValueError("V4_FACTORS_INPUT_CONTRACT_MISSING")
    factor_dates=_session_dates(factors["date"],"factors")
    current_factors=factors.loc[
        factor_dates.eq(session)&factors.feature_name.isin(names)
    ]
    if current_factors.empty or "available_at" not in current_factors:
        raise ValueError("V4_CURRENT_FACTOR_AVAILABILITY_MISSING")
    required.extend(current_factors.available_at.tolist())

    states=frames.get("market_style")
    if not isinstance(states,pd.DataFrame) or states.empty:
        raise ValueError("V4_MARKET_STYLE_INPUT_CONTRACT_MISSING")
    state_dates=_session_dates(states["date"],"market_style")
    current_state=states.loc[state_dates.eq(session)]
    if len(current_state)!=1 or "state_available_at" not in current_state:
        raise ValueError("V4_CURRENT_MARKET_STYLE_STATE_INVALID")
    required.extend(current_state.state_available_at.tolist())

    times=[]
    for value in required:
        stamp=pd.Timestamp(value)
        if stamp.tzinfo is None:
            raise ValueError("V4_LAYER_INPUT_AVAILABILITY_UNZONED")
        times.append(stamp.tz_convert("UTC"))
    signal=max([base.tz_convert("UTC"),*times])
    if signal>=entry.tz_convert("UTC"):
        raise ValueError("V4_LAYER_SIGNAL_REACHES_NEXT_SESSION_ENTRY")
    if now_utc is not None:
        moment=pd.Timestamp(now_utc)
        if moment.tzinfo is None:
            raise ValueError("V4_LAYER_SIGNAL_NOW_UNZONED")
        if signal>moment.tz_convert("UTC"):
            raise ValueError("V4_LAYER_INPUT_NOT_YET_AVAILABLE")
    return signal


def audit_forward_candidate_cohort(frames: dict, manifest: dict,
                                   session, signal_time) -> dict:
    """Reject silent cohort attrition and labels/inputs that could see T+1."""
    session = pd.Timestamp(session)
    cutoff = pd.Timestamp(signal_time)
    if session.tzinfo is not None or session != session.normalize():
        raise ValueError("V4_COHORT_SESSION_INVALID")
    if cutoff.tzinfo is None:
        raise ValueError("V4_SIGNAL_CUTOFF_MUST_BE_AWARE")
    cutoff = cutoff.tz_convert("UTC")
    names = manifest.get("factor_names")
    if (not isinstance(names, list) or not names or len(names) != len(set(names))
            or any(not isinstance(x, str) or not x.strip() for x in names)):
        raise ValueError("V4_FACTOR_REGISTRY_INVALID")
    digest = manifest.get("source_snapshot_sha256")
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise ValueError("V4_SOURCE_SNAPSHOT_INVALID")
    basket = manifest.get("source_symbols")
    if (not isinstance(basket, list) or not basket or len(basket) != len(set(basket))
            or any(not isinstance(x, str) or not x for x in basket)):
        raise ValueError("V4_SOURCE_BASKET_INVALID")
    needed = {
        "factors": {"date", "security_id", "feature_name", "value",
                    "available_at", "decision_eligible"},
        "labels": {"date", "security_id", "horizon", "label_kind",
                   "available_at", "gross_return", "excess_return"},
        "market_style": {"date", "state_available_at"},
        "candidate_meta": {"date", "security_id", "symbol", "sector",
                           "available_at", "source_snapshot_sha256",
                           "reference_close", "atr20", "adv20"},
    }
    for key, columns in needed.items():
        frame = frames.get(key)
        if not isinstance(frame, pd.DataFrame) or frame.empty or columns - set(frame):
            raise ValueError(f"V4_{key.upper()}_INPUT_CONTRACT_MISSING")
        if (_session_dates(frame["date"], key) > session).any():
            raise ValueError(f"V4_{key.upper()}_FUTURE_SESSION_INPUT")

    metadata = frames["candidate_meta"]
    if (not _session_dates(metadata.date, "candidate_meta").eq(session).all()
            or metadata.security_id.isna().any()
            or metadata.security_id.astype(str).eq("").any()
            or metadata.security_id.duplicated().any()):
        raise ValueError("V4_CURRENT_CANDIDATE_IDENTITIES_INVALID")
    identities = set(metadata.security_id)
    if (not set(metadata.symbol).issubset(set(basket))
            or metadata.symbol.isna().any()
            or metadata.symbol.duplicated().any()):
        raise ValueError("V4_CURRENT_CANDIDATES_OUTSIDE_SOURCE_BASKET")
    if not metadata.source_snapshot_sha256.eq(digest).all():
        raise ValueError("V4_CURRENT_CANDIDATE_SOURCE_CHANGED")
    if metadata.sector.isna().any() or metadata.sector.astype(str).str.upper().isin(
            {"", "UNKNOWN", "UNVERIFIED", "N/A"}).any():
        raise ValueError("V4_CURRENT_CANDIDATE_SECTOR_UNVERIFIED")
    for column in ("reference_close", "atr20", "adv20"):
        values = pd.to_numeric(metadata[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all() or not values.gt(0).all():
            raise ValueError(f"V4_CURRENT_CANDIDATE_{column.upper()}_INVALID")
    _known_by(metadata.available_at, cutoff, "CANDIDATE")

    factors = frames["factors"].copy()
    selected = factors.loc[_session_dates(factors.date, "factors").eq(session)
                           & factors.feature_name.isin(names)].copy()
    expected = {(sid, factor) for sid in identities for factor in names}
    pairs = list(zip(selected.security_id, selected.feature_name))
    if len(pairs) != len(set(pairs)) or set(pairs) != expected:
        raise ValueError("V4_CURRENT_FACTOR_COHORT_INCOMPLETE_OR_DUPLICATE")
    if not selected.decision_eligible.map(
            lambda x: isinstance(x, (bool, np.bool_)) and bool(x)).all():
        raise ValueError("V4_CURRENT_FACTOR_NOT_DECISION_ELIGIBLE")
    numeric = pd.to_numeric(selected.value, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("V4_CURRENT_FACTOR_VALUE_INVALID")
    _known_by(selected.available_at, cutoff, "FACTOR")

    labels = frames["labels"]
    current = labels.loc[_session_dates(labels.date, "labels").eq(session)].copy()
    expected_labels = {(sid, h) for sid in identities for h in (1, 3, 5)}
    label_pairs = list(zip(current.security_id, current.horizon))
    if len(label_pairs) != len(set(label_pairs)) or set(label_pairs) != expected_labels:
        raise ValueError("V4_CURRENT_LABEL_COHORT_INCOMPLETE_OR_DUPLICATE")
    if (not current.label_kind.eq("FUTURE_UNOBSERVED").all()
            or current[["gross_return", "excess_return", "available_at"]].notna().any().any()):
        raise ValueError("V4_CURRENT_LABEL_OUTCOME_LEAKAGE")

    states = frames["market_style"]
    current_state = states.loc[_session_dates(states.date, "market_style").eq(session)]
    if len(current_state) != 1 or states.date.duplicated().any():
        raise ValueError("V4_CURRENT_MARKET_STYLE_STATE_INVALID")
    _known_by(current_state.state_available_at, cutoff, "MARKET_STYLE")
    numeric_conditions = {
        prefix: [col for col in states if col.startswith(prefix)
                 and pd.api.types.is_numeric_dtype(states[col])]
        for prefix in ("market_", "style_")
    }
    for prefix, columns in numeric_conditions.items():
        if not columns or current_state[columns].isna().all(axis=None):
            raise ValueError(f"V4_CURRENT_{prefix.upper()}CONDITIONS_MISSING")
        numbers = current_state[columns].to_numpy(dtype=float)
        if not np.isfinite(numbers).all():
            raise ValueError(f"V4_CURRENT_{prefix.upper()}CONDITIONS_NONFINITE")
    return {
        "status": "CURRENT_COHORT_CONTRACT_VERIFIED_RESEARCH_ONLY",
        "session_date_et": str(session.date()),
        "candidate_count": len(identities),
        "current_factor_rows": len(selected),
        "current_unknown_labels": len(current),
        "source_snapshot_sha256": digest,
        "historical_pit_attested": False,
        "execution_eligible": False,
        "real_orders_enabled": False,
    }
