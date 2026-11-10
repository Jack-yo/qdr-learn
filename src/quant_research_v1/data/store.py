"""Version-preserving DuckDB warehouse; Parquet exports are source/feed partitioned."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

# On Windows venv Python uses a launcher; the runtime wheel places C++ DLLs
# in sys.prefix, which Python 3.8+ does not search automatically for extensions.
_runtime_dll_dir = os.add_dll_directory(sys.prefix) if sys.platform == "win32" else None
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from quant_research.clock import utc
from quant_research.data.schema import PriceRecord

DDL = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT INTO schema_version VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS securities (
 security_id VARCHAR PRIMARY KEY, symbol VARCHAR NOT NULL, exchange VARCHAR,
 asset_type VARCHAR NOT NULL, first_seen DATE NOT NULL, last_seen DATE NOT NULL,
 source VARCHAR NOT NULL, quality_flag VARCHAR NOT NULL);
CREATE TABLE IF NOT EXISTS prices_daily (
 security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, date DATE NOT NULL,
 open DOUBLE NOT NULL, high DOUBLE NOT NULL, low DOUBLE NOT NULL, close DOUBLE NOT NULL,
 volume BIGINT NOT NULL, vwap DOUBLE, adjustment_basis VARCHAR NOT NULL,
 source VARCHAR NOT NULL, feed VARCHAR NOT NULL, event_time TIMESTAMPTZ NOT NULL,
 available_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
 availability_basis VARCHAR NOT NULL, raw_sha256 VARCHAR NOT NULL, quality_flag VARCHAR NOT NULL,
 PRIMARY KEY (security_id,date,source,feed,adjustment_basis,raw_sha256),
 CHECK(volume>=0), CHECK(low>0 AND low<=open AND low<=close AND high>=open AND high>=close),
 CHECK(event_time<=available_at AND available_at<=ingested_at));
ALTER TABLE prices_daily ADD COLUMN IF NOT EXISTS adj_close DOUBLE;
CREATE TABLE IF NOT EXISTS price_observations (
 security_id VARCHAR NOT NULL, date DATE NOT NULL, source VARCHAR NOT NULL, feed VARCHAR NOT NULL,
 adjustment_basis VARCHAR NOT NULL, raw_sha256 VARCHAR NOT NULL,
 available_at TIMESTAMPTZ NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(security_id,date,source,feed,adjustment_basis,raw_sha256,available_at));
INSERT INTO price_observations SELECT security_id,date,source,feed,adjustment_basis,raw_sha256,available_at,ingested_at
 FROM prices_daily ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS factor_returns (
 date DATE NOT NULL, factor_name VARCHAR NOT NULL, value_decimal DOUBLE, source VARCHAR NOT NULL,
 available_at TIMESTAMPTZ NOT NULL, version VARCHAR NOT NULL, use_policy VARCHAR NOT NULL,
 PRIMARY KEY(date,factor_name,source,version));
CREATE TABLE IF NOT EXISTS sec_snapshots (
 cik VARCHAR NOT NULL, kind VARCHAR NOT NULL, raw_sha256 VARCHAR NOT NULL,
 fetched_at TIMESTAMPTZ NOT NULL, available_at TIMESTAMPTZ NOT NULL, quality_flag VARCHAR NOT NULL,
 PRIMARY KEY(cik,kind,raw_sha256));
CREATE TABLE IF NOT EXISTS filings (
 cik VARCHAR NOT NULL, accession VARCHAR NOT NULL, form VARCHAR NOT NULL, period_end DATE,
 accepted_at TIMESTAMPTZ, available_at TIMESTAMPTZ NOT NULL, source_version VARCHAR NOT NULL,
 quality_flag VARCHAR NOT NULL, PRIMARY KEY(cik,accession,source_version));
CREATE TABLE IF NOT EXISTS runs (
 run_id VARCHAR PRIMARY KEY, created_at_utc TIMESTAMPTZ NOT NULL, asof_timestamp_utc TIMESTAMPTZ NOT NULL,
 data_cutoff_utc TIMESTAMPTZ NOT NULL, universe_version VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
 config_sha256 VARCHAR NOT NULL, data_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, manifest_json VARCHAR NOT NULL);
CREATE TABLE IF NOT EXISTS corporate_actions (
 security_id VARCHAR NOT NULL, event_id VARCHAR NOT NULL, ex_date DATE NOT NULL, action_type VARCHAR NOT NULL,
 factor_or_cash DOUBLE NOT NULL, announced_at TIMESTAMPTZ, available_at TIMESTAMPTZ,
 source VARCHAR NOT NULL, version VARCHAR NOT NULL, PRIMARY KEY(security_id,event_id,source,version));
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS quality_flag VARCHAR DEFAULT 'UNKNOWN';
ALTER TABLE corporate_actions ADD COLUMN IF NOT EXISTS currency VARCHAR;
INSERT INTO schema_version VALUES (2) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS universe_daily (
 date DATE NOT NULL, security_id VARCHAR NOT NULL, universe_version VARCHAR NOT NULL, is_eligible BOOLEAN NOT NULL,
 reason VARCHAR NOT NULL, source VARCHAR NOT NULL, quality_flag VARCHAR NOT NULL, available_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY(date,security_id,universe_version));
CREATE TABLE IF NOT EXISTS fundamentals_pit (
 security_id VARCHAR NOT NULL, feature VARCHAR NOT NULL, value DOUBLE, period_end DATE NOT NULL,
 available_at TIMESTAMPTZ NOT NULL, source_accession VARCHAR NOT NULL,
 PRIMARY KEY(security_id,feature,period_end,source_accession,available_at));
CREATE TABLE IF NOT EXISTS features_daily (
 date DATE NOT NULL,security_id VARCHAR NOT NULL,feature_name VARCHAR NOT NULL,value DOUBLE,
 available_at TIMESTAMPTZ,version VARCHAR NOT NULL,research_mode VARCHAR NOT NULL,
 decision_eligible BOOLEAN NOT NULL,missing_reason VARCHAR NOT NULL,signal_time TIMESTAMPTZ NOT NULL,
 run_id VARCHAR NOT NULL,PRIMARY KEY(run_id,date,security_id,feature_name));
CREATE TABLE IF NOT EXISTS labels (
 date DATE NOT NULL,security_id VARCHAR NOT NULL,horizon INTEGER NOT NULL,
 entry_time TIMESTAMPTZ NOT NULL,exit_time TIMESTAMPTZ NOT NULL,available_at TIMESTAMPTZ,
 forward_return DOUBLE,benchmark_return DOUBLE,proxy_forward_return DOUBLE,proxy_benchmark_return DOUBLE,
 net_return DOUBLE,adjustment_basis VARCHAR NOT NULL,label_kind VARCHAR NOT NULL,missing_reason VARCHAR NOT NULL,
 entry_date DATE NOT NULL,exit_date DATE NOT NULL,run_id VARCHAR NOT NULL,
 PRIMARY KEY(run_id,date,security_id,horizon));
INSERT INTO schema_version VALUES (3) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS predictions (
 run_id VARCHAR NOT NULL,date DATE NOT NULL,security_id VARCHAR NOT NULL,horizon INTEGER NOT NULL,variant VARCHAR NOT NULL,
 p_up DOUBLE,expected_return DOUBLE,expected_excess_return DOUBLE,downside_quantile DOUBLE,uncertainty DOUBLE,
 model_version VARCHAR NOT NULL,available_at TIMESTAMPTZ NOT NULL,decision_eligible BOOLEAN NOT NULL,
 research_mode VARCHAR NOT NULL,PRIMARY KEY(run_id,date,security_id,horizon,variant));
CREATE TABLE IF NOT EXISTS orders (
 run_id VARCHAR NOT NULL,experiment_key VARCHAR NOT NULL,sequence INTEGER NOT NULL,date DATE,security_id VARCHAR,
 status VARCHAR,record_json VARCHAR NOT NULL,PRIMARY KEY(run_id,experiment_key,sequence));
CREATE TABLE IF NOT EXISTS fills (
 run_id VARCHAR NOT NULL,experiment_key VARCHAR NOT NULL,sequence INTEGER NOT NULL,date DATE NOT NULL,security_id VARCHAR NOT NULL,
 side VARCHAR NOT NULL,quantity BIGINT NOT NULL,fill_time TIMESTAMPTZ NOT NULL,fill_price DOUBLE NOT NULL,cost DOUBLE NOT NULL,
 record_json VARCHAR NOT NULL,PRIMARY KEY(run_id,experiment_key,sequence));
CREATE TABLE IF NOT EXISTS positions (
 run_id VARCHAR NOT NULL,experiment_key VARCHAR NOT NULL,date DATE NOT NULL,security_id VARCHAR NOT NULL,quantity BIGINT NOT NULL,
 mark_price DOUBLE NOT NULL,weight DOUBLE NOT NULL,record_json VARCHAR NOT NULL,PRIMARY KEY(run_id,experiment_key,date,security_id));
CREATE TABLE IF NOT EXISTS equity_curve (
 run_id VARCHAR NOT NULL,experiment_key VARCHAR NOT NULL,date DATE NOT NULL,cash DOUBLE NOT NULL,equity DOUBLE NOT NULL,
 cumulative_costs DOUBLE NOT NULL,record_json VARCHAR NOT NULL,PRIMARY KEY(run_id,experiment_key,date));
INSERT INTO schema_version VALUES (4) ON CONFLICT DO NOTHING;
"""


