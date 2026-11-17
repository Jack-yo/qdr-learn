from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest

from quant_research.data.l1_market_store import L1MarketStore
from quant_research.data.warehouse_observability import (
    warehouse_dataset, warehouse_overview, warehouse_preview, warehouse_runs,
)


def _populate(root):
    payload = b"read-only warehouse fixture receipt"
    digest = sha256(payload).hexdigest()
    stamp = datetime(2026, 11, 17, 22, 30, tzinfo=timezone.utc)
    with L1MarketStore(root) as store:
        store.write_receipt(
            provider="ALPACA", dataset="fixture_bars",
            fetched_at=stamp, available_at=stamp,
            observed_start="2026-11-16", observed_end="2026-11-16",
            receipt_sha256=digest, payload=payload,
        )
        store.write_bars([{
            "session_date": "2026-11-16", "security_id": "SID-SPY",
            "symbol": "SPY", "open": 600, "high": 605, "low": 598,
            "close": 603, "volume": 1000000, "provider": "ALPACA",
            "price_basis": "raw", "identity_status": "SYMBOL_ONLY_UNVERIFIED",
            "available_at": stamp, "receipt_sha256": digest,
        }])
        store.write_observations([{
            "session_date": "2026-11-16", "dimension": "volatility",
            "feature_id": "rv20", "value": 18.2, "unit": "%",
            "provider": "ALPACA", "source": "ALPACA_BARS",
            "available_at": stamp, "receipt_sha256": digest,
            "pit_status": "PIT_UNVERIFIED", "quality_status": "OBSERVED",
            "coverage_n": 1, "expected_n": 1,
        }])
        store.write_source_health([{
            "source_key": "alpaca_bars", "asof_session": "2026-11-16",
            "fetched_at": stamp, "status": "OBSERVED",
            "receipt_sha256": digest,
            "metadata": {"feed": "sip", "symbols": 28, "api_key": "DO_NOT_EXPOSE"},
        }])
    return digest


def test_missing_warehouse_database_is_not_created_by_get(tmp_path):
    result = warehouse_overview(tmp_path)
    assert result["status"] == "PARTIAL"
    assert result["read_only"] is True
    assert len(result["sources"]) == 21
    assert all(x["run_status"] == "NOT_OBSERVED" for x in result["sources"])
    assert not (tmp_path / "data/l1_market").exists()
    assert warehouse_runs(tmp_path)["status"] == "NOT_CREATED"


def test_overview_separates_source_registry_from_real_run_health(tmp_path):
    _populate(tmp_path)
    result = warehouse_overview(tmp_path)
    assert result["status"] == "OBSERVED"
    assert result["read_only"] is True
    assert result["summary"]["datasets"] >= 17
    assert result["summary"]["populated_datasets"] >= 3
    l1_ids={x["dataset_id"] for x in result["datasets"]}
    assert {"market_bars","market_universe","market_observations",
            "security_features","reference_history","market_events",
            "source_health","quality_checks","path_outcomes",
            "source_receipts","maintenance_runs"} <= l1_ids
    bars=next(x for x in result["datasets"] if x["dataset_id"]=="market_bars")
    assert bars["latest_fetched_at_utc"]=="2026-11-17T22:30:00+00:00"
    assert result["policy"]["provider_requests"] is False
    sources = {item["source_key"]: item for item in result["sources"]}
    assert len(sources) == 21
    assert sources["alpaca_bars"]["code_status"] == "IMPLEMENTED_PARTIAL"
    assert sources["alpaca_bars"]["run_status"] == "OBSERVED"
    assert sources["alpaca_bars"]["metadata"] == {"feed":"sip"}
    assert "api_key" not in json.dumps(result)
    assert sources["alpaca_assets"]["run_status"] == "NOT_OBSERVED"
    assert any(item["dataset_id"] == "reference_history" for item in result["datasets"])
    assert next(item for item in result["datasets"]
                if item["dataset_id"] == "path_outcomes")["use_policy"] == "OUTCOME_VALIDATION_NOT_MODEL_INPUT"


def test_existing_catalog_assets_are_listed_with_explicit_preview_limit(tmp_path):
    result=warehouse_overview(tmp_path)
    datasets={item["dataset_id"]:item for item in result["datasets"]}
    assert "market_prices" in datasets
    assert "classic_factors" in datasets
    assert "pit_fundamentals" in datasets
    assert datasets["market_prices"]["preview_supported"] is True
    detail=warehouse_dataset(tmp_path,"market_prices")
    assert detail["status"]=="OBSERVED"
    assert detail["policy"]["preview_supported"] is True
    preview=warehouse_preview(tmp_path,"market_prices")
    assert preview["status"]=="NOT_CREATED"
    assert preview["rows"]==[]


