"""Read-only, reproducible inventory of local DuckDB research stores.

Writes aggregate metadata only; never exports rows, credentials, or vendor data.
"""

from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DATABASES = (
    "data/real_v21.duckdb",
    "data/research.duckdb",
    "data/g3_evidence.duckdb",
    "data/managed/classic_factors/factors.duckdb",
    "data/managed/corporate_actions/events.duckdb",
)
DATE_NAMES = ("session_date", "trade_date", "date", "asof_date", "observed_at_utc", "timestamp", "created_at_utc")
SYMBOL_NAMES = ("symbol", "ticker", "asset_symbol")


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def audit_database(relative_path: str) -> dict:
    path = ROOT / relative_path
    result: dict = {"path": relative_path, "exists": path.exists(), "tables": []}
    if not path.exists():
        return result
    result["bytes"] = path.stat().st_size
    result["modified_utc"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    try:
        con = duckdb.connect(str(path), read_only=True)
        tables = con.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('information_schema', 'pg_catalog') ORDER BY 1, 2").fetchall()
        for schema, table in tables:
            full = f"{quote(schema)}.{quote(table)}"
            columns = con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=? AND table_name=? ORDER BY ordinal_position", [schema, table]).fetchall()
            names = [row[0] for row in columns]
            entry: dict = {"table": f"{schema}.{table}", "columns": dict(columns)}
            try:
                entry["rows"] = con.execute(f"SELECT count(*) FROM {full}").fetchone()[0]
                symbol = next((name for name in SYMBOL_NAMES if name in names), None)
                if symbol:
                    entry["securities"] = con.execute(f"SELECT count(DISTINCT {quote(symbol)}) FROM {full}").fetchone()[0]
                date_column = next((name for name in DATE_NAMES if name in names), None)
                if date_column:
                    low, high = con.execute(f"SELECT min({quote(date_column)}), max({quote(date_column)}) FROM {full}").fetchone()
                    entry["date_column"] = date_column
                    entry["first"] = str(low) if low is not None else None
                    entry["last"] = str(high) if high is not None else None
                entry["null_counts"] = {name: con.execute(f"SELECT count(*) FROM {full} WHERE {quote(name)} IS NULL").fetchone()[0] for name in names if name in ("symbol", "session_date", "trade_date", "date", "open", "high", "low", "close", "volume", "source", "raw_sha256")}
                key_date = next((name for name in ("session_date", "trade_date", "date") if name in names), None)
                if symbol and key_date:
                    entry["duplicate_symbol_date_rows"] = con.execute(f"SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM {full} GROUP BY {quote(symbol)}, {quote(key_date)} HAVING count(*)>1)").fetchone()[0]
                if {"open", "high", "low", "close"}.issubset(names):
                    entry["ohlc_invalid_rows"] = con.execute(f"SELECT count(*) FROM {full} WHERE open<=0 OR high<=0 OR low<=0 OR close<=0 OR high<greatest(open,close,low) OR low>least(open,close,high)").fetchone()[0]
                if "volume" in names:
                    entry["nonpositive_volume_rows"] = con.execute(f"SELECT count(*) FROM {full} WHERE volume<=0").fetchone()[0]
                if "source" in names:
                    entry["sources"] = dict(con.execute(f"SELECT cast(source AS varchar), count(*) FROM {full} GROUP BY 1").fetchall())
            except Exception as exc:
                entry["query_error"] = f"{type(exc).__name__}: {exc}"
            result["tables"].append(entry)
        if "prices_daily" in {name for _, name in tables}:
            result["prices_detail"] = {
                "by_source_basis": [dict(zip(("source", "feed", "adjustment_basis", "rows", "securities", "dates", "first", "last", "last_ingested"), row)) for row in con.execute("SELECT source, feed, adjustment_basis, count(*), count(DISTINCT security_id), count(DISTINCT date), min(date), max(date), max(ingested_at) FROM prices_daily GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall()],
                "sha_rows_missing": con.execute("SELECT count(*) FROM prices_daily WHERE raw_sha256 IS NULL OR length(raw_sha256)<>64").fetchone()[0],
                "availability_after_session": con.execute("SELECT count(*) FROM prices_daily WHERE CAST(available_at AT TIME ZONE 'America/New_York' AS DATE)>date").fetchone()[0],
                "distinct_raw_hashes": con.execute("SELECT count(DISTINCT raw_sha256) FROM prices_daily").fetchone()[0],
                "price_key_groups_with_versions": con.execute("SELECT count(*) FROM (SELECT security_id,date,source,count(*) n FROM prices_daily GROUP BY 1,2,3 HAVING n>1)").fetchone()[0],
                "exact_duplicate_version_rows": con.execute("SELECT coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM prices_daily GROUP BY security_id,date,source,feed,adjustment_basis,raw_sha256 HAVING n>1)").fetchone()[0],
                "distinct_security_sessions": con.execute("SELECT count(*) FROM (SELECT DISTINCT security_id,date FROM prices_daily)").fetchone()[0],
                "quality_flags": dict(con.execute("SELECT coalesce(quality_flag,'<null>'),count(*) FROM prices_daily GROUP BY 1").fetchall()),
            }
            hashes = [r[0] for r in con.execute("SELECT DISTINCT raw_sha256 FROM prices_daily WHERE raw_sha256 IS NOT NULL").fetchall()]
            root_raw = ROOT / "data/raw/objects"
            result["prices_detail"]["raw_objects_missing"] = sum(not (root_raw / digest).is_file() for digest in hashes)
            result["prices_detail"]["raw_objects_hash_mismatch"] = sum((root_raw / digest).is_file() and hashlib.sha256((root_raw / digest).read_bytes()).hexdigest() != digest for digest in hashes)
        if "labels" in {name for _, name in tables}:
            result["labels_detail"] = [dict(zip(("kind", "basis", "rows", "first", "last", "gross_nonnull", "proxy_nonnull"), row)) for row in con.execute("SELECT label_kind,adjustment_basis,count(*),min(date),max(date),count(forward_return),count(proxy_forward_return) FROM labels GROUP BY 1,2 ORDER BY 1,2").fetchall()]
        if "factor_returns" in {name for _, name in tables}:
            result["french_detail"] = [dict(zip(("factor", "rows", "first", "last", "max_available_at"), row)) for row in con.execute("SELECT factor_name,count(*),min(date),max(date),max(available_at) FROM factor_returns GROUP BY 1 ORDER BY 1").fetchall()]
        if "features_daily" in {name for _, name in tables}:
            result["features_detail"] = [dict(zip(("research_mode", "decision_eligible", "rows", "first", "last"), row)) for row in con.execute("SELECT research_mode,decision_eligible,count(*),min(date),max(date) FROM features_daily GROUP BY 1,2 ORDER BY 1,2").fetchall()]
        if "securities" in {name for _, name in tables}:
            result["security_detail"] = [dict(zip(("source", "asset_type", "quality_flag", "rows"), row)) for row in con.execute("SELECT source,asset_type,quality_flag,count(*) FROM securities GROUP BY 1,2,3 ORDER BY 1,2,3").fetchall()]
        if "corporate_event_versions" in {name for _, name in tables}:
            result["event_detail"] = [dict(zip(("provider", "event_type", "rows", "securities", "first_observed", "last_observed"), row)) for row in con.execute("SELECT provider,event_type,count(*),count(DISTINCT symbol),min(observed_at),max(observed_at) FROM corporate_event_versions GROUP BY 1,2 ORDER BY 1,2").fetchall()]
        con.close()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def main() -> None:
    output = ROOT / "outputs" / "local_acceptance"
    output.mkdir(parents=True, exist_ok=True)
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "databases": [audit_database(path) for path in DATABASES]}
    target = output / "database_audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(target.relative_to(ROOT))
    for database in report["databases"]:
        print(database["path"], "tables", len(database["tables"]), "error", database.get("error"))
        for table in database["tables"]:
            print(" ", table["table"], "rows", table.get("rows"), "securities", table.get("securities"), "dates", table.get("first"), table.get("last"), "error", table.get("query_error"))


if __name__ == "__main__":
    main()
