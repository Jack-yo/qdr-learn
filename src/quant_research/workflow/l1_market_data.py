"""QDR L1 market-data catalogue and local store operations.

Examples:
  python -m quant_research.workflow.l1_market_data catalog
  python -m quant_research.workflow.l1_market_data init --root .
  python -m quant_research.workflow.l1_market_data status --root .
  python -m quant_research.workflow.l1_market_data import-bars --root . --input bars.parquet --provider alpaca --price-basis raw --available-at 2026-11-17T22:00:00Z

Importing a file records its exact bytes and requires an explicit provider
availability timestamp. A file hash proves byte identity, not vendor authenticity
or PIT eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from quant_research.data.l1_market_catalog import catalog_payload, coverage_matrix
from quant_research.data.l1_market_store import L1MarketStore


def _read(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(path)
    raise ValueError("INPUT_MUST_BE_CSV_OR_PARQUET")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="QDR L1 six-system / twelve-dimension market data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog", help="Print the canonical six-system and twelve-dimension registry")
    for name in ("init", "status"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, default=Path("."))
        item.add_argument("--db", type=Path)
    bars = sub.add_parser("import-bars", help="Append actual OHLCV rows with immutable input receipt")
    bars.add_argument("--root", type=Path, default=Path("."))
    bars.add_argument("--db", type=Path)
    bars.add_argument("--input", type=Path, required=True)
    bars.add_argument("--provider", required=True)
    bars.add_argument("--price-basis", choices=("raw", "split", "dividend", "all"), required=True)
    bars.add_argument("--available-at", required=True, help="Actual timezone-aware source availability time")
    bars.add_argument("--identity-status", default="SYMBOL_ONLY_UNVERIFIED")
    args = parser.parse_args(argv)

    if args.command == "catalog":
        print(json.dumps(catalog_payload(), ensure_ascii=False, indent=2))
        return 0

    with L1MarketStore(args.root, db_path=getattr(args, "db", None)) as store:
        if args.command == "init":
            print(json.dumps({"status": "INITIALIZED", **store.status()}, ensure_ascii=False))
            return 0
        if args.command == "status":
            status = store.status()
            observations = store.read_observations()
            rows = observations.to_dict("records") if not observations.empty else []
            print(json.dumps({**status, "coverage": coverage_matrix(rows)},
                             ensure_ascii=False, default=str))
            return 0
        if args.command == "import-bars":
            available_at = datetime.fromisoformat(args.available_at.replace("Z", "+00:00"))
            if available_at.tzinfo is None or available_at.utcoffset() is None:
                raise ValueError("AVAILABLE_AT_MUST_HAVE_TIMEZONE")
            raw = args.input.read_bytes()
            digest = sha256(raw).hexdigest()
            frame = _read(args.input)
            required = {"symbol", "open", "high", "low", "close", "volume"}
            if required - set(frame.columns):
                raise ValueError("BAR_FILE_MISSING_COLUMNS:" + ",".join(sorted(required-set(frame.columns))))
            date_column = "session_date" if "session_date" in frame else "date"
            if date_column not in frame:
                raise ValueError("BAR_FILE_SESSION_DATE_REQUIRED")
            if "security_id" not in frame:
                frame["security_id"] = "SYMBOL:" + frame.symbol.astype(str).str.upper()
            if "available_at" not in frame:
                frame["available_at"] = available_at.isoformat()
            if "identity_status" not in frame:
                frame["identity_status"] = args.identity_status
            store.write_receipt(provider=args.provider, dataset="daily_ohlcv_file",
                fetched_at=datetime.now(timezone.utc), available_at=available_at,
                receipt_sha256=digest, observed_start=frame[date_column].min(),
                observed_end=frame[date_column].max(), payload=raw,
                metadata={"input_name": args.input.name, "price_basis": args.price_basis,
                          "row_count": len(frame), "identity_status": args.identity_status})
            frame = frame.rename(columns={date_column: "session_date"})
            frame["provider"] = args.provider
            frame["price_basis"] = args.price_basis
            frame["receipt_sha256"] = digest
            count = store.write_bars(frame.to_dict("records"))
            print(json.dumps({"status": "IMPORTED", "rows": count,
                "symbols": int(frame.symbol.nunique()), "receipt_sha256": digest,
                "historical_pit_verified": False, "forecast_eligible": False},
                ensure_ascii=False))
            return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
