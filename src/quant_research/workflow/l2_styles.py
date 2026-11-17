"""Read-only L2 ETF style observation workflow using existing verified market data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.research.l2_style_rotation import (
    REQUIRED_SYMBOLS,
    registry_payload,
    style_observations_v1,
)


def calculate(root: Path, *, asof: str | None = None,
              cutoff: datetime | None = None,
              start: str = "2017-01-03",
              source: str = "yahoo") -> dict:
    """Read verified existing prices and calculate observations; never ingests data."""
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
    observations = style_observations_v1(close, available)

    symbol_coverage = []
    for symbol in REQUIRED_SYMBOLS:
        group = prices_long.loc[prices_long.symbol.eq(symbol)]
        latest = group.loc[pd.to_datetime(group.date).eq(pd.Timestamp(end))]
        symbol_coverage.append({
            "symbol": symbol,
            "rows": int(len(group)),
            "first_session": str(pd.to_datetime(group.date).min().date()) if len(group) else None,
            "last_session": str(pd.to_datetime(group.date).max().date()) if len(group) else None,
            "asof_present": bool(len(latest)),
            "available_at": (
                pd.to_datetime(latest.available_at, utc=True).max().isoformat()
                if len(latest) else None
            ),
        })

    latest = observations.loc[
        observations.date.eq(pd.Timestamp(end))
    ].copy()
    latest["observation_status"] = latest.apply(
        lambda row: (
            "OBSERVATION_ONLY"
            if pd.notna(row.relative_return_5d)
            else "BLOCKED_INCOMPLETE_5D_WINDOW"
        ), axis=1
    )
    latest["missing_reason"] = latest.apply(
        lambda row: (
            None if pd.notna(row.relative_return_5d)
            else "MISSING_OR_INCOMPLETE_REQUIRED_PRICE_WINDOW"
        ), axis=1
    )
    series = observations.groupby("style_id", sort=False).tail(126)
    records = lambda frame: json.loads(
        frame.to_json(orient="records", date_format="iso")
    )
    return {
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
            "symbols_with_asof_price": sum(x["asof_present"] for x in symbol_coverage),
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
