"""Append-only DuckDB store for QDR L1 market observations and provenance.

One local writer process is expected. Provider credentials are never persisted.
Raw provider bodies are optional immutable SHA256 objects; parsed observations
always retain a receipt reference. This store does not attest PIT eligibility.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from uuid import uuid4

_SHA = re.compile(r"^[a-f0-9]{64}$")
_MAX_RAW_BYTES = 100_000_000


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("SESSION_DATE_REQUIRED")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValueError("SESSION_DATE_INVALID") from exc


def _timestamp(value, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("TIMESTAMP_INVALID") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _finite(value, *, optional=False):
    if value is None and optional:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        if optional:
            return None
        raise ValueError("NUMERIC_VALUE_INVALID") from exc
    if not math.isfinite(number):
        if optional:
            return None
        raise ValueError("NUMERIC_VALUE_NONFINITE")
    return number


def _json(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str, allow_nan=False)


def _optional_int(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if math.isfinite(number) else None


class L1MarketStore:
    """Local append-only L1 data store with source receipt enforcement."""

    def __init__(self, project_root, *, db_path=None):
        import duckdb
        self.root = Path(project_root).resolve()
        self.data_root = self.root / "data" / "l1_market"
        self.raw_root = self.data_root / "raw"
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.data_root / "market_data.duckdb"
        if not self.db_path.is_absolute():
            self.db_path = self.root / self.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        self.initialize()

    def initialize(self):
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_schema (
            version INTEGER PRIMARY KEY, installed_at TIMESTAMPTZ NOT NULL)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_source_receipts (
            receipt_sha256 VARCHAR PRIMARY KEY, provider VARCHAR NOT NULL,
            dataset VARCHAR NOT NULL, fetched_at TIMESTAMPTZ NOT NULL,
            available_at TIMESTAMPTZ, observed_start DATE, observed_end DATE,
            raw_object_path VARCHAR, metadata_json VARCHAR NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL)""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_bars (
            session_date DATE NOT NULL, security_id VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL, open DOUBLE NOT NULL, high DOUBLE NOT NULL,
            low DOUBLE NOT NULL, close DOUBLE NOT NULL, volume DOUBLE NOT NULL,
            vwap DOUBLE, trade_count BIGINT, provider VARCHAR NOT NULL,
            price_basis VARCHAR NOT NULL, identity_status VARCHAR NOT NULL,
            available_at TIMESTAMPTZ NOT NULL, receipt_sha256 VARCHAR NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(session_date, security_id, provider, price_basis, receipt_sha256))""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_universe (
            session_date DATE NOT NULL, universe_id VARCHAR NOT NULL,
            security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,
            is_member BOOLEAN NOT NULL, provider VARCHAR NOT NULL,
            membership_basis VARCHAR NOT NULL, pit_status VARCHAR NOT NULL,
            known_at TIMESTAMPTZ NOT NULL, receipt_sha256 VARCHAR NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(session_date, universe_id, security_id, provider, receipt_sha256))""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_observations (
            session_date DATE NOT NULL, dimension VARCHAR NOT NULL,
            feature_id VARCHAR NOT NULL, value DOUBLE, unit VARCHAR NOT NULL,
            provider VARCHAR NOT NULL, source VARCHAR NOT NULL,
            observed_at TIMESTAMPTZ, available_at TIMESTAMPTZ NOT NULL,
            vintage_id VARCHAR NOT NULL, pit_status VARCHAR NOT NULL,
            quality_status VARCHAR NOT NULL, coverage_n BIGINT,
            expected_n BIGINT, receipt_sha256 VARCHAR NOT NULL,
            metadata_json VARCHAR NOT NULL, ingested_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(session_date, feature_id, provider, vintage_id, receipt_sha256))""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_events (
            event_id VARCHAR NOT NULL, source VARCHAR NOT NULL,
            event_type VARCHAR NOT NULL, scheduled_at TIMESTAMPTZ NOT NULL,
            schedule_known_at TIMESTAMPTZ NOT NULL, released_at TIMESTAMPTZ,
            consensus_value DOUBLE, consensus_known_at TIMESTAMPTZ,
            actual_value DOUBLE, receipt_sha256 VARCHAR NOT NULL,
            vintage_id VARCHAR NOT NULL, metadata_json VARCHAR NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY(event_id, source, vintage_id))""")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS l1_market_run_log (
            run_id VARCHAR PRIMARY KEY, command VARCHAR NOT NULL,
            started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ,
            status VARCHAR NOT NULL, counts_json VARCHAR NOT NULL,
            errors_json VARCHAR NOT NULL)""")
        self.conn.execute("""INSERT INTO l1_market_schema
            SELECT 1, ? WHERE NOT EXISTS (SELECT 1 FROM l1_market_schema WHERE version=1)""",
            [datetime.now(timezone.utc)])

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _require_receipt(self, digest):
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError("SOURCE_RECEIPT_SHA256_REQUIRED")
        if not self.conn.execute(
            "SELECT 1 FROM l1_market_source_receipts WHERE receipt_sha256=?", [digest]
        ).fetchone():
            raise ValueError("SOURCE_RECEIPT_NOT_REGISTERED")

    def write_receipt(self, *, provider, dataset, fetched_at, receipt_sha256,
                      available_at=None, observed_start=None, observed_end=None,
                      payload=None, metadata=None):
        if not provider or not dataset:
            raise ValueError("SOURCE_ID_REQUIRED")
        fetched = _timestamp(fetched_at)
        available = _timestamp(available_at, optional=True)
        if not isinstance(receipt_sha256, str) or not _SHA.fullmatch(receipt_sha256):
            raise ValueError("SOURCE_RECEIPT_SHA256_INVALID")
        raw_path = None
        if payload is not None:
            if not isinstance(payload, bytes) or len(payload) > _MAX_RAW_BYTES:
                raise ValueError("RAW_SOURCE_OBJECT_SIZE_INVALID")
            actual = sha256(payload).hexdigest()
            if actual != receipt_sha256:
                raise ValueError("RAW_SOURCE_OBJECT_HASH_MISMATCH")
            path = self.raw_root / actual[:2] / actual
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if sha256(path.read_bytes()).hexdigest() != actual:
                    raise ValueError("RAW_SOURCE_OBJECT_TAMPERED")
            else:
                temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
                try:
                    with temp.open("xb") as stream:
                        stream.write(payload)
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
            raw_path = path.relative_to(self.root).as_posix()
        self.conn.execute("""INSERT INTO l1_market_source_receipts VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""",
            [receipt_sha256, provider, dataset, fetched, available,
             _date(observed_start) if observed_start else None,
             _date(observed_end) if observed_end else None,
             raw_path, _json(metadata), datetime.now(timezone.utc)])
        return receipt_sha256

    def write_bars(self, records):
        rows, now = [], datetime.now(timezone.utc)
        for item in records:
            digest = item.get("receipt_sha256")
            self._require_receipt(digest)
            symbol = str(item.get("symbol") or "").strip().upper()
            security_id = str(item.get("security_id") or "").strip()
            provider = str(item.get("provider") or "").strip()
            basis = str(item.get("price_basis") or "").strip()
            if not symbol or not security_id or not provider or not basis:
                raise ValueError("BAR_IDENTITY_OR_BASIS_REQUIRED")
            opn, high, low, close, volume = [_finite(item.get(k)) for k in
                                               ("open", "high", "low", "close", "volume")]
            if min(opn, high, low, close) <= 0 or volume < 0:
                raise ValueError("BAR_PRICE_OR_VOLUME_INVALID")
            if high < max(opn, close, low) or low > min(opn, close, high):
                raise ValueError("BAR_OHLC_INCONSISTENT")
            rows.append((_date(item.get("session_date") or item.get("date")),
                security_id, symbol, opn, high, low, close, volume,
                _finite(item.get("vwap"), optional=True), _optional_int(item.get("trade_count")),
                provider, basis, str(item.get("identity_status") or "SYMBOL_ONLY_UNVERIFIED"),
                _timestamp(item.get("available_at")), digest, now))
        if rows:
            self.conn.executemany("""INSERT INTO l1_market_bars VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""", rows)
        return len(rows)

    def write_universe(self, records):
        rows, now = [], datetime.now(timezone.utc)
        for item in records:
            self._require_receipt(item.get("receipt_sha256"))
            if type(item.get("is_member")) is not bool:
                raise ValueError("UNIVERSE_MEMBERSHIP_MUST_BE_BOOLEAN")
            rows.append((_date(item.get("session_date") or item.get("date")),
                str(item.get("universe_id") or ""), str(item.get("security_id") or ""),
                str(item.get("symbol") or "").upper(), item["is_member"],
                str(item.get("provider") or ""), str(item.get("membership_basis") or "UNATTESTED"),
                str(item.get("pit_status") or "PIT_UNATTESTED"),
                _timestamp(item.get("known_at")), item["receipt_sha256"], now))
        if any(not x[1] or not x[2] or not x[3] or not x[5] for x in rows):
            raise ValueError("UNIVERSE_IDENTITY_REQUIRED")
        if rows:
            self.conn.executemany("""INSERT INTO l1_market_universe VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""", rows)
        return len(rows)

    def write_observations(self, records):
        rows, now = [], datetime.now(timezone.utc)
        for item in records:
            self._require_receipt(item.get("receipt_sha256"))
            value = _finite(item.get("value"), optional=True)
            status = str(item.get("quality_status") or item.get("status") or "OBSERVED")
            if status == "OBSERVED" and value is None:
                raise ValueError("OBSERVED_FEATURE_VALUE_REQUIRED")
            rows.append((_date(item.get("session_date") or item.get("observed_date")),
                str(item.get("dimension") or ""), str(item.get("feature_id") or item.get("id") or ""),
                value, str(item.get("unit") or ""), str(item.get("provider") or ""),
                str(item.get("source") or ""), _timestamp(item.get("observed_at"), optional=True),
                _timestamp(item.get("available_at") or item.get("fetched_at")),
                str(item.get("vintage_id") or "CURRENT_VINTAGE"),
                str(item.get("pit_status") or item.get("pit") or "PIT_UNVERIFIED"),
                status, _optional_int(item.get("coverage_n")),
                _optional_int(item.get("expected_n")), item["receipt_sha256"],
                _json(item.get("metadata")), now))
        if any(not x[1] or not x[2] or not x[4] or not x[5] or not x[14] for x in rows):
            raise ValueError("OBSERVATION_IDENTITY_REQUIRED")
        if rows:
            self.conn.executemany("""INSERT INTO l1_market_observations VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""", rows)
        return len(rows)

    def write_events(self, records):
        rows, now = [], datetime.now(timezone.utc)
        for item in records:
            self._require_receipt(item.get("receipt_sha256"))
            rows.append((str(item.get("event_id") or ""), str(item.get("source") or ""),
                str(item.get("event_type") or ""), _timestamp(item.get("scheduled_at")),
                _timestamp(item.get("schedule_known_at")),
                _timestamp(item.get("released_at"), optional=True),
                _finite(item.get("consensus_value"), optional=True),
                _timestamp(item.get("consensus_known_at"), optional=True),
                _finite(item.get("actual_value"), optional=True), item["receipt_sha256"],
                str(item.get("vintage_id") or "CURRENT_VINTAGE"),
                _json(item.get("metadata")), now))
        if any(not x[0] or not x[1] or not x[2] for x in rows):
            raise ValueError("EVENT_IDENTITY_REQUIRED")
        if rows:
            self.conn.executemany("""INSERT INTO l1_market_events VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING""", rows)
        return len(rows)

    def read_bars(self, *, start=None, end=None, symbols=None):
        query, params = "SELECT * FROM l1_market_bars WHERE 1=1", []
        if start:
            query += " AND session_date>=?"
            params.append(_date(start))
        if end:
            query += " AND session_date<=?"
            params.append(_date(end))
        if symbols:
            clean = sorted({str(x).upper() for x in symbols})
            query += " AND symbol IN (" + ",".join("?" for _ in clean) + ")"
            params.extend(clean)
        return self.conn.execute(query + " ORDER BY session_date, symbol", params).fetchdf()

    def read_universe(self, *, universe_id=None, start=None, end=None):
        query, params = "SELECT * FROM l1_market_universe WHERE 1=1", []
        if universe_id:
            query += " AND universe_id=?"
            params.append(universe_id)
        if start:
            query += " AND session_date>=?"
            params.append(_date(start))
        if end:
            query += " AND session_date<=?"
            params.append(_date(end))
        return self.conn.execute(query + " ORDER BY session_date, symbol", params).fetchdf()

    def read_observations(self, *, asof=None, dimension=None):
        query, params = "SELECT * FROM l1_market_observations WHERE 1=1", []
        if asof:
            query += " AND session_date<=?"
            params.append(_date(asof))
        if dimension:
            query += " AND dimension=?"
            params.append(dimension)
        return self.conn.execute(query + " ORDER BY session_date, feature_id", params).fetchdf()

    def status(self):
        bars = self.conn.execute("""SELECT COUNT(*), COUNT(DISTINCT symbol),
            MIN(session_date), MAX(session_date) FROM l1_market_bars""").fetchone()
        obs = self.conn.execute("""SELECT COUNT(*), COUNT(DISTINCT feature_id),
            MAX(session_date) FROM l1_market_observations""").fetchone()
        universe = self.conn.execute("""SELECT COUNT(*), COUNT(DISTINCT security_id),
            MAX(session_date) FROM l1_market_universe""").fetchone()
        receipts = self.conn.execute("SELECT COUNT(*) FROM l1_market_source_receipts").fetchone()[0]
        return {
            "schema": "qdr.l1.market_data_store_status.v1",
            "database": self.db_path.as_posix(),
            "bars": {"rows": bars[0], "symbols": bars[1],
                     "first_session": str(bars[2]) if bars[2] else None,
                     "last_session": str(bars[3]) if bars[3] else None},
            "observations": {"rows": obs[0], "features": obs[1],
                             "last_session": str(obs[2]) if obs[2] else None},
            "universe": {"rows": universe[0], "securities": universe[1],
                         "last_session": str(universe[2]) if universe[2] else None},
            "source_receipts": receipts, "historical_pit_verified": False,
            "forecast_eligible": False, "trade_eligible": False,
        }
