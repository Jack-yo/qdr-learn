"""Deterministic contracts for the six-system L1 feature engine."""
import numpy as np
import pandas as pd
import pytest

from quant_research.research.l1_market_features import (
    compute_forward_path_labels, compute_l1_market_features,
)


def sample_market(n=280, members=40):
    days = pd.bdate_range("2025-01-02", periods=n)
    symbols = ["SPY", "XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
               "XLP", "XLRE", "XLU", "XLV", "XLY", "IWM", "IWB"] + [
                   f"STK{i:03d}" for i in range(members)]
    bars, universe = [], []
    for j, symbol in enumerate(symbols):
        for i, day in enumerate(days):
            base = 100 + i * (0.03 + (j % 5) * 0.002) + np.sin(i/9+j)*0.15
            bars.append({
                "session_date": day, "security_id": "ID:"+symbol, "symbol": symbol,
                "open": base*0.999, "high": base*1.01, "low": base*0.99,
                "close": base, "volume": 10000+j*20+i,
                "available_at": (day+pd.Timedelta(hours=22)).tz_localize("UTC"),
                "provider": "fixture-provider", "price_basis": "raw",
                "receipt_sha256": ("%064x" % (j+1)),
            })
            if symbol.startswith("STK"):
                universe.append({
                    "session_date": day, "universe_id": "CURRENT_SAMPLE",
                    "security_id": "ID:"+symbol, "symbol": symbol, "is_member": True,
                    "known_at": (day+pd.Timedelta(hours=20)).tz_localize("UTC"),
                    "snapshot_complete": True,
                })
    cutoffs = pd.DataFrame({
        "session_date": days,
        "decision_cutoff_utc": days.tz_localize("UTC")+pd.Timedelta(hours=23),
    })
    return pd.DataFrame(bars), cutoffs, pd.DataFrame(universe)


def test_market_engine_computes_price_volatility_and_sector_features():
    bars, cutoffs, universe = sample_market()
    result = compute_l1_market_features(bars, cutoffs)
    values = result["observations"]
    latest = values.loc[values.session_date.eq(cutoffs.session_date.iloc[-1].date().isoformat())]
    assert {"spy_return_5","rv20","downside_rv20","sector_dispersion_5"} <= set(latest.feature_id)
    assert result["policy"]["forecast_eligible"] is False
    assert not result["security_features"].empty


def test_breadth_requires_explicit_complete_snapshot_and_remains_unverified_pit():
    bars, cutoffs, universe = sample_market()
    result = compute_l1_market_features(bars, cutoffs, universe=universe)
    latest_day = cutoffs.session_date.iloc[-1].date().isoformat()
    breadth = result["observations"].query("session_date == @latest_day and dimension == 'breadth'")
    assert "advances" in set(breadth.feature_id)
    assert set(breadth.pit_status) == {"CURRENT_SNAPSHOT_ONLY"}
    assert not any(breadth.get("model_eligible", []))
    incomplete = universe.copy()
    incomplete["snapshot_complete"] = False
    blocked = compute_l1_market_features(bars, cutoffs, universe=incomplete)
    assert blocked["observations"].query("dimension == 'breadth'").empty
    assert (blocked["breadth_quality"].status == "PARTIAL").any()


def test_late_market_bars_are_rejected_not_backfilled():
    bars, cutoffs, _ = sample_market(n=30, members=30)
    bars.loc[bars.index[-1], "available_at"] = pd.Timestamp("2030-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="BAR_ARRIVED_AFTER_DECISION_CUTOFF"):
        compute_l1_market_features(bars, cutoffs)


def test_path_labels_are_separate_and_same_bar_double_touch_is_ambiguous():
    bars, cutoffs, _ = sample_market(n=12, members=30)
    labels = compute_forward_path_labels(bars, cutoffs, up_barrier=0.0001, down_barrier=-0.0001)
    assert not labels.empty
    assert set(labels.status) == {"OUTCOME_ONLY_NOT_PREDICTOR"}
    assert "first_touch" in labels
