"""Read-only L2 ETF style observation workflow using existing verified market data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.research.l2_rotation import (
    ROTATION_PROTOCOL_VERSION, rotation_states_v1,
)
from quant_research.research.l2_style_rotation import (
    REQUIRED_SYMBOLS,
    registry_payload,
    style_observations_v1,
)


def load_observation_frame(root: Path, *, asof: str | None = None,
                           cutoff: datetime | None = None,
                           start: str = "2017-01-03",
                           source: str = "yahoo"):
    """Return the full causal P1 observation frame and read-only source evidence."""
    root = Path(root)
    if source.lower() != "yahoo":
        raise ValueError("L2_V1_REQUIRES_SPLIT_ADJUSTED_YAHOO_PRICE_BASIS")
    bundle = load_real_bundle(
        root / "data/research.duckdb",
        source=source,
        asof=asof,
        cutoff=cutoff,
        start=start,
        symbols=list(REQUIRED_SYMBOLS),
        raw_root=root / "data/raw",
    )
    metadata = bundle.metadata
    prices_long = bundle.prices
    if set(prices_long.adjustment_basis) != {"yahoo_split_adjusted"}:
        raise ValueError("L2_PRICE_BASIS_NOT_SPLIT_ADJUSTED")
    if prices_long.duplicated(["date", "symbol"]).any():
        raise ValueError("L2_DUPLICATE_SYMBOL_SESSION")
    end = metadata["asof_date_et"]
    sessions = TradingClock().calendar.sessions_in_range(start, end)
    close = prices_long.pivot(index="date", columns="symbol", values="close")
    available = prices_long.pivot(index="date", columns="symbol", values="available_at")
    close.index = pd.to_datetime(close.index)
    available.index = pd.to_datetime(available.index)
    close = close.reindex(index=sessions, columns=REQUIRED_SYMBOLS)
    available = available.reindex(index=sessions, columns=REQUIRED_SYMBOLS)
    available = available.apply(pd.to_datetime, utc=True, errors="coerce")
    cutoff_timestamp = pd.Timestamp(metadata["knowledge_cutoff_utc"])
    if cutoff_timestamp.tzinfo is None:
        raise ValueError("L2_REQUIRES_TIMEZONE_AWARE_CUTOFF")
    cutoff_timestamp = cutoff_timestamp.tz_convert("UTC")
    eligible = available.notna() & available.le(cutoff_timestamp)
    close = close.where(eligible)
    available = available.where(eligible)
    observations = style_observations_v1(close, available)
    return observations, prices_long, metadata, sessions, cutoff_timestamp


def calculate(root: Path, *, asof: str | None = None,
              cutoff: datetime | None = None,
              start: str = "2017-01-03",
              source: str = "yahoo",
              include_rotation: bool = False) -> dict:
    """Read verified existing prices and calculate observations; never ingests data."""
    root = Path(root)
    observations, prices_long, metadata, sessions, cutoff_timestamp = load_observation_frame(
        root, asof=asof, cutoff=cutoff, start=start, source=source
    )
    end = metadata["asof_date_et"]

    symbol_coverage = []
    for symbol in REQUIRED_SYMBOLS:
        group = prices_long.loc[prices_long.symbol.eq(symbol)]
        latest = group.loc[pd.to_datetime(group.date).eq(pd.Timestamp(end))]
        at_cutoff = bool(
            len(latest) and pd.to_datetime(
                latest.available_at, utc=True, errors="coerce"
            ).notna().all() and pd.to_datetime(
                latest.available_at, utc=True, errors="coerce"
            ).le(cutoff_timestamp).all()
        )
        symbol_coverage.append({
            "symbol": symbol,
            "rows": int(len(group)),
            "first_session": str(pd.to_datetime(group.date).min().date()) if len(group) else None,
            "last_session": str(pd.to_datetime(group.date).max().date()) if len(group) else None,
            "asof_present": bool(len(latest)),
            "asof_available_by_cutoff": at_cutoff,
            "available_at": (
                pd.to_datetime(latest.available_at, utc=True).max().isoformat()
                if len(latest) else None
            ),
        })

    latest = observations.loc[
        observations.date.eq(pd.Timestamp(end))
    ].copy()
    def window_status(row):
        if pd.isna(row.relative_return_5d):
            return "BLOCKED_INCOMPLETE_5D_WINDOW", "MISSING_OR_INCOMPLETE_REQUIRED_PRICE_WINDOW"
        if pd.isna(row.relative_return_20d):
            return "PARTIAL_INCOMPLETE_20D_WINDOW", "MISSING_OR_INCOMPLETE_20D_WINDOW"
        if pd.isna(row.relative_return_60d) or pd.isna(row.available_at):
            return "PARTIAL_INCOMPLETE_60D_WINDOW", "MISSING_OR_INCOMPLETE_60D_WINDOW"
        return "OBSERVATION_ONLY", None

    statuses = latest.apply(window_status, axis=1)
    latest["observation_status"] = statuses.map(lambda x: x[0])
    latest["missing_reason"] = statuses.map(lambda x: x[1])
    series = observations.groupby("style_id", sort=False).tail(126)
    records = lambda frame: json.loads(
        frame.to_json(orient="records", date_format="iso")
    )
    payload = {
        **registry_payload(),
        "status": "OBSERVATION_ONLY",
        "asof_session": end,
        "signal_cutoff_utc": metadata["knowledge_cutoff_utc"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": metadata["source"],
        "feed": metadata["feed"],
        "price_basis": "yahoo_split_adjusted",
        "source_snapshot_sha256": metadata["snapshot_sha256"],
        "historical_decision_eligible": False,
        "real_orders_enabled": False,
        "coverage": {
            "required_symbols": len(REQUIRED_SYMBOLS),
            "symbols_with_asof_price": sum(x["asof_available_by_cutoff"] for x in symbol_coverage),
            "symbols": symbol_coverage,
            "exchange_sessions": len(sessions),
        },
        "latest": records(latest),
        "series": records(series),
        "limitations": [
            "ETF_PROXY_NOT_HISTORICAL_CONSTITUENT_PIT",
            "CURRENT_VINTAGE_SPLIT_ADJUSTED_PRICE_NOT_TOTAL_RETURN",
            "OBSERVATION_ONLY_NO_FORECAST",
            "NO_DATA_INGESTION_OR_WAREHOUSE_MUTATION",
        ],
    }
    if include_rotation:
        rotation = rotation_states_v1(
            observations, cutoff_utc=metadata["knowledge_cutoff_utc"]
        )
        current = rotation.loc[rotation.date.eq(end)]
        recent = rotation.groupby("style_id", sort=False).tail(126)
        transitions = rotation.loc[rotation.transitioned_on_session].tail(50)
        payload["rotation"] = {
            "schema": "qdr.l2.rotation.v1",
            "protocol_version": ROTATION_PROTOCOL_VERSION,
            "status": "OBSERVATION_ONLY",
            "asof_session": end,
            "latest": records(current),
            "history": records(recent),
            "transitions": records(transitions),
            "styles_with_known_state": int(current.rotation_state.ne("UNKNOWN").sum()),
            "styles_unknown": int(current.rotation_state.eq("UNKNOWN").sum()),
            "history_scope": "CURRENT_VINTAGE_RESEARCH_ONLY_NOT_HISTORICAL_PIT",
            "forecast_available": False,
            "real_orders_enabled": False,
        }
    return payload


def calculate_rotation(root: Path, *, asof: str | None = None,
                       cutoff: datetime | None = None,
                       start: str = "2017-01-03") -> dict:
    """Expose P2 only, based on the same read-only P1 source snapshot."""
    overview = calculate(
        root, asof=asof, cutoff=cutoff, start=start, include_rotation=True
    )
    return {
        "source": overview["source"],
        "price_basis": overview["price_basis"],
        "source_snapshot_sha256": overview["source_snapshot_sha256"],
        "signal_cutoff_utc": overview["signal_cutoff_utc"],
        "asof_session": overview["asof_session"],
        "registry_version": overview["registry_version"],
        "historical_decision_eligible": False,
        "real_orders_enabled": False,
        "coverage": overview["coverage"],
        "limitations": overview["limitations"],
        **overview["rotation"],
    }
