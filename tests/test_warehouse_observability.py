"""Read-only warehouse inventory and preview contract tests."""
import json
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.error import HTTPError
from urllib.request import urlopen

import duckdb
import pytest

from quant_research.data.catalog import build_catalog, cache_inventory
from quant_research.data.warehouse_observability import (
    overview, dataset_detail, preview_dataset, maintenance_runs,
)
from quant_research.web import Console, ThreadingHTTPServer, handler
from quant_research.policy import PolicyError


def _l1_store(root):
    path = root / "data/l1_market/market_data.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    now = datetime.now(timezone.utc)
    with duckdb.connect(str(path)) as db:
        db.execute("""CREATE TABLE l1_market_bars(
            session_date DATE, security_id VARCHAR, symbol VARCHAR,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE,
            vwap DOUBLE, trade_count BIGINT, provider VARCHAR, price_basis VARCHAR,
            identity_status VARCHAR, available_at TIMESTAMPTZ,
            receipt_sha256 VARCHAR, ingested_at TIMESTAMPTZ)""")
        db.execute("""INSERT INTO l1_market_bars VALUES
            (?,?,?,10,11,9,10.5,1000,NULL,12,'ALPACA','raw','SYMBOL_UNVERIFIED',?,?,?)""",
            [today, "SID-AAA", "AAA", now, "a" * 64, now])
        db.execute("CREATE TABLE l1_market_observations(session_date DATE, feature_id VARCHAR)")
        db.executemany("INSERT INTO l1_market_observations VALUES (?,?)",
                       [(today, "vix_close"), (today, "advance_decline_ratio")])
        db.execute("""CREATE TABLE l1_market_source_health(
            source_key VARCHAR, asof_session DATE, fetched_at TIMESTAMPTZ,
            status VARCHAR, error_code VARCHAR, receipt_sha256 VARCHAR, metadata_json VARCHAR)""")
        db.execute("""INSERT INTO l1_market_source_health VALUES
            (?,?,?,'OBSERVED',NULL,?,'{}')""",
            ["alpaca_bars", today, now, "b" * 64])
    return path

def _price_store(root):
    path = root / "data/real_v21.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as db:
        db.execute("""CREATE TABLE prices_daily(
            symbol VARCHAR, date DATE, source VARCHAR, feed VARCHAR,
            adjustment_basis VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE,
            close DOUBLE, volume BIGINT)""")
        db.execute("""INSERT INTO prices_daily VALUES
            ('SPY','2026-11-13','ALPACA','sip','raw',600,605,598,603,1000000),
            ('QQQ','2026-11-13','ALPACA','sip','raw',500,505,498,503,800000)""")
    return path


def test_overview_is_read_only_and_does_not_create_missing_stores(tmp_path):
    result = overview(tmp_path)
    assert result["schema"] == "qdr.warehouse.overview.v1"
    assert result["status"] == "AVAILABLE"
    assert result["policy"]["read_only"] is True
    assert result["policy"]["provider_requests"] is False
    assert any(x["dataset_id"] == "l1_market_bars" and x["status"] == "NOT_CREATED"
               for x in result["datasets"])
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "outputs").exists()


def test_l1_inventory_uses_real_rows_and_source_health(tmp_path):
    _l1_store(tmp_path)
    result = overview(tmp_path)
    bars = next(x for x in result["datasets"] if x["dataset_id"] == "l1_market_bars")
    assert bars["status"] == "COLLECTED_RESTRICTED_USE"
    assert bars["physical_rows"] == 1
    assert bars["unique_rows"] == 1
    assert bars["symbols"] == 1
    assert "close" in bars["field_names"] and "session_date" in bars["field_names"]
    assert bars["last_observation"] == datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    observations = next(x for x in result["datasets"] if x["dataset_id"] == "l1_market_observations")
    assert "volatility_options" in observations["systems"]
    assert result["summary"]["l1_observed_features"] == 2
    source = next(x for x in result["sources"] if x["key"] == "alpaca_bars")
    assert source["runtime_status"] == "OBSERVED"
    assert source["latest_observation"]["asof_session"] == datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    assert result["policy"]["historical_pit_verified"] is False


