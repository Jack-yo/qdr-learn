"""Contracts for the QDR L1 six-system / twelve-dimension foundation."""
import hashlib
import pytest

from quant_research.data.l1_market_catalog import (
    DIMENSIONS, FEATURES, SOURCES, SYSTEMS, catalog_payload, coverage_matrix,
)


def test_catalog_has_six_systems_twelve_dimensions_and_unique_features():
    payload = catalog_payload()
    assert len(SYSTEMS) == 6
    assert len(DIMENSIONS) == 12
    assert len(FEATURES) == len({x.key for x in FEATURES})
    assert payload["counts"]["sources"] == len(SOURCES)
    assert {x.key for x in DIMENSIONS} == {
        "price", "breadth", "volatility", "options_pricing",
        "options_positioning", "microstructure", "correlation",
        "cross_asset", "positioning", "events", "funding", "path",
    }


def test_path_is_outcome_validation_not_predictor_input():
    path = next(x for x in DIMENSIONS if x.key == "path")
    assert path.role == "outcome_validation_not_input"
    assert path.system_keys == ()
    assert all(not x.key.startswith("fwd_") or x.dimension == "path" for x in FEATURES)


def test_registry_does_not_confuse_code_with_live_or_pit_coverage():
    payload = catalog_payload()
    assert payload["policy"]["live_verified"] is False
    assert payload["policy"]["historical_pit_verified"] is False
    assert payload["policy"]["forecast_eligible"] is False
    pit = next(x for x in SOURCES if x.key == "pit_universe")
    assert pit.code_status == "BLOCKED"
    assert "固定 30" in pit.limitation


def test_coverage_uses_actual_observations_not_registered_features():
    result = coverage_matrix()
    assert result["summary"]["features_observed"] == 0
    assert all(x["coverage"]["available"] == 0 for x in result["dimensions"])
    breadth = next(x for x in result["dimensions"] if x["id"] == "breadth")
    assert breadth["status"] == "BLOCKED"
    assert breadth["model_eligible"] is False


def test_coverage_marks_partial_and_never_upgrades_pit_without_attestation():
    result = coverage_matrix([
        {"feature_id": "advances", "observed_date": "2026-11-16",
         "value": 100, "status": "OBSERVED", "pit_status": "CURRENT_SNAPSHOT_ONLY"},
    ], asof="2026-11-16")
    breadth = next(x for x in result["dimensions"] if x["id"] == "breadth")
    assert breadth["status"] == "PARTIAL"
    assert breadth["coverage"]["available"] == 1
    assert breadth["historical_pit_verified"] is False
    assert breadth["model_eligible"] is False


def test_coverage_ignores_future_and_null_observations():
    result = coverage_matrix([
        {"feature_id": "vix_close", "observed_date": "2026-11-18",
         "value": 20, "status": "OBSERVED"},
        {"feature_id": "rv5", "observed_date": "2026-11-16",
         "value": None, "status": "OBSERVED"},
    ], asof="2026-11-17")
    vol = next(x for x in result["dimensions"] if x["id"] == "volatility")
    assert vol["coverage"]["available"] == 0


def test_store_receipt_is_required_and_bars_are_idempotent(tmp_path):
    pytest.importorskip("duckdb")
    from datetime import datetime, timezone
    from quant_research.data.l1_market_store import L1MarketStore
    payload = b"actual source response bytes"
    digest = hashlib.sha256(payload).hexdigest()
    with L1MarketStore(tmp_path) as store:
        with pytest.raises(ValueError, match="SOURCE_RECEIPT_NOT_REGISTERED"):
            store.write_bars([{
                "date": "2026-11-16", "security_id": "SYMBOL:SPY", "symbol": "SPY",
                "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000,
                "provider": "fixture-provider", "price_basis": "raw",
                "available_at": "2026-11-16T22:00:00Z", "receipt_sha256": digest,
            }])
        store.write_receipt(provider="fixture-provider", dataset="bars",
            fetched_at=datetime.now(timezone.utc), available_at="2026-11-16T22:00:00Z",
            receipt_sha256=digest, payload=payload)
        row = {
            "date": "2026-11-16", "security_id": "SYMBOL:SPY", "symbol": "SPY",
            "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1000,
            "provider": "fixture-provider", "price_basis": "raw",
            "available_at": "2026-11-16T22:00:00Z", "receipt_sha256": digest,
        }
        assert store.write_bars([row]) == 1
        assert store.write_bars([row]) == 1
        assert len(store.read_bars()) == 1
        assert store.status()["source_receipts"] == 1