def test_primary_sip_prices_have_source_filtered_read_only_preview(tmp_path):
    import duckdb

    db_path=tmp_path/"data/real_v21.duckdb"
    db_path.parent.mkdir(parents=True)
    with duckdb.connect(str(db_path)) as db:
        db.execute("""CREATE TABLE prices_daily(
            security_id VARCHAR,symbol VARCHAR,date DATE,
            open DOUBLE,high DOUBLE,low DOUBLE,close DOUBLE,volume BIGINT,
            vwap DOUBLE,adjustment_basis VARCHAR,source VARCHAR,feed VARCHAR,
            event_time TIMESTAMPTZ,available_at TIMESTAMPTZ,ingested_at TIMESTAMPTZ,
            availability_basis VARCHAR,raw_sha256 VARCHAR,quality_flag VARCHAR)""")
        db.execute("""INSERT INTO prices_daily VALUES
            ('SID-SPY','SPY','2026-11-16',600,605,598,603,1000,602,
             'raw','ALPACA','sip','2026-11-16T21:00:00Z',
             '2026-11-16T21:05:00Z','2026-11-16T21:06:00Z',
             'PROVIDER_TIMESTAMP','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','PASS'),
            ('SID-QQQ','QQQ','2026-11-16',500,505,498,503,1000,502,
             'raw','ALPACA','iex','2026-11-16T21:00:00Z',
             '2026-11-16T21:05:00Z','2026-11-16T21:06:00Z',
             'PROVIDER_TIMESTAMP','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','PASS')""")
    overview=warehouse_overview(tmp_path)
    market=next(x for x in overview["datasets"] if x["dataset_id"]=="market_prices")
    assert market["physical_rows"]==2
    assert market["preview_supported"] is True
    result=warehouse_preview(tmp_path,"market_prices",symbol="spy")
    assert result["status"]=="OBSERVED"
    assert result["total"]==1
    assert result["rows"][0]["symbol"]=="SPY"
    assert result["rows"][0]["feed"]=="sip"
    assert result["use_policy"]=="ALPACA_SIP_RAW_OBSERVATION_ONLY"


def test_dataset_detail_and_preview_are_allowlisted_and_paginated(tmp_path):
    _populate(tmp_path)
    detail = warehouse_dataset(tmp_path, "market_bars")
    assert detail["status"] == "OBSERVED"
    assert detail["dataset"]["physical_rows"] == 1
    assert detail["dataset"]["unique_rows"] == 1
    assert detail["dataset"]["symbols"] == 1

    page = warehouse_preview(tmp_path, "market_bars", limit=1, offset=0, symbol="spy")
    assert page["status"] == "OBSERVED"
    assert page["total"] == 1
    assert page["rows"][0]["symbol"] == "SPY"
    assert page["rows"][0]["session_date"] == "2026-11-16"
    assert page["read_only"] is True

    with pytest.raises(ValueError, match="WAREHOUSE_DATASET_NOT_ALLOWED"):
        warehouse_preview(tmp_path, "arbitrary_table")
    with pytest.raises(ValueError, match="WAREHOUSE_LIMIT_INVALID"):
        warehouse_preview(tmp_path, "market_bars", limit=500)
    with pytest.raises(ValueError, match="WAREHOUSE_SYMBOL_INVALID"):
        warehouse_preview(tmp_path, "market_bars", symbol="SPY;DROP")


def test_maintenance_lock_blocks_reads_without_opening_database(tmp_path):
    _populate(tmp_path)
    lock = tmp_path / "data/catalog/.maintenance.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("maintenance", encoding="utf-8")
    result = warehouse_overview(tmp_path)
    assert result["status"] == "MAINTENANCE_RUNNING"
    assert result["datasets"] == []
    preview = warehouse_preview(tmp_path, "market_bars")
    assert preview["status"] == "MAINTENANCE_RUNNING"
    assert preview["rows"] == []


def test_l1_run_history_returns_only_existing_run_rows(tmp_path):
    _populate(tmp_path)
    assert warehouse_runs(tmp_path)["runs"] == []
    with L1MarketStore(tmp_path) as store:
        store.conn.execute(
            """INSERT INTO l1_market_run_log
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ["run-1", "scan-live",
             datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc),
             datetime(2026, 11, 17, 22, 1, tzinfo=timezone.utc),
             "PARTIAL", json.dumps({"sources": 2}),
             json.dumps({"fred_alfred": "NO_CREDENTIALS"})],
        )
    result = warehouse_runs(tmp_path)
    assert result["status"] == "OBSERVED"
    assert result["runs"][0]["run_id"] == "run-1"
    assert result["runs"][0]["counts"] == {"sources": 2}
    assert result["runs"][0]["errors"] == {"fred_alfred": "NO_CREDENTIALS"}
