"""P1 ingestion orchestration, monthly restartable requests and run manifests."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
from uuid import uuid4

import yaml

from quant_research.clock import TradingClock
from quant_research.data.http import HttpCache, atomic_write
from quant_research.data.providers.alpaca import AlpacaProvider
from quant_research.policy import SYMBOLS, require_real_source
from quant_research.data.providers.french import FrenchProvider
from quant_research.data.providers.sec import SECProvider, recent_filings
from quant_research.data.providers.yahoo import YahooProvider
from quant_research.data.quality import audit, write_audit
from quant_research.data.schema import PriceRecord
from quant_research.data.store import Warehouse


def month_ranges(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("Start exceeds end")
    while first <= last:
        following = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        stop = min(last, following - timedelta(days=1))
        yield str(first), str(stop)
        first = stop + timedelta(days=1)


def execute(args):
    if hasattr(args,"source"): require_real_source(args.source)
    run_id, now = str(uuid4()), datetime.now(timezone.utc)
    output = args.output / run_id
    output.mkdir(parents=True, exist_ok=False)
    parameters = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    manifest = {"run_id": run_id, "stage": "P1", "command": args.command,
        "source":getattr(args,'source',None) or {'ingest-sec':'SEC','ingest-french':'FRENCH'}.get(args.command),
        "created_at_utc": now.isoformat(), "asof_timestamp_utc": now.isoformat(), "data_cutoff_utc": now.isoformat(),
        "universe_version": "current-requested-list-not-pit-v1",
        "model_version": "none-p1", "parameters": parameters, "status": "RUNNING", "research_grade": False,
        "config_sha256": hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest(),
        "flags": ["DATA_INCOMPLETE", "NOT_READY"], "inserted_rows": 0}
    package_root = Path(__file__).resolve().parents[1]
    code_digest = hashlib.sha256()
    for file in sorted(package_root.rglob("*.py")):
        code_digest.update(file.relative_to(package_root).as_posix().encode())
        code_digest.update(file.read_bytes())
    manifest["code_sha256"] = code_digest.hexdigest()
    manifest["runtime_versions"] = {name: importlib.metadata.version(name) for name in
                                    ["quant-research", "duckdb", "pyarrow", "exchange-calendars", "yfinance"]}
    sources = yaml.safe_load(args.sources_config.read_text(encoding="utf-8"))
    sec_rate = float(sources["sec"]["requests_per_second_max"])
    alpaca_rate = float(sources["alpaca"]["requests_per_minute_max"])
    if not 0 < sec_rate <= 10 or not 0 < alpaca_rate <= 200:
        raise ValueError("Invalid source rates: SEC <=10/s, default Alpaca tier <=200/min")
    manifest["source_config_sha256"] = hashlib.sha256(args.sources_config.read_bytes()).hexdigest()
    manifest["config_sha256"] = hashlib.sha256(json.dumps({"parameters": parameters, "sources": sources}, sort_keys=True).encode()).hexdigest()
    http = HttpCache(args.data_dir / "raw", offline=args.offline, refresh=args.refresh,
                     intervals={"data.sec.gov": 1 / sec_rate + 0.01, "data.alpaca.markets": 60 / alpaca_rate})
    clock = TradingClock()
    error = None
    with Warehouse(args.db) as store:
        try:
            if args.command == "ingest":
                symbols = args.symbols.split(",")
                if len(set(symbols)) != len(symbols) or not all(symbols):
                    raise ValueError("Symbols must be unique nonempty entries")
                source, feed = {"alpaca": ("ALPACA", args.feed), "yahoo": ("YAHOO", "yahoo")}[args.source]
                if args.source == "yahoo":
                    provider = YahooProvider(clock, args.data_dir / "raw", args.offline, args.refresh)
                    manifest["inserted_actions"] = 0
                    for symbol in symbols:
                        records = provider.bars([symbol], args.start, args.end)
                        manifest["inserted_rows"] += store.put_prices(records, clock)
                        manifest["inserted_actions"] += store.insert_rows("corporate_actions", [r.model_dump() for r in provider.last_actions])
                        print(json.dumps({"progress": symbol, "rows": len(records), "actions": len(provider.last_actions)}), flush=True)
                    if args.repair_gaps and not args.offline:
                        missing = audit(store, clock, symbols, args.start, args.end, source, feed)["gaps"]
                        provider.refresh = True
                        for symbol, days in missing.items():
                            if days:
                                manifest["inserted_rows"] += store.put_prices(provider.bars([symbol], args.start, args.end), clock)
                                manifest["inserted_actions"] += store.insert_rows("corporate_actions", [r.model_dump() for r in provider.last_actions])
                else:
                    provider = AlpacaProvider(clock, http, args.feed)
                    for start, end in month_ranges(args.start, args.end):
                        records = provider.bars(symbols, start, end)
                        manifest["inserted_rows"] += store.put_prices(records, clock)
                    if args.repair_gaps and not args.offline:
                        missing = audit(store, clock, symbols, args.start, args.end, source, feed)["gaps"]
                        http.refresh = True
                        for symbol, days in missing.items():
                            # One bounded retry pass per gap date; no fabricated fills or infinite retries.
                            for day in days:
                                manifest["inserted_rows"] += store.put_prices(provider.bars([symbol], day, day), clock)
                report = audit(store, clock, symbols, args.start, args.end, source, feed)
                write_audit(report, output)
                manifest.update({"status": "INGESTED" if report["coverage_complete"] else "DATA_INCOMPLETE",
                                 "coverage_complete": report["coverage_complete"], "rows": report["rows"],
                                 "raw_execution_prices_available": report["raw_execution_prices_available"],
                                 "flags": report["flags"], "source": source, "feed": feed,
                                 "parquet": str(store.export_prices(args.data_dir / "silver", source, feed))})
            elif args.command == "ingest-french":
                counts = {}
                for dataset in args.datasets.split(","):
                    factors = FrenchProvider(http).factors(dataset)
                    counts[dataset] = len(factors)
                    manifest["inserted_rows"] += store.insert_rows("factor_returns", [r.model_dump() for r in factors])
                manifest.update(status="INGESTED_ATTRIBUTION_ONLY", datasets=counts)
                table = store.db.execute("SELECT * FROM factor_returns ORDER BY date,factor_name,version").fetch_arrow_table()
                import pyarrow.parquet as pq
                path = args.data_dir / "silver" / "french" / f"{run_id}.parquet"
                path.parent.mkdir(parents=True, exist_ok=True)
                pq.write_table(table, path)
                manifest["parquet"] = str(path)
            elif args.command == "ingest-sec":
                snapshots = []
                for cik in args.ciks.split(","):
                    for snapshot in SECProvider(http).snapshots(cik):
                        manifest["inserted_rows"] += store.insert_rows("sec_snapshots", [{k:v for k,v in snapshot.items() if k != "payload"}])
                        if snapshot["kind"] == "submissions":
                            store.insert_rows("filings", recent_filings(snapshot))
                        snapshots.append({"cik": snapshot["cik"], "kind": snapshot["kind"], "sha256": snapshot["raw_sha256"]})
                manifest.update(status="INGESTED_SNAPSHOT_ONLY", snapshots=snapshots)
            elif args.command == "data-audit":
                source, feed = {"alpaca": ("ALPACA", args.feed), "yahoo": ("YAHOO", "yahoo")}[args.source]
                cutoff = clock.signal(args.asof) if args.asof else None
                report = audit(store, clock, args.symbols.split(","), args.start, args.end, source, feed, cutoff)
                write_audit(report, output)
                manifest.update(status="AUDITED", coverage_complete=report["coverage_complete"], rows=report["rows"], flags=report["flags"])
        except Exception as exc:
            # Keep completed pages/months for restart, never call a partial run successful.
            error = exc
            manifest.update(status="FAILED", error_type=type(exc).__name__, error=str(exc) if isinstance(exc, ValueError) else "See source/cache availability; no data fabricated")
        finished = datetime.now(timezone.utc).isoformat()
        manifest["asof_timestamp_utc"] = finished
        manifest["data_cutoff_utc"] = finished
        if args.command == "data-audit" and not error:
            manifest["data_cutoff_utc"] = report["data_cutoff_utc"]
            manifest["asof_timestamp_utc"] = report["data_cutoff_utc"]
        hashes = store.db.execute("""SELECT raw_sha256,cast(available_at AS VARCHAR) FROM price_observations
            UNION SELECT version,cast(available_at AS VARCHAR) FROM factor_returns
            UNION SELECT raw_sha256,cast(available_at AS VARCHAR) FROM sec_snapshots ORDER BY 1,2""").fetchall()
        manifest["data_sha256"] = hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
        manifest["table_counts"] = {t: store.count(t) for t in ["prices_daily", "corporate_actions", "factor_returns", "sec_snapshots", "filings"]}
        store.insert_rows("runs", [{**{k: manifest[k] for k in ["run_id", "created_at_utc", "asof_timestamp_utc", "data_cutoff_utc",
            "universe_version", "model_version", "config_sha256", "data_sha256", "status"]}, "manifest_json": json.dumps(manifest)}])
    atomic_write(output / "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"))
    atomic_write(output / "run.log", f"{now.isoformat()} run_id={run_id} status={manifest['status']}\n".encode())
    print(json.dumps({"run_id": run_id, "status": manifest["status"], "manifest": str((output / "manifest.json").resolve())}))
    return 3 if error else (4 if manifest.get("coverage_complete") is False else 0)