def test_universe_snapshot_schema_migration_preserves_column_semantics(tmp_path):
    duckdb=pytest.importorskip("duckdb")
    from datetime import datetime,timezone
    from quant_research.data.l1_market_store import L1MarketStore
    db=tmp_path/"l1_market.duckdb"
    conn=duckdb.connect(str(db))
    conn.execute("""CREATE TABLE l1_market_universe (
        session_date DATE NOT NULL, universe_id VARCHAR NOT NULL,
        security_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL,
        is_member BOOLEAN NOT NULL, provider VARCHAR NOT NULL,
        membership_basis VARCHAR NOT NULL, pit_status VARCHAR NOT NULL,
        known_at TIMESTAMPTZ NOT NULL, receipt_sha256 VARCHAR NOT NULL,
        ingested_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(session_date, universe_id, security_id, provider, receipt_sha256))""")
    conn.close()
    payload=b"complete current universe snapshot"
    digest=hashlib.sha256(payload).hexdigest()
    with L1MarketStore(tmp_path,db_path=db) as store:
        store.write_receipt(provider="fixture",dataset="universe",
            fetched_at=datetime.now(timezone.utc),
            available_at="2026-11-16T20:00:00Z",
            receipt_sha256=digest,payload=payload)
        store.write_universe([{
            "session_date":"2026-11-16","universe_id":"CURRENT","security_id":"ID:AAPL",
            "symbol":"AAPL","is_member":True,"provider":"fixture",
            "membership_basis":"CURRENT_DIRECTORY","snapshot_complete":True,
            "pit_status":"CURRENT_SNAPSHOT_ONLY","known_at":"2026-11-16T20:00:00Z",
            "receipt_sha256":digest,
        }])
        row=store.read_universe().iloc[0]
        assert bool(row.snapshot_complete) is True
        assert row.pit_status=="CURRENT_SNAPSHOT_ONLY"


def test_public_scan_persists_features_and_source_health(tmp_path):
    pytest.importorskip("duckdb")
    from quant_research.workflow.l1_market_ingest import (
        market_data_snapshot,persist_public_scan,
    )
    digest=hashlib.sha256(b"fixture public source response").hexdigest()
    payload={
        "schema":"qdr.l1.extended.v1","asof_session":"2026-11-16",
        "fetched_at":"2026-11-16T22:00:00Z",
        "features":[{
            "domain":"breadth","id":"advances","label":"上涨家数","value":1250,
            "unit":"只","status":"PARTIAL","source":"FIXTURE",
            "observed_date":"2026-11-16","fetched_at":"2026-11-16T22:00:00Z",
            "pit":"CURRENT_SNAPSHOT_ONLY","receipt_sha256":digest,
            "coverage_n":1250,"expected_n":3000,
        }],
        "source_health":{"market_breadth":{
            "status":"PARTIAL","source":"FIXTURE",
            "effective_date":"2026-11-16","fetched_at":"2026-11-16T22:00:00Z",
            "receipt_sha256":digest,"coverage_n":1250,"expected_n":3000,
            "input_receipts":[hashlib.sha256(b"asset list").hexdigest(),
                              hashlib.sha256(b"snapshot batch").hexdigest()],
        }},
        "calendar_events":[],
    }
    result=persist_public_scan(tmp_path,payload,scan_kind="extended")
    assert result["features"]==1 and result["source_health"]==3
    snapshot=market_data_snapshot(tmp_path)
    breadth=next(x for x in snapshot["coverage"]["dimensions"] if x["id"]=="breadth")
    assert breadth["coverage"]["available"]==1
    assert breadth["historical_pit_verified"] is False
    assert snapshot["policy"]["forecast_eligible"] is False
    assert snapshot["status"]["source_receipts"]>=1
    health_by_key={x["source_key"]:x for x in snapshot["source_health"]}
    assert {"alpaca_assets","alpaca_snapshots","market_breadth"} <= set(health_by_key)
    assert health_by_key["alpaca_assets"]["receipt_sha256"] == hashlib.sha256(b"asset list").hexdigest()
    assert health_by_key["alpaca_snapshots"]["receipt_sha256"] == hashlib.sha256(b"snapshot batch").hexdigest()
    assert health_by_key["alpaca_snapshots"]["metadata"]["snapshot_receipt_count"] == 1


