"""QDR L1 six-system / twelve-dimension data operations.

Examples:
  python -m quant_research.workflow.l1_market_data catalog
  python -m quant_research.workflow.l1_market_data init --root .
  python -m quant_research.workflow.l1_market_data status --root .
  python -m quant_research.workflow.l1_market_data scan-live --root .
  python -m quant_research.workflow.l1_market_data import-bars --root . --input bars.parquet --provider alpaca --price-basis split
  python -m quant_research.workflow.l1_market_data import-universe --root . --input universe.csv --provider alpaca-assets --universe-id CURRENT_ACTIVE --known-at 2026-11-17T22:00:00Z --snapshot-complete
  python -m quant_research.workflow.l1_market_data compute --root . --price-basis split

The store is append-only. Current vendor directories and snapshots are never
promoted to historical point-in-time membership or trading eligibility.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from quant_research.data.l1_market_catalog import catalog_payload
from quant_research.data.l1_market_store import L1MarketStore
from quant_research.workflow.l1_market_ingest import (
    market_data_snapshot, persist_l1_v2, persist_public_scan,
)


def _read(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    if path.suffix.lower() in (".parquet", ".pq"):
        return pd.read_parquet(path)
    raise ValueError("INPUT_MUST_BE_CSV_OR_PARQUET")


def _aware(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return stamp.tz_convert("UTC")


def _bool_series(series, field):
    def parse(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(field + "_MUST_BE_BOOLEAN")
    return series.map(parse)


def _make_cutoffs(bars):
    from quant_research.clock import TradingClock
    clock = TradingClock()
    sessions = sorted(pd.to_datetime(bars.session_date).dt.normalize().drop_duplicates())
    rows = []
    for day in sessions:
        session = clock.session(pd.Timestamp(day).date().isoformat())
        rows.append({"session_date": pd.Timestamp(day),
                     "decision_cutoff_utc": clock.close(session) + clock.delay})
    return pd.DataFrame(rows)


def _register_derived_receipts(store, frames):
    now = datetime.now(timezone.utc)
    receipts = {}
    for frame in frames:
        if frame is None or frame.empty or "receipt_sha256" not in frame:
            continue
        for digest, group in frame.groupby("receipt_sha256", dropna=True):
            digest = str(digest)
            if digest in receipts:
                continue
            available_values = group["available_at"].dropna().tolist() if "available_at" in group else []
            available = max((_aware(x) for x in available_values), default=now)
            receipts[digest] = {
                "provider": "QDR_FEATURE_ENGINE",
                "dataset": "l1_derived_features",
                "fetched_at": now,
                "available_at": available,
                "receipt_sha256": digest,
                "metadata": {"derived_receipt": True,
                    "engine_version": "L1_FEATURES_V1",
                    "record_count": int(len(group)),
                    "raw_provider_body_stored": False},
            }
    for item in receipts.values():
        store.write_receipt(**item)
    return len(receipts)


def _add_import_receipt(store, *, provider, dataset, raw, frame, available_at, metadata):
    digest = sha256(raw).hexdigest()
    dates = frame["session_date"] if "session_date" in frame else frame.get("date")
    store.write_receipt(
        provider=provider, dataset=dataset,
        fetched_at=datetime.now(timezone.utc),
        available_at=available_at,
        receipt_sha256=digest, payload=raw,
        observed_start=dates.min() if dates is not None else None,
        observed_end=dates.max() if dates is not None else None,
        metadata={**metadata, "row_count":len(frame)},
    )
    return digest


def _import_bars(store, args):
    raw = args.input.read_bytes()
    frame = _read(args.input)
    required = {"symbol", "open", "high", "low", "close", "volume"}
    if required - set(frame.columns):
        raise ValueError("BAR_FILE_MISSING_COLUMNS:" + ",".join(sorted(required-set(frame.columns))))
    date_column = "session_date" if "session_date" in frame else "date"
    if date_column not in frame:
        raise ValueError("BAR_FILE_SESSION_DATE_REQUIRED")
    frame = frame.rename(columns={date_column:"session_date"})
    if "security_id" not in frame:
        frame["security_id"] = "SYMBOL:" + frame.symbol.astype(str).str.upper()
    if "available_at" not in frame:
        if not args.available_at:
            raise ValueError("BAR_FILE_AVAILABLE_AT_OR_ARGUMENT_REQUIRED")
        frame["available_at"] = _aware(args.available_at)
    else:
        frame["available_at"] = frame.available_at.map(_aware)
    if "identity_status" not in frame:
        frame["identity_status"] = args.identity_status
    digest = _add_import_receipt(store, provider=args.provider,
        dataset="daily_ohlcv_file", raw=raw, frame=frame,
        available_at=max(frame.available_at),
        metadata={"input_name":args.input.name,"price_basis":args.price_basis,
                  "identity_status":args.identity_status})
    frame["provider"] = args.provider
    frame["price_basis"] = args.price_basis
    frame["receipt_sha256"] = digest
    count = store.write_bars(frame.to_dict("records"))
    return {"status":"IMPORTED","rows":count,"symbols":int(frame.symbol.nunique()),
            "receipt_sha256":digest,"historical_pit_verified":False}


def _import_universe(store, args):
    raw = args.input.read_bytes()
    frame = _read(args.input)
    if "session_date" not in frame and "date" in frame:
        frame = frame.rename(columns={"date":"session_date"})
    if "session_date" not in frame:
        if not args.session_date:
            raise ValueError("UNIVERSE_SESSION_DATE_REQUIRED")
        frame["session_date"] = args.session_date
    required = {"security_id","symbol"}
    if required - set(frame.columns):
        raise ValueError("UNIVERSE_FILE_MISSING_IDENTITY")
    if "is_member" not in frame:
        frame["is_member"] = True
    frame["is_member"] = _bool_series(frame.is_member,"UNIVERSE_MEMBERSHIP")
    if "snapshot_complete" not in frame:
        frame["snapshot_complete"] = bool(args.snapshot_complete)
    else:
        frame["snapshot_complete"] = _bool_series(frame.snapshot_complete,"UNIVERSE_COMPLETENESS")
        if args.snapshot_complete:
            frame["snapshot_complete"] = True
    if "known_at" not in frame:
        if not args.known_at:
            raise ValueError("UNIVERSE_KNOWN_AT_REQUIRED")
        frame["known_at"] = args.known_at
    frame["known_at"] = frame.known_at.map(_aware)
    frame["universe_id"] = args.universe_id
    frame["provider"] = args.provider
    frame["membership_basis"] = args.membership_basis
    frame["pit_status"] = args.pit_status
    digest = _add_import_receipt(store,provider=args.provider,
        dataset="universe_membership_snapshot",raw=raw,frame=frame,
        available_at=max(frame.known_at),
        metadata={"input_name":args.input.name,"universe_id":args.universe_id,
                  "snapshot_complete":bool(frame.snapshot_complete.all()),
                  "pit_status":args.pit_status,"membership_basis":args.membership_basis})
    frame["receipt_sha256"] = digest
    count = store.write_universe(frame.to_dict("records"))
    return {"status":"IMPORTED","rows":count,"universe_id":args.universe_id,
            "snapshot_complete":bool(frame.snapshot_complete.all()),
            "pit_status":args.pit_status,"receipt_sha256":digest}


def _import_events(store, args):
    raw = args.input.read_bytes()
    frame = _read(args.input)
    required = {"event_id","event_type","scheduled_at","schedule_known_at"}
    if required - set(frame.columns):
        raise ValueError("EVENT_FILE_MISSING_COLUMNS:" + ",".join(sorted(required-set(frame.columns))))
    frame["scheduled_at"] = frame.scheduled_at.map(_aware)
    frame["schedule_known_at"] = frame.schedule_known_at.map(_aware)
    if "source" not in frame:
        frame["source"] = args.provider
    if "vintage_id" not in frame:
        frame["vintage_id"] = "IMPORTED:" + args.provider
    digest = _add_import_receipt(store,provider=args.provider,
        dataset="economic_event_calendar",raw=raw,frame=frame,
        available_at=max(frame.schedule_known_at),
        metadata={"input_name":args.input.name})
    frame["receipt_sha256"] = digest
    count = store.write_events(frame.to_dict("records"))
    return {"status":"IMPORTED","rows":count,"receipt_sha256":digest}


def _compute(store, args):
    from quant_research.research.l1_market_features import compute_l1_market_features
    bars = store.read_bars()
    bars = bars.loc[bars.price_basis.eq(args.price_basis)]
    if args.provider:
        bars = bars.loc[bars.provider.eq(args.provider)]
    if bars.empty:
        raise ValueError("NO_BARS_FOR_SELECTED_PRICE_BASIS_AND_PROVIDER")
    if bars.provider.nunique() != 1:
        raise ValueError("MULTIPLE_BAR_PROVIDERS_REQUIRE_PROVIDER_FILTER")
    if bars.symbol.duplicated().any() and bars.duplicated(["session_date","symbol"]).any():
        raise ValueError("DUPLICATE_SYMBOL_BARS_REVIEW_PROVIDER_OR_PRICE_BASIS")
    if not bars.symbol.eq("SPY").any():
        raise ValueError("SPY_BENCHMARK_REQUIRED")
    cutoffs = _read(args.cutoffs) if args.cutoffs else _make_cutoffs(bars)
    if "session_date" not in cutoffs and "date" in cutoffs:
        cutoffs = cutoffs.rename(columns={"date":"session_date"})
    universe = store.read_universe(universe_id=args.universe_id)
    events = store.read_events()
    result = compute_l1_market_features(
        bars,cutoffs,universe=universe,events=events,
        min_breadth_coverage=args.min_breadth_coverage)
    observations=result["observations"]
    security=result["security_features"]
    labels=result["path_labels"]
    derived_receipts=_register_derived_receipts(store,[observations,security,labels])
    observation_count=store.write_observations(observations.to_dict("records"))
    security_count=store.write_security_features(security.to_dict("records"))
    quality_count=store.write_quality_checks(result["breadth_quality"].to_dict("records"))
    label_count=store.write_path_labels(labels.to_dict("records"))
    return {
        "status":"COMPUTED_RESEARCH_ONLY",
        "observations":observation_count,
        "security_features":security_count,
        "breadth_quality_checks":quality_count,
        "path_labels":label_count,
        "derived_receipts":derived_receipts,
        "policy":result["policy"],
        "store_status":store.status(),
    }


def _scan_live(root, refresh=False):
    from quant_research.data.l1_official_sources import scan_official_l1
    from quant_research.data.l1_public_extended import scan_extended_public
    from quant_research.workflow.l1_v2 import current_l1_v2
    from quant_research.data.l1_light_sources import SourceUnavailable

    output={}
    official=scan_official_l1(root,refresh=refresh)
    output["official"]=persist_public_scan(root,official,scan_kind="official")
    extended=scan_extended_public(root,refresh=refresh)
    output["extended"]=persist_public_scan(root,extended,scan_kind="extended")
    try:
        v2=current_l1_v2(root,refresh=refresh)
        output["v2"]=persist_l1_v2(root,v2)
    except (SourceUnavailable,ValueError,OSError,KeyError,TypeError) as exc:
        output["v2"]={"status":"NOT_PERSISTED","code":getattr(exc,"code",type(exc).__name__)}
    output["snapshot"]=market_data_snapshot(root)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="QDR L1 six-system / twelve-dimension market data")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog",help="Print canonical six-system / twelve-dimension registry")
    for name in ("init","status"):
        item=sub.add_parser(name)
        item.add_argument("--root",type=Path,default=Path("."))
        item.add_argument("--db",type=Path)
    bars=sub.add_parser("import-bars",help="Append OHLCV rows and immutable file receipt")
    bars.add_argument("--root",type=Path,default=Path("."))
    bars.add_argument("--db",type=Path)
    bars.add_argument("--input",type=Path,required=True)
    bars.add_argument("--provider",required=True)
    bars.add_argument("--price-basis",choices=("raw","split","dividend","all"),required=True)
    bars.add_argument("--available-at",help="Required only when input has no per-row available_at")
    bars.add_argument("--identity-status",default="SYMBOL_ONLY_UNVERIFIED")
    universe=sub.add_parser("import-universe",help="Append a dated current or historical membership snapshot")
    universe.add_argument("--root",type=Path,default=Path("."))
    universe.add_argument("--db",type=Path)
    universe.add_argument("--input",type=Path,required=True)
    universe.add_argument("--provider",required=True)
    universe.add_argument("--universe-id",required=True)
    universe.add_argument("--known-at",help="Timezone-aware availability time when absent from file")
    universe.add_argument("--session-date",help="Session date when absent from file")
    universe.add_argument("--membership-basis",default="CURRENT_VENDOR_DIRECTORY")
    universe.add_argument("--pit-status",default="CURRENT_SNAPSHOT_ONLY")
    universe.add_argument("--snapshot-complete",action="store_true")
    events=sub.add_parser("import-events",help="Append dated economic event calendar records")
    events.add_argument("--root",type=Path,default=Path("."))
    events.add_argument("--db",type=Path)
    events.add_argument("--input",type=Path,required=True)
    events.add_argument("--provider",required=True)
    compute=sub.add_parser("compute",help="Compute and persist research-only L1 features from stored bars")
    compute.add_argument("--root",type=Path,default=Path("."))
    compute.add_argument("--db",type=Path)
    compute.add_argument("--price-basis",choices=("raw","split"),required=True)
    compute.add_argument("--provider")
    compute.add_argument("--universe-id")
    compute.add_argument("--cutoffs",type=Path,help="Optional CSV/Parquet with session_date and decision_cutoff_utc")
    compute.add_argument("--min-breadth-coverage",type=float,default=0.98)
    live=sub.add_parser("scan-live",help="Fetch and persist current L1 public/credentialed observations")
    live.add_argument("--root",type=Path,default=Path("."))
    live.add_argument("--refresh",action="store_true")
    args=parser.parse_args(argv)

    if args.command=="catalog":
        print(json.dumps(catalog_payload(),ensure_ascii=False,indent=2))
        return 0
    if args.command=="scan-live":
        print(json.dumps(_scan_live(args.root,args.refresh),ensure_ascii=False,default=str))
        return 0
    if args.command=="status":
        print(json.dumps(market_data_snapshot(args.root,asof=None),ensure_ascii=False,default=str))
        return 0
    with L1MarketStore(args.root,db_path=getattr(args,"db",None)) as store:
        if args.command=="init":
            result={"status":"INITIALIZED",**store.status()}
        elif args.command=="import-bars":
            result=_import_bars(store,args)
        elif args.command=="import-universe":
            result=_import_universe(store,args)
        elif args.command=="import-events":
            result=_import_events(store,args)
        elif args.command=="compute":
            if not 0.5<=args.min_breadth_coverage<=1:
                raise ValueError("MIN_BREADTH_COVERAGE_MUST_BE_BETWEEN_0_5_AND_1")
            result=_compute(store,args)
        else:
            raise ValueError("UNKNOWN_L1_MARKET_DATA_COMMAND")
    print(json.dumps(result,ensure_ascii=False,default=str))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
