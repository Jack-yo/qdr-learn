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
    state=readiness_fn(Path(root).resolve(),asof=str(day.date()))
    dataset=(state.get("stages") or {}).get("dataset") or {}
    evidence=dataset.get("evidence") or {}
    if dataset.get("status")!="OBSERVATION_ONLY":
        raise ValueError("REAL_SOURCE_OBSERVATION_NOT_VERIFIED")
    if evidence.get("asof_date_et")!=str(day.date()):
        raise ValueError("REAL_SOURCE_SESSION_MISMATCH")
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
    if (not pd.to_datetime(metadata.date).eq(day).all()
            or not metadata.source_snapshot_sha256.eq(snapshot).all()
            or not pd.to_datetime(metadata.available_at,utc=True).le(signal).all()):
        raise ValueError("CANDIDATE_METADATA_NOT_KNOWN_AS_OF_T")
    factors=frames["factors"]
    if "date" not in factors or "available_at" not in factors:
        raise ValueError("FACTOR_SOURCE_TIMESTAMPS_MISSING")
    at_t=factors.loc[pd.to_datetime(factors.date).eq(day)]
    if at_t.empty or not pd.to_datetime(at_t.available_at,utc=True).le(signal).all():
        raise ValueError("FACTOR_SOURCE_NOT_KNOWN_AS_OF_T")
    states=frames["market_style"]
    if "date" not in states or "state_available_at" not in states:
        raise ValueError("MARKET_STYLE_SOURCE_TIMESTAMPS_MISSING")
    state_t=states.loc[pd.to_datetime(states.date).eq(day)]
    if (len(state_t)!=1
            or not pd.to_datetime(state_t.state_available_at,utc=True).le(signal).all()):
        raise ValueError("MARKET_STYLE_NOT_KNOWN_AS_OF_T")
    return {"status":"PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY",
            "session_date_et":str(day.date()),
            "source_snapshot_sha256":snapshot,
            "checked_candidate_rows":len(metadata),
            "checked_forward_label_rows":len(upcoming),
            "real_orders_enabled":False,
            "historical_pit_attested":False}
