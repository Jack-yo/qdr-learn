"""Current-vintage, ETF-only L1 observation adapter.

This module is deliberately separate from the archived L1 research reader.  It
uses the verified source/availability evidence carried by ``load_real_bundle``
to keep the UI populated when no research archive exists, but it never turns a
current revised snapshot into a PIT observation or a forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_research.data.bundle import load_real_bundle
from quant_research.research.l1_features import DOMAINS, REGISTRY


STATUS = "CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION"
_SAFE_FEATURES = ("market_intraday_return", "market_close_location")


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("CURRENT_OBSERVATION_NAIVE_TIMESTAMP")
    return stamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _domain_payload(values: dict[str, float | None], available_at: str | None) -> list[dict[str, Any]]:
    result = []
    for domain, title in DOMAINS.items():
        names = [name for name, item_domain in REGISTRY.items() if item_domain == domain]
        available = [name for name in names if values.get(name) is not None]
        result.append({
            "id": domain,
            "name": title,
            "status": "OBSERVED" if len(available) == len(names) else ("PARTIAL" if available else "MISSING"),
            "value": values.get(available[0]) if available else None,
            "label": available[0] if available else None,
            "unit": "fraction" if available else None,
            "coverage": {"available": len(available), "registered": len(names)},
            "source_available_at": available_at if available else None,
        })
    return result


def build_current_observation(bundle, *, benchmark: str = "SPY", asof: str | None = None) -> dict[str, Any]:
    """Return an ``observations_for_api``-compatible descriptive payload.

    ``bundle`` must be the result of :func:`load_real_bundle`; accepting the
    bundle object also makes source and timestamp checks easy to unit-test.
    The only calculated features are same-session, within-bar measures.  They
    do not require a historical corporate-action adjustment chain.  Every
    other registered feature is returned explicitly as ``MISSING``.
    """
    if not hasattr(bundle, "prices") or not hasattr(bundle, "metadata"):
        raise TypeError("bundle must be a DatasetBundle returned by load_real_bundle")
    prices = bundle.prices
    metadata = bundle.metadata
    if prices.empty:
        raise ValueError("CURRENT_OBSERVATION_NO_REAL_DATA")
    required = {"date", "symbol", "open", "high", "low", "close", "available_at"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"CURRENT_OBSERVATION_SCHEMA_MISSING:{sorted(missing)}")
    dates = pd.to_datetime(prices.date, errors="coerce")
    if dates.isna().any():
        raise ValueError("CURRENT_OBSERVATION_INVALID_DATE")
    latest = dates.max().date().isoformat()
    session = asof or metadata.get("asof_date_et") or latest
    if session != latest:
        raise ValueError("CURRENT_OBSERVATION_ASOF_MISMATCH")
    rows = prices.loc[dates.dt.date.astype(str).eq(session) & prices.symbol.eq(benchmark)].copy()
    if len(rows) != 1:
        raise ValueError("CURRENT_OBSERVATION_BENCHMARK_SESSION_MISSING")
    row = rows.iloc[0]
    numeric = {name: _finite(row[name]) for name in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in numeric.values()):
        raise ValueError("CURRENT_OBSERVATION_INVALID_BENCHMARK_BAR")
    if numeric['high'] < max(numeric['open'], numeric['close'], numeric['low']) or numeric['low'] > min(numeric['open'], numeric['close'], numeric['high']):
        raise ValueError("CURRENT_OBSERVATION_INVALID_BENCHMARK_BAR")

    values: dict[str, float | None] = {name: None for name in REGISTRY}
    values["market_intraday_return"] = _finite(numeric["close"] / numeric["open"] - 1.0)
    bar_range = numeric["high"] - numeric["low"]
    values["market_close_location"] = _finite((numeric["close"] - numeric["low"]) / bar_range) if bar_range > 0 else None
    available_at = _iso(row.available_at)
    source = str(metadata.get("source", row.get("source", "UNKNOWN")))
    source_time = {
        "available_at": available_at,
        "event_time": _iso(row.get("event_time")),
        "knowledge_cutoff_utc": _iso(metadata.get("knowledge_cutoff_utc")),
        "source": source,
        "feed": metadata.get("feed", row.get("feed")),
        "adjustment_basis": row.get("adjustment_basis", metadata.get("adjustment_bases")),
    }
    if not all(source_time[key] for key in ('available_at', 'event_time', 'knowledge_cutoff_utc')):
        raise ValueError('CURRENT_OBSERVATION_MISSING_TIMESTAMP')
    if not pd.Timestamp(source_time['event_time']) <= pd.Timestamp(available_at) <= pd.Timestamp(source_time['knowledge_cutoff_utc']):
        raise ValueError('CURRENT_OBSERVATION_INVALID_TIMING')
    features = []
    for feature, domain in REGISTRY.items():
        value = values[feature]
        observed = value is not None
        features.append({
            "id": feature,
            "domain": domain,
            "status": "OBSERVED" if observed else "MISSING",
            "value": value,
            "source": source if observed else None,
            "available_at": available_at if observed else None,
            "reason": "SAME_SESSION_WITHIN_BAR" if observed else "NOT_AVAILABLE_OR_NOT_SAFE_FOR_RAW_ETF_HISTORY",
            "research_only": True,
        })
    drivers = [{"label": name, "value": values[name], "unit": "fraction", "status": "OBSERVED",
                "delta": None, "oos_increment": None}
               for name in _SAFE_FEATURES if values[name] is not None]
    return {
        "schema": "qdr.l1.market.v1",
        "status": STATUS,
        "asof_session": session,
        "knowledge_cutoff_utc": source_time["knowledge_cutoff_utc"],
        "source_snapshot_sha256": metadata.get("snapshot_sha256"),
        "source_time": source_time,
        "source_version_kind": metadata.get("source_version_kind", "current_revised_snapshot"),
        "model_version": None,
        "domains": _domain_payload(values, available_at),
        "drivers": drivers,
        "features": features,
        "feature_rows": 1,
        "historical_pit_verified": False,
        "current_prediction_eligible": False,
        "forecast_eligible": False,
        "forecast": None,
        "research_archive_available": False,
        "limitations": [
            "CURRENT_VINTAGE_NOT_HISTORICAL_PIT",
            "ETF_PROXY_ONLY_NOT_FULL_MARKET_BREADTH",
            "RAW_ETF_HISTORY_CORPORATE_ACTION_CONTINUITY_NOT_PROVEN",
            "DESCRIPTIVE_OBSERVATION_NOT_FORECAST",
        ],
    }


def current_observation_for_api(database: str | Path, *, source: str = "alpaca",
                                asof: str | None = None, cutoff: datetime | str | None = None,
                                start: str = "2017-01-03", raw_root: str | Path = Path("data/raw"),
                                symbols: list[str] | None = None, benchmark: str = "SPY") -> dict[str, Any]:
    """Load a real bundle and produce the current-vintage observation payload."""
    bundle = load_real_bundle(database, source=source, asof=asof, cutoff=cutoff,
                              start=start, raw_root=Path(raw_root), symbols=symbols)
    return build_current_observation(bundle, benchmark=benchmark, asof=asof)


observations_for_api = current_observation_for_api

