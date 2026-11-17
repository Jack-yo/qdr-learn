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
    assert breadth["status"] == "MISSING"
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