class Warehouse:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = duckdb.connect(str(self.path))
        self.db.execute("SET TimeZone='UTC'")
        self.db.execute(DDL)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.db.close()

    def count(self, table):
        if table not in {"securities", "prices_daily", "factor_returns", "sec_snapshots", "filings", "runs", "corporate_actions", "features_daily", "labels", "predictions","orders","fills","positions","equity_curve"}:
            raise ValueError("Unknown table")
        return self.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def insert_rows(self, table, rows):
        from quant_research.policy import require_real_source
        for row in rows:
            if 'source' in row: require_real_source(row['source'])
            if table=='runs':
                require_real_source(json.loads(row['manifest_json']).get('source'))
        if not rows:
            return 0
        allowed = {"factor_returns", "sec_snapshots", "filings", "runs", "corporate_actions"}
        if table not in allowed:
            raise ValueError("Table requires specialized insertion")
        columns = [r[1] for r in self.db.execute(f"PRAGMA table_info('{table}')").fetchall()]
        if any(set(row) != set(columns) for row in rows):
            raise ValueError("Row columns do not match table schema")
        before = self.count(table)
        self.db.execute("BEGIN")
        try:
            self.db.register("incoming_records", pa.Table.from_pylist(rows))
            try:
                projection = ",".join('"' + c + '"' for c in columns)
                self.db.execute(f"INSERT INTO {table} SELECT {projection} FROM incoming_records ON CONFLICT DO NOTHING")
            finally:
                self.db.unregister("incoming_records")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.count(table) - before

    def insert_frame(self, table, frame):
        from quant_research.policy import PolicyError
        for column in ('security_id','research_mode'):
            if column in frame and frame[column].astype(str).str.contains('synth|fixture|mock|demo',case=False,regex=True).any():
                raise PolicyError('NON_REAL_RECORD_REJECTED','Non-real derived record rejected')
        if table not in ("features_daily","labels","predictions","orders","fills","positions","equity_curve"):
            raise ValueError("Derived table not allowed")
        columns = [r[1] for r in self.db.execute(f"PRAGMA table_info('{table}')").fetchall()]
        if set(columns) != set(frame.columns):
            raise ValueError("Derived frame schema mismatch")
        before = self.count(table)
        self.db.register("derived_frame",pa.Table.from_pandas(frame,preserve_index=False))
        try:
            self.db.execute("BEGIN")
            projection = ",".join('"'+c+'"' for c in columns)
            self.db.execute(f"INSERT INTO {table} SELECT {projection} FROM derived_frame ON CONFLICT DO NOTHING")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        finally:
            self.db.unregister("derived_frame")
        return self.count(table)-before

    def store_audit(self,table,frame,run_id,experiment_key):
        if table not in ("orders","fills","positions","equity_curve"):
            raise ValueError("Execution table not allowed")
        if frame.empty:
            return 0
        import pandas as pd
        # Pandas JSON normalizes NaN to null before strict archival JSON serialization.
        records=json.loads(frame.to_json(orient="records",date_format="iso"))
        rows=[]
        for sequence,record in enumerate(records):
            row={"run_id":run_id,"experiment_key":experiment_key,"record_json":json.dumps(record,allow_nan=False)}
            if table in ("orders","fills"):
                row["sequence"]=sequence
            if table=="orders":
                stamp=record.get("date") or record.get("signal_time") or record.get("fill_time")
                row.update(date=str(stamp)[:10] if stamp else None,security_id=record.get("security_id"),status=record.get("status"))
            elif table=="fills":
                row.update({key:record[key] for key in ["date","security_id","side","quantity","fill_time","fill_price","cost"]})
            elif table=="positions":
                row.update({key:record[key] for key in ["date","security_id","quantity","mark_price","weight"]})
            else:
                row.update({key:record[key] for key in ["date","cash","equity","cumulative_costs"]})
            rows.append(row)
        return self.insert_frame(table,pd.DataFrame(rows))

    def put_prices(self, records, clock):
        from quant_research.policy import require_real_source
        for record in records: require_real_source(record.source)
        records = [PriceRecord.model_validate(r) for r in records]
        keys = set()
        for record in records:
            key = (record.security_id, record.date, record.source, record.feed, record.raw_sha256)
            if key in keys:
                raise ValueError("Duplicate price key in ingestion batch")
            keys.add(key)
            if utc(record.event_time) != clock.close(record.date):
                raise ValueError("Price event timestamp is not the session close")
        before = self.count("prices_daily")
        self.db.execute("BEGIN")
        try:
            identities = {}
            for r in records:
                identities.setdefault(r.security_id, []).append(r)
            for group in identities.values():
                r = group[0]
                self.db.execute("""INSERT INTO securities VALUES (?,?,NULL,'UNKNOWN',?,?,?,?)
                    ON CONFLICT(security_id) DO UPDATE SET
                    first_seen=least(securities.first_seen,excluded.first_seen),
                    last_seen=greatest(securities.last_seen,excluded.last_seen)""",
                    [r.security_id, r.symbol, min(x.date for x in group), max(x.date for x in group), r.source, r.quality_flag])
            if records:
                self.db.register("incoming_prices", pa.Table.from_pylist([r.model_dump() for r in records]))
                try:
                    self.db.execute("INSERT INTO prices_daily SELECT * FROM incoming_prices ON CONFLICT DO NOTHING")
                    self.db.execute("""INSERT INTO price_observations
                        SELECT security_id,date,source,feed,adjustment_basis,raw_sha256,available_at,ingested_at
                        FROM incoming_prices ON CONFLICT DO NOTHING""")
                finally:
                    self.db.unregister("incoming_prices")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return self.count("prices_daily") - before

    def prices(self, source, feed, cutoff=None, start=None, end=None):
        from quant_research.policy import require_real_source
        require_real_source(source)
        if cutoff is None:
            clause, params = "", [source, feed]
        else:
            clause, params = " AND obs.available_at<=? AND p.event_time<=?", [source, feed, utc(cutoff), utc(cutoff)]
        if start is not None:
            clause += " AND p.date>=?"
            params.append(start)
        if end is not None:
            clause += " AND p.date<=?"
            params.append(end)
        # Select vintage only AFTER applying knowledge cutoff, never use latest then backdate.
        return self.db.execute(f"""SELECT p.* REPLACE(obs.available_at AS available_at,obs.ingested_at AS ingested_at)
            FROM prices_daily p JOIN price_observations obs USING(security_id,date,source,feed,adjustment_basis,raw_sha256)
            WHERE p.source=? AND p.feed=? {clause}
            QUALIFY row_number() OVER (PARTITION BY p.security_id,p.date,p.source,p.feed,p.adjustment_basis
              ORDER BY obs.available_at DESC,p.raw_sha256 DESC)=1 ORDER BY p.security_id,p.date""", params).fetch_arrow_table()

    def export_prices(self, root, source, feed):
        table = self.prices(source, feed)
        digest = hashlib.sha256(table.to_pandas().to_json(date_format="iso", orient="records").encode()).hexdigest()
        path = Path(root) / source.lower() / feed / f"{digest}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path)
        return path
