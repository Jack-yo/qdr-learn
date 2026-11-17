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
                    "snapshot_complete": True, "provider": "fixture-universe",
                    "receipt_sha256": ("%064x" % 999),
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
    assert set(breadth.pit_status) == {"PIT_UNVERIFIED_CURRENT_UNIVERSE"}
    correlation = result["observations"].query("session_date == @latest_day and dimension == \"correlation\"")
    assert {"stock_dispersion_1", "downside_sync_share"} <= set(correlation.feature_id)
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


def test_breadth_rejects_mixed_universe_ids_in_a_single_session():
    bars,cutoffs,universe=sample_market()
    latest=universe.session_date.max()
    extra=universe.loc[universe.session_date.eq(latest)].copy()
    extra["universe_id"]="SECOND_UNIVERSE"
    mixed=pd.concat([universe,extra],ignore_index=True)
    result=compute_l1_market_features(bars,cutoffs,universe=mixed)
    quality=result["breadth_quality"]
    row=quality.loc[quality.session_date.eq(latest.date().isoformat())].iloc[0]
    assert row.reason=="MULTIPLE_UNIVERSE_IDS"
    assert result["observations"].loc[
        result["observations"].session_date.eq(latest.date().isoformat()) &
        result["observations"].dimension.eq("breadth")
    ].empty


def test_breadth_moving_average_shares_exclude_missing_ma_from_denominator():
    bars,cutoffs,universe=sample_market(n=280,members=100)
    target=universe.session_date.max()
    missing_id=universe.loc[universe.session_date.eq(target),"security_id"].iloc[0]
    bars=bars.loc[~((bars.security_id==missing_id) &
                    (bars.session_date<target-pd.Timedelta(days=10)))]
    result=compute_l1_market_features(bars,cutoffs,universe=universe)
    row=result["observations"].loc[
        result["observations"].session_date.eq(target.date().isoformat()) &
        result["observations"].feature_id.eq("pct_above_ma20")
    ]
    assert not row.empty
    assert row.iloc[0].value==pytest.approx(100.0)

def test_fomc_days_feature_uses_published_schedule_known_at_and_stays_non_pit():
    bars,cutoffs,_=sample_market(n=30,members=30)
    target=cutoffs.session_date.iloc[-1]
    cutoff=cutoffs.decision_cutoff_utc.iloc[-1]
    scheduled=target+pd.Timedelta(days=30)
    events=pd.DataFrame([{
        "event_id":"FOMC|"+scheduled.date().isoformat(),
        "event_type":"FOMC",
        "scheduled_at":(scheduled+pd.Timedelta(hours=23,minutes=59)).tz_localize("UTC"),
        "schedule_known_at":cutoff-pd.Timedelta(hours=1),
        "source":"FED_FOMC_CALENDAR",
        "receipt_sha256":"a"*64,
    }])
    result=compute_l1_market_features(bars,cutoffs,events=events)
    day=target.date().isoformat()
    row=result["observations"].query(
        "session_date == @day and feature_id == 'days_to_fomc'")
    assert len(row)==1
    assert row.iloc[0].value==30
    assert row.iloc[0].pit_status=="CURRENT_SCHEDULE_NOT_HISTORICAL_PIT"

    events.loc[0,"schedule_known_at"]=cutoff+pd.Timedelta(hours=1)
    not_yet_known=compute_l1_market_features(bars,cutoffs,events=events)
    assert not not_yet_known["observations"].query(
        "session_date == @day and feature_id == 'days_to_fomc'").shape[0]