def test_missing_source_health_is_not_reported_as_current(tmp_path):
    result = overview(tmp_path)
    source = next(x for x in result["sources"] if x["key"] == "alpaca_bars")
    assert source["runtime_status"] == "NOT_OBSERVED"
    assert source["freshness"]["status"] == "UNKNOWN_DATE"
    assert source["latest_observation"] is None


def test_l1_dataset_detail_and_preview_are_actual_and_read_only(tmp_path):
    _l1_store(tmp_path)
    detail = dataset_detail(tmp_path, "l1_market_bars")
    assert detail["preview_supported"] is True
    assert {x["name"] for x in detail["fields"]} >= {"session_date", "symbol", "close", "receipt_sha256"}
    result = preview_dataset(tmp_path, "l1_market_bars", q="AAA", limit=10)
    assert result["total"] == 1
    assert result["rows"][0]["symbol"] == "AAA"
    assert result["rows"][0]["close"] == 10.5
    assert result["read_only"] is True
    with duckdb.connect(str(tmp_path / "data/l1_market/market_data.duckdb"), read_only=True) as db:
        assert db.execute("SELECT COUNT(*) FROM l1_market_bars").fetchone()[0] == 1



def test_source_freshness_uses_observation_date_not_fetch_time(tmp_path):
    _l1_store(tmp_path)
    old_day = (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=10)).isoformat()
    with duckdb.connect(str(tmp_path / "data/l1_market/market_data.duckdb")) as db:
        db.execute("UPDATE l1_market_source_health SET asof_session=?", [old_day])
        db.execute("UPDATE l1_market_source_health SET fetched_at=?", [datetime.now(timezone.utc)])
    result = overview(tmp_path)
    source = next(x for x in result["sources"] if x["key"] == "alpaca_bars")
    assert source["latest_observation"]["fetched_at_utc"] is not None
    assert source["freshness"]["status"] == "STALE"
    assert source["runtime_status"] == "STALE"
    assert any(x["type"] == "SOURCE" and x["id"] == "alpaca_bars"
               for x in result["attention"])



def test_quality_checks_and_failed_maintenance_appear_in_attention(tmp_path):
    _l1_store(tmp_path)
    with duckdb.connect(str(tmp_path / "data/l1_market/market_data.duckdb")) as db:
        db.execute("""CREATE TABLE l1_market_quality_checks(
            session_date DATE, dimension VARCHAR, status VARCHAR, reason VARCHAR,
            coverage_n BIGINT, expected_n BIGINT, checked_at TIMESTAMPTZ, metadata_json VARCHAR)""")
        db.execute("""INSERT INTO l1_market_quality_checks VALUES
            (CURRENT_DATE,'breadth','PARTIAL','INCOMPLETE_SOURCE_COVERAGE',18,28,CURRENT_TIMESTAMP,'{}')""")
    run = tmp_path / "outputs/maintenance/run-quality"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "run_id": "run-quality", "status": "PARTIAL_BLOCKED",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "tasks": [{"group": "prices", "status": "BLOCKED", "code": "MISSING_SESSION"}],
    }), encoding="utf-8")
    result = overview(tmp_path)
    quality = next(x for x in result["attention"] if x["type"] == "QUALITY_CHECK")
    maintenance = next(x for x in result["attention"] if x["type"] == "MAINTENANCE")
    quality_asset = next(x for x in result["datasets"] if x["dataset_id"] == "l1_market_quality_checks")
    assert "breadth_structure" in quality_asset["systems"]
    assert quality["status"] == "PARTIAL"
    assert "18/28" in quality["reason"]
    assert quality["occurred_at"] and quality["action"]
    assert maintenance["reason"] == "MISSING_SESSION"
    assert maintenance["occurred_at"] and maintenance["action"]


def test_primary_market_preview_keeps_alpaca_sip_raw_scope(tmp_path):
    _price_store(tmp_path)
    inventory_result = overview(tmp_path)
    market_asset = next(x for x in inventory_result["datasets"] if x["dataset_id"] == "market_prices")
    assert {"symbol", "date", "source", "feed", "adjustment_basis"} <= set(market_asset["field_names"])
    result = preview_dataset(tmp_path, "market_prices", q="SPY", limit=10)
    assert result["total"] == 1
    assert result["rows"][0]["symbol"] == "SPY"
    assert result["rows"][0]["source"] == "ALPACA"
    assert result["rows"][0]["feed"] == "sip"
    assert result["rows"][0]["adjustment_basis"] == "raw"


