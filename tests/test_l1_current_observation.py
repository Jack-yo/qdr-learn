"""Contracts for the real current-vintage L1 observation adapter."""
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.research.l1_features import DOMAINS, REGISTRY
from quant_research.workflow.l1_current_observation import (
    STATUS,
    build_current_observation,
    current_observation_for_api,
)


def _bundle(*, with_benchmark=True):
    day = pd.Timestamp("2026-11-12")
    rows = []
    if with_benchmark:
        rows.append({"date": day, "symbol": "SPY", "open": 100.0,
                     "high": 103.0, "low": 99.0, "close": 102.0,
                     "available_at": "2026-11-13T00:10:00Z",
                     "event_time": "2026-11-12T21:00:00Z",
                     "source": "ALPACA", "feed": "sip", "adjustment_basis": "raw"})
    prices = pd.DataFrame(rows)
    return SimpleNamespace(
        prices=prices,
        metadata={"asof_date_et": "2026-11-12", "knowledge_cutoff_utc": "2026-11-13T00:20:00Z",
                  "source": "ALPACA", "feed": "sip", "source_version_kind": "current_revised_snapshot",
                  "snapshot_sha256": "a" * 64},
    )


def test_current_observation_has_all_57_features_and_12_domains():
    result = build_current_observation(_bundle())
    assert result["status"] == STATUS
    assert len(result["features"]) == 57 == len(REGISTRY)
    assert len(result["domains"]) == 12 == len(DOMAINS)
    assert result["current_prediction_eligible"] is False
    assert result["historical_pit_verified"] is False
    assert result["forecast"] is None
    assert result["source_time"]["available_at"] == "2026-11-13T00:10:00Z"
    assert result["knowledge_cutoff_utc"] == "2026-11-13T00:20:00Z"
    assert all(item["status"] == "MISSING" for item in result["features"]
               if item["id"] not in {"market_intraday_return", "market_close_location"})
    assert not any(item["id"].startswith("breadth_") and item["status"] == "OBSERVED"
                    for item in result["features"])


def test_same_session_values_are_descriptive_only():
    result = build_current_observation(_bundle())
    values = {item["id"]: item["value"] for item in result["features"]}
    assert values["market_intraday_return"] == pytest.approx(0.02)
    assert values["market_close_location"] == pytest.approx(0.75)
    assert "RAW_ETF_HISTORY_CORPORATE_ACTION_CONTINUITY_NOT_PROVEN" in result["limitations"]
    assert result["source_version_kind"] == "current_revised_snapshot"


def test_missing_benchmark_and_asof_mismatch_fail_closed():
    with pytest.raises(ValueError, match="NO_REAL_DATA"):
        build_current_observation(_bundle(with_benchmark=False))
    with pytest.raises(ValueError, match="ASOF_MISMATCH"):
        build_current_observation(_bundle(), asof="2026-11-11")


def test_late_or_naive_source_time_is_rejected():
    bundle=_bundle()
    bundle.prices.loc[0,'available_at']='2026-11-13T00:30:00Z'
    with pytest.raises(ValueError, match='INVALID_TIMING'):
        build_current_observation(bundle)
    bundle.prices.loc[0,'available_at']='2026-11-13 00:10:00'
    with pytest.raises(ValueError, match='NAIVE_TIMESTAMP'):
        build_current_observation(bundle)


def test_loader_uses_real_bundle_and_preserves_errors(monkeypatch, tmp_path):
    calls = {}

    def fake_loader(*args, **kwargs):
        calls.update(kwargs)
        return _bundle()

    monkeypatch.setattr("quant_research.workflow.l1_current_observation.load_real_bundle", fake_loader)
    result = current_observation_for_api(tmp_path / "real.duckdb", cutoff="2026-11-13T00:20:00Z",
                                         raw_root=tmp_path / "raw", symbols=["SPY"])
    assert result["status"] == STATUS
    assert calls["source"] == "alpaca"
    assert calls["raw_root"] == tmp_path / "raw"
    assert calls["symbols"] == ["SPY"]


def test_overview_falls_back_without_promoting_frozen_forecast(monkeypatch, tmp_path):
    from quant_research.workflow.l1_runtime import market_overview_for_api
    payload = build_current_observation(_bundle())
    monkeypatch.setattr('quant_research.workflow.l1_current_observation.current_observation_for_api',
                        lambda *args, **kwargs: payload)
    for horizon in (1, 3, 5):
        result = market_overview_for_api(tmp_path, horizon)
        assert result['status'] == STATUS
        assert result['horizon'] == horizon and result['forecast'] is None
        assert result['current_prediction_eligible'] is False