def test_registry_blocked_pit_universe_is_visible_without_runtime_failure():
    from quant_research.data.l1_market_catalog import coverage_matrix
    result=coverage_matrix([],source_health={})
    breadth=next(x for x in result["dimensions"] if x["id"]=="breadth")
    assert breadth["status"]=="BLOCKED"
    assert "pit_universe" in breadth["blocked_sources"]
    assert breadth["model_eligible"] is False


def test_partial_breadth_keeps_pit_universe_blocker_visible():
    from quant_research.data.l1_market_catalog import coverage_matrix
    result=coverage_matrix([{
        "session_date":"2026-11-16","feature_id":"advances","value":1200,
        "quality_status":"PARTIAL","pit_status":"PIT_UNVERIFIED_CURRENT_UNIVERSE",
    }],source_health={"alpaca_assets":{"status":"OBSERVED"},
                      "alpaca_snapshots":{"status":"PARTIAL"}})
    breadth=next(x for x in result["dimensions"] if x["id"]=="breadth")
    assert breadth["status"]=="PARTIAL"
    assert "pit_universe" in breadth["blocked_sources"]


def test_missing_market_breadth_health_is_attributed_to_both_alpaca_sources(tmp_path):
    pytest.importorskip("duckdb")
    from quant_research.workflow.l1_market_ingest import market_data_snapshot,persist_public_scan
    payload={
        "schema":"qdr.l1.extended.v1","asof_session":"2026-11-16",
        "fetched_at":"2026-11-16T22:00:00Z","features":[],
        "source_health":{"market_breadth":{"status":"MISSING","code":"MISSING_ALPACA_CREDENTIALS",
            "fetched_at":"2026-11-16T22:00:00Z"}},
        "calendar_events":[],
    }
    persist_public_scan(tmp_path,payload,scan_kind="extended")
    snapshot=market_data_snapshot(tmp_path)
    health={x["source_key"]:x["status"] for x in snapshot["source_health"]}
    assert health["alpaca_assets"]=="MISSING"
    assert health["alpaca_snapshots"]=="MISSING"

def test_asset_directory_success_survives_snapshot_batch_failure(tmp_path):
    pytest.importorskip("duckdb")
    from quant_research.workflow.l1_market_ingest import market_data_snapshot,persist_public_scan
    asset_digest=hashlib.sha256(b"asset directory response").hexdigest()
    derived_digest=hashlib.sha256(b"derived breadth response").hexdigest()
    payload={
        "schema":"qdr.l1.extended.v1","asof_session":"2026-11-16",
        "fetched_at":"2026-11-16T22:00:00Z","features":[],
        "source_health":{"market_breadth":{
            "status":"MISSING","code":"ALL_ALPACA_SNAPSHOT_BATCHES_FAILED",
            "source":"ALPACA_ACTIVE_US_EQUITY_SNAPSHOT_BREADTH",
            "fetched_at":"2026-11-16T22:00:00Z",
            "receipt_sha256":derived_digest,
            "input_receipts":[asset_digest],
            "coverage_n":0,"expected_n":120,
            "observation_mode":"NO_SNAPSHOT_DATA",
        }},
        "calendar_events":[],
    }
    persist_public_scan(tmp_path,payload,scan_kind="extended")
    snapshot=market_data_snapshot(tmp_path)
    health={x["source_key"]:x for x in snapshot["source_health"]}
    assert health["alpaca_assets"]["status"]=="OBSERVED"
    assert health["alpaca_assets"]["receipt_sha256"]==asset_digest
    assert health["alpaca_snapshots"]["status"]=="MISSING"
    assert health["alpaca_snapshots"]["receipt_sha256"] is None
    assert health["market_breadth"]["status"]=="MISSING"

