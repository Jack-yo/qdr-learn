"""Read-only source/time admission BEFORE any V4 model or research plan freeze.

Hash and timestamp checks prove input consistency, not PIT eligibility, model
predictive accuracy, or execution approval. Dependency injection is test-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import pandas as pd

_SHA=re.compile(r"[a-f0-9]{64}\Z")


def preflight_v4_day(root: Path, session_date: str, bundle_id: str,
                     *, now_utc: datetime | None=None,
                     checked_inputs=None, readiness_fn=None, clock=None) -> dict:
    """Fail before writes if the T-day source does not match the real warehouse."""
    if checked_inputs is None:
        from quant_research.workflow.v4_study_cli import _checked_inputs
        checked_inputs=_checked_inputs
    if readiness_fn is None:
        from quant_research.workflow.research_readiness import research_readiness
        readiness_fn=research_readiness
    if clock is None:
        from quant_research.clock import TradingClock
        clock=TradingClock()
    moment=pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if moment.tzinfo is None:
        raise ValueError("PREFLIGHT_TIME_MUST_BE_AWARE")
    moment=moment.tz_convert("UTC")
    day=clock.session(session_date)
    window=clock.window(day,1,now=moment.to_pydatetime())
    if not pd.Timestamp(window.signal_time)<=moment<pd.Timestamp(window.entry_time):
        raise ValueError("NOT_IN_T_CLOSE_TO_NEXT_OPEN_WINDOW")
    frames,manifest=checked_inputs(Path(root).resolve(),bundle_id)
    snapshot=manifest.get("source_snapshot_sha256")
    if not isinstance(snapshot,str) or not _SHA.fullmatch(snapshot):
        raise ValueError("SOURCE_BUNDLE_SNAPSHOT_INVALID")
    source_symbols=manifest.get("source_symbols")
    if (not isinstance(source_symbols,list) or not source_symbols
            or any(not isinstance(x,str) or not x.strip() for x in source_symbols)
            or len(set(source_symbols))!=len(source_symbols)):
        raise ValueError("SOURCE_SYMBOL_BASKET_REQUIRED")
    state=readiness_fn(Path(root).resolve(),asof=str(day.date()),
                       symbols=source_symbols)
    dataset=(state.get("stages") or {}).get("dataset") or {}
    evidence=dataset.get("evidence") or {}
    if dataset.get("status")!="OBSERVATION_ONLY":
        raise ValueError("REAL_SOURCE_OBSERVATION_NOT_VERIFIED")
    if evidence.get("asof_date_et")!=str(day.date()):
        raise ValueError("REAL_SOURCE_SESSION_MISMATCH")
    if evidence.get("latest_session_complete") is not True:
        raise ValueError("REAL_SOURCE_LATEST_SESSION_INCOMPLETE")
    if evidence.get("symbols") != source_symbols:
        raise ValueError("SOURCE_BASKET_MISMATCH")
    if evidence.get("source_snapshot_sha256")!=snapshot:
        raise ValueError("BUNDLE_DIFFERS_FROM_LIVE_WAREHOUSE_SNAPSHOT")
    for name in ("factors","labels","market_style","candidate_meta"):
        if name not in frames or not isinstance(frames[name],pd.DataFrame):
            raise ValueError(f"REQUIRED_V4_SOURCE_FRAME_MISSING:{name}")
        if frames[name].empty:
            raise ValueError(f"REQUIRED_V4_SOURCE_FRAME_EMPTY:{name}")
    signal=pd.Timestamp(window.signal_time)
    labels=frames["labels"].copy()
    for field in ("date","horizon","label_kind","gross_return","excess_return",
                  "entry_time","exit_time"):
        if field not in labels:
            raise ValueError(f"LABEL_SCHEMA_INCOMPLETE:{field}")
    days=pd.to_datetime(labels.date,errors="raise")
    if days.dt.tz is not None:
        raise ValueError("LABEL_DATES_REQUIRE_MARKET_SESSION_DAYS")
    upcoming=labels.loc[days.eq(day)].copy()
    if upcoming.empty or set(upcoming.horizon)!={1,3,5}:
        raise ValueError("MISSING_ALL_CURRENT_HORIZON_LABELS")
    if "security_id" not in upcoming or upcoming[["security_id","horizon"]].isna().any().any():
        raise ValueError("CURRENT_LABEL_SECURITY_IDENTITY_MISSING")
    if upcoming.duplicated(["security_id","horizon"]).any():
        raise ValueError("DUPLICATE_CURRENT_SECURITY_HORIZON_LABEL")
    horizon_sets=[set(group.security_id) for _,group in upcoming.groupby("horizon")]
    if not horizon_sets or any(group!=horizon_sets[0] for group in horizon_sets[1:]):
        raise ValueError("HORIZON_SECURITY_UNIVERSE_MISMATCH")
    if (upcoming.gross_return.notna().any()
            or upcoming.excess_return.notna().any()
            or not upcoming.label_kind.eq("FUTURE_UNOBSERVED").all()):
        raise ValueError("FUTURE_LABEL_LEAKAGE")
    for horizon,subset in upcoming.groupby("horizon"):
        expected=clock.window(day,int(horizon),now=moment.to_pydatetime())
        if (not pd.to_datetime(subset.entry_time,utc=True)
                    .eq(pd.Timestamp(expected.entry_time)).all()
                or not pd.to_datetime(subset.exit_time,utc=True)
                    .eq(pd.Timestamp(expected.exit_time)).all()):
            raise ValueError("TRADE_WINDOW_LABEL_MISMATCH")
    metadata=frames["candidate_meta"].copy()
    required={"date","security_id","symbol","sector","reference_close",
              "atr20","adv20","available_at","source_snapshot_sha256"}
    if required-set(metadata):
        raise ValueError("CANDIDATE_METADATA_SCHEMA_INCOMPLETE")
    if metadata.security_id.duplicated().any():
        raise ValueError("CANDIDATE_METADATA_DUPLICATE_IDENTITY")
    if not set(metadata.symbol).issubset(set(source_symbols)):
        raise ValueError("CANDIDATE_NOT_IN_VERIFIED_SOURCE_BASKET")
    if not set(metadata.security_id).issubset(horizon_sets[0]):
        raise ValueError("CANDIDATE_MISSING_FROM_CURRENT_HORIZON_LABELS")
    if (not pd.to_datetime(metadata.date).eq(day).all()
            or not metadata.source_snapshot_sha256.eq(snapshot).all()):
        raise ValueError("CANDIDATE_METADATA_NOT_KNOWN_AS_OF_T")

    factors=frames["factors"]
    if "date" not in factors or "available_at" not in factors:
        raise ValueError("FACTOR_SOURCE_TIMESTAMPS_MISSING")
    at_t=factors.loc[pd.to_datetime(factors.date).eq(day)]
    if at_t.empty:
        raise ValueError("FACTOR_SOURCE_NOT_KNOWN_AS_OF_T")
    factor_times=pd.to_datetime(at_t.available_at,utc=True,errors="coerce")
    if factor_times.isna().any():
        raise ValueError("FACTOR_SOURCE_TIMESTAMPS_MISSING")

    states=frames["market_style"]
    if "date" not in states or "state_available_at" not in states:
        raise ValueError("MARKET_STYLE_SOURCE_TIMESTAMPS_MISSING")
    state_t=states.loc[pd.to_datetime(states.date).eq(day)]
    if len(state_t)!=1:
        raise ValueError("MARKET_STYLE_NOT_KNOWN_AS_OF_T")
    state_times=pd.to_datetime(
        state_t.state_available_at,utc=True,errors="coerce"
    )
    if state_times.isna().any():
        raise ValueError("MARKET_STYLE_SOURCE_TIMESTAMPS_MISSING")

    # L3 is downstream from L1/L2: its causal decision timestamp is the later
    # of the base close+delay signal and the last required factor/state input.
    # It may move later inside the close-to-next-open window, never earlier.
    layer_signal=max(
        signal,
        factor_times.max(),
        state_times.max(),
    )
    if layer_signal>moment:
        raise ValueError("L3_LAYER_INPUT_NOT_YET_AVAILABLE")
    if layer_signal>=pd.Timestamp(window.entry_time):
        raise ValueError("L3_LAYER_SIGNAL_REACHES_NEXT_SESSION_ENTRY")

    metadata_times=pd.to_datetime(
        metadata.available_at,utc=True,errors="coerce"
    )
    if (
        metadata_times.isna().any()
        or not metadata_times.le(layer_signal).all()
    ):
        raise ValueError("CANDIDATE_METADATA_NOT_KNOWN_BY_L3_SIGNAL")
    l2_binding=None
    if manifest.get("l2_style_context_receipt") is not None:
        from quant_research.workflow.l2_l3_binding import (
            verify_l2_style_history_binding)
        l2_binding=verify_l2_style_history_binding(
            Path(root).resolve(),states,manifest["l2_style_context_receipt"],
            clock=clock)
    # Require exact T-day stock/factor/horizon coverage. A verified source
    # hash alone must not hide inner-join attrition or NaN candidate factors.
    from quant_research.workflow.v4_bundle_contract import audit_forward_candidate_cohort
    cohort=audit_forward_candidate_cohort(frames,manifest,day,layer_signal)
    return {"status":"PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY",
            "cohort_contract":cohort,
            "session_date_et":str(day.date()),
            "source_snapshot_sha256":snapshot,
            "source_symbols":source_symbols,
            "checked_candidate_rows":len(metadata),
            "checked_forward_label_rows":len(upcoming),
            "base_signal_time":signal.isoformat(),
            "layer_signal_time":layer_signal.isoformat(),
            "l2_style_binding_verified":bool(
                l2_binding and l2_binding.get("binding_verified") is True),
            "l2_style_historical_pit_attested":bool(
                l2_binding and l2_binding.get("historical_pit_attested") is True),
            "l2_style_binding_context_sha256":(
                l2_binding.get("context_identity_sha256") if l2_binding else None),
            "real_orders_enabled":False,
            "historical_pit_attested":False}