def test_preview_rejects_unsafe_identifiers_and_unbounded_queries(tmp_path):
    with pytest.raises(ValueError, match="DATASET_ID"):
        dataset_detail(tmp_path, "../prices")
    with pytest.raises(ValueError, match="PAGINATION"):
        preview_dataset(tmp_path, "market_prices", limit=500)
    with pytest.raises(ValueError, match="SYMBOL"):
        preview_dataset(tmp_path, "market_prices", symbol="SPY;DROP TABLE prices_daily")
    with pytest.raises(ValueError, match="DATE"):
        preview_dataset(tmp_path, "market_prices", start="2026-99-99")


def test_fast_catalog_mode_does_not_rehash_raw_objects(tmp_path):
    receipts = tmp_path / "data/raw/receipts"
    objects = tmp_path / "data/raw/objects"
    receipts.mkdir(parents=True)
    objects.mkdir(parents=True)
    digest = "a" * 64
    (objects / digest).write_bytes(b"content whose hash is deliberately not checked")
    (receipts / "receipt.json").write_text(json.dumps({
        "sha256": digest, "url": "https://data.alpaca.markets/v2/stocks/bars",
        "fetched_at": "2026-11-13T22:00:00Z",
    }), encoding="utf-8")
    rows = cache_inventory(tmp_path, verify_hashes=False)
    assert rows[0]["hash_verified"] is None
    assert rows[0]["hash_check"] == "NOT_RECHECKED"
    catalog = build_catalog(tmp_path, verify_cache_hashes=False)
    assert catalog["cache_hash_verification"] == "SKIPPED"
    assert catalog["cache_hash_failures"] is None


def test_maintenance_lock_blocks_warehouse_reads(tmp_path):
    marker = tmp_path / "data/catalog/.maintenance.lock"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"pid":1}', encoding="utf-8")
    result = overview(tmp_path)
    assert result["status"] == "MAINTENANCE_RUNNING"
    assert result["datasets"] == []
    with pytest.raises(PolicyError, match="maintenance"):
        dataset_detail(tmp_path, "l1_market_bars")


def test_maintenance_runs_read_only_manifest(tmp_path):
    folder = tmp_path / "outputs/maintenance/run-1"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({
        "run_id": "run-1", "status": "PARTIAL_BLOCKED",
        "created_at_utc": "2026-11-13T22:00:00Z",
        "tasks": [{"group": "prices", "status": "BLOCKED", "code": "SOURCE_OUTAGE",
                   "inserted_rows": 0}],
    }), encoding="utf-8")
    result = maintenance_runs(tmp_path, limit=5)
    assert result["total"] == 1
    assert result["runs"][0]["tasks"][0]["code"] == "SOURCE_OUTAGE"


def test_warehouse_http_routes_and_shell_navigation(tmp_path):
    console = Console(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(console))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/warehouse/overview") as response:
            data = json.load(response)
            assert response.status == 200
            assert data["policy"]["read_only"] is True
        with urlopen(base + "/api/v1/warehouse/datasets/l1_market_bars") as response:
            detail = json.load(response)
            assert response.status == 200
            assert detail["preview_supported"] is False
        with urlopen(base + "/studio") as response:
            html = response.read().decode("utf-8")
            assert 'data-page="warehouse"' in html
            assert 'v4_ui_warehouse.js' in html
            assert 'v4_ui_warehouse.css' in html
        with urlopen(base + "/assets/v4_ui_warehouse.js") as response:
            assert response.status == 200
        with urlopen(base + "/assets/v4_ui_warehouse.css") as response:
            assert response.status == 200
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/warehouse/runs?limit=51")
        assert error.value.code == 400
        assert json.load(error.value)["code"] == "WAREHOUSE_QUERY_INVALID"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/warehouse/datasets/not_a_real_dataset")
        assert error.value.code == 404
        assert json.load(error.value)["code"] == "WAREHOUSE_DATASET_NOT_FOUND"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/warehouse/overview?unexpected=1")
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