def test_append_only_bar_and_universe_reads_select_latest_revision(tmp_path):
    pytest.importorskip("duckdb")
    from datetime import datetime,timezone
    from quant_research.data.l1_market_store import L1MarketStore

    first=b"first provider revision"
    second=b"corrected provider revision"
    first_sha=hashlib.sha256(first).hexdigest()
    second_sha=hashlib.sha256(second).hexdigest()
    stamp=datetime(2026,11,16,22,0,tzinfo=timezone.utc)
    with L1MarketStore(tmp_path) as store:
        for payload,digest in ((first,first_sha),(second,second_sha)):
            store.write_receipt(provider="fixture",dataset="bars",
                fetched_at=stamp,available_at=stamp,receipt_sha256=digest,payload=payload)
        base={
            "session_date":"2026-11-16","security_id":"ID:AAA","symbol":"AAA",
            "open":100,"high":103,"low":99,"close":101,"volume":1000,
            "provider":"fixture","price_basis":"raw","available_at":stamp,
        }
        store.write_bars([{**base,"receipt_sha256":first_sha}])
        store.write_bars([{**base,"close":102,"receipt_sha256":second_sha}])
        bars=store.read_bars()
        assert len(bars)==1
        assert bars.iloc[0].close==102
        assert bars.iloc[0].receipt_sha256==second_sha

        universe_first=b"first universe revision"
        universe_second=b"corrected universe revision"
        universe_first_sha=hashlib.sha256(universe_first).hexdigest()
        universe_second_sha=hashlib.sha256(universe_second).hexdigest()
        for payload,digest in ((universe_first,universe_first_sha),
                               (universe_second,universe_second_sha)):
            store.write_receipt(provider="fixture",dataset="universe",
                fetched_at=stamp,available_at=stamp,receipt_sha256=digest,payload=payload)
        universe_base={
            "session_date":"2026-11-16","universe_id":"CURRENT_SAMPLE",
            "security_id":"ID:AAA","symbol":"AAA","is_member":True,
            "provider":"fixture","membership_basis":"CURRENT_DIRECTORY",
            "snapshot_complete":True,"pit_status":"CURRENT_SNAPSHOT_ONLY",
            "known_at":stamp,
        }
        store.write_universe([{**universe_base,"receipt_sha256":universe_first_sha}])
        store.write_universe([{**universe_base,"is_member":False,
                               "receipt_sha256":universe_second_sha}])
        universe=store.read_universe(universe_id="CURRENT_SAMPLE")
        assert len(universe)==1
        assert bool(universe.iloc[0].is_member) is False
        assert universe.iloc[0].receipt_sha256==universe_second_sha

def test_coverage_keeps_all_partial_feature_rows_as_partial():
    from quant_research.data.l1_market_catalog import FEATURES,coverage_matrix
    specs=[x for x in FEATURES if x.dimension=="price"]
    rows=[{
        "feature_id":spec.key,"session_date":"2026-11-16","value":1.0,
        "quality_status":"PARTIAL","available_at":"2026-11-16T22:00:00Z",
    } for spec in specs]
    result=coverage_matrix(rows,asof="2026-11-16")
    price=next(x for x in result["dimensions"] if x["id"]=="price")
    assert price["coverage"]["available"]==len(specs)
    assert price["status"]=="PARTIAL"


def test_latest_missing_observation_supersedes_older_valid_value():
    from quant_research.data.l1_market_catalog import coverage_matrix
    result=coverage_matrix([
        {"feature_id":"vix_close","session_date":"2026-11-16","value":20.0,
         "quality_status":"OBSERVED","available_at":"2026-11-16T22:00:00Z"},
        {"feature_id":"vix_close","session_date":"2026-11-16","value":None,
         "quality_status":"MISSING","available_at":"2026-11-16T23:00:00Z"},
    ],asof="2026-11-16")
    volatility=next(x for x in result["dimensions"] if x["id"]=="volatility")
    assert "vix_close" in volatility["missing_features"]
    assert volatility["coverage"]["available"]==0

def test_fomc_calendar_is_registered_as_partial_non_pit_source():
    from quant_research.data.l1_market_catalog import FEATURE_BY_KEY,SOURCE_BY_KEY
    feature=FEATURE_BY_KEY["days_to_fomc"]
    source=SOURCE_BY_KEY["fed_calendar"]
    assert feature.implementation=="PARTIAL"
    assert source.code_status=="IMPLEMENTED_PARTIAL"
    assert source.pit_status=="CURRENT_PUBLISHED_SCHEDULE_NOT_HISTORICAL_PIT"

def test_pit_attested_universe_import_requires_manifest_bound_to_source_hash(tmp_path):
    import json
    from types import SimpleNamespace
    from quant_research.data.l1_market_store import L1MarketStore
    from quant_research.workflow.l1_market_data import _import_universe

    csv_path=tmp_path/"pit_universe.csv"
    csv_bytes=(
        "session_date,security_id,symbol,is_member,snapshot_complete,known_at\n"
        "2026-11-16,CRSP:AAA,AAA,true,true,2026-11-16T22:00:00Z\n"
    ).encode()
    csv_path.write_bytes(csv_bytes)
    data_sha=hashlib.sha256(csv_bytes).hexdigest()
    manifest={
        "attestation_id":"CRSP-US-COMMON-2026-11",
        "provider":"CRSP","scope":"US_COMMON_STOCKS",
        "coverage_start":"2020-01-01","coverage_end":"2026-11-16",
        "source_data_sha256":data_sha,
        "security_identity_scheme":"CRSP_PERMNO",
        "membership_point_in_time":True,"delisted_included":True,
        "known_at_semantics":"point_in_time","license_scope":"research_use_only",
        "review_status":"OPERATOR_REVIEWED",
        "reviewed_at":"2026-11-17T22:00:00Z","reviewed_by":"research_operator",
    }
    manifest_path=tmp_path/"pit_manifest.json"
    manifest_path.write_text(json.dumps(manifest),encoding="utf-8")
    args=SimpleNamespace(
        input=csv_path,session_date=None,universe_id="US_COMMON_STOCKS",
        provider="CRSP",snapshot_complete=True,known_at=None,
        membership_basis="PIT_VENDOR_MEMBERSHIP",pit_status="PIT_ATTESTED",
        pit_attestation_file=manifest_path,
    )
    with L1MarketStore(tmp_path) as store:
        result=_import_universe(store,args)
        rows=store.read_universe(universe_id="US_COMMON_STOCKS")
        assert result["pit_status"]=="PIT_ATTESTED"
        assert rows.iloc[0].pit_status=="PIT_ATTESTED"
        assert rows.iloc[0].pit_attestation_id==manifest["attestation_id"]
        assert rows.iloc[0].pit_attestation_provider=="CRSP"
        assert rows.iloc[0].pit_attestation_sha256==hashlib.sha256(
            manifest_path.read_bytes()).hexdigest()
        args.pit_status="PIT_VERIFIED"
        with pytest.raises(ValueError,match="PIT_VERIFIED_REQUIRES_INDEPENDENT_SIGNATURE_VERIFICATION"):
            _import_universe(store,args)


def test_pit_attested_features_are_not_mistaken_for_pit_verified():
    import json
    specs=[x for x in FEATURES if x.dimension=="price"]
    rows=[{
        "feature_id":spec.key,"session_date":"2026-11-16","value":1.0,
        "quality_status":"OBSERVED","pit_status":"PIT_ATTESTED",
        "metadata_json":json.dumps({"pit_attestation_id":"CRSP-US-COMMON-2026-11"}),
    } for spec in specs]
    result=coverage_matrix(rows,asof="2026-11-16")
    price=next(x for x in result["dimensions"] if x["id"]=="price")
    assert price["historical_pit_verified"] is False
    assert price["model_eligible"] is False
