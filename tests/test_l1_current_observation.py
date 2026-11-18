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
    assert next(item for item in result['features'] if item['id']=='breadth_up_share')['reason']=='HISTORICAL_PIT_UNIVERSE_NOT_VERIFIED'


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
    result = current_observation_for_api(tmp_path / "real.duckdb", asof="2026-11-12", cutoff="2026-11-13T00:20:00Z",
                                         raw_root=tmp_path / "raw", symbols=["SPY"])
    assert result["status"] == STATUS
    assert calls["source"] == "alpaca"
    assert calls["raw_root"] == tmp_path / "raw"
    assert calls["symbols"] == ["SPY"]


def test_complete_xnys_etf_history_populates_registered_retrospective_metrics():
    from quant_research.clock import TradingClock
    days = TradingClock().calendar.sessions_in_range("2026-09-01", "2026-11-12").tz_localize(None)
    symbols = ["SPY", "RSP", "HYG", "LQD", "IWM"]
    rows = []
    for i, day in enumerate(days):
        for j, symbol in enumerate(symbols):
            close = 100 + i * (1 + j / 10)
            rows.append({"date": day, "symbol": symbol, "open": close - 1,
                         "high": close + 1, "low": close - 2, "close": close,
                         "available_at": f"2026-11-13T00:{i % 50:02d}:00Z",
                         "event_time": f"{day.date()}T21:00:00Z", "source": "ALPACA",
                         "feed": "sip", "adjustment_basis": "raw"})
    bundle = SimpleNamespace(prices=pd.DataFrame(rows), metadata={
        "asof_date_et": str(days[-1].date()), "knowledge_cutoff_utc": "2026-11-13T01:00:00Z",
        "source": "ALPACA", "feed": "sip", "source_version_kind": "current_revised_snapshot",
        "snapshot_sha256": "b" * 64})
    result = build_current_observation(bundle)
    values = {item["id"]: item["value"] for item in result["features"]}
    assert values["market_return_5"] is not None
    assert values["credit_proxy_relative_return_5"] is not None
    assert values["market_vol_20"] is not None
    spy=bundle.prices.loc[bundle.prices.symbol.eq('SPY')].sort_values('date').tail(26)
    returns=spy.close.pct_change(fill_method=None).iloc[1:]
    expected_change=returns.iloc[-20:].std()/returns.iloc[:20].std()-1
    assert values['market_vol_change_5']==pytest.approx(expected_change)
    assert set(result['return_windows'])=={'1','3','5','10','20'}
    assert result["source_time"]["available_at"] == "2026-11-13T00:49:00Z"
    assert all(item["reason"] == "CURRENT_VINTAGE_ETF_RETROSPECTIVE"
               for item in result["features"] if item["value"] is not None)


def test_missing_xnys_session_does_not_create_continuous_history_metric():
    from quant_research.clock import TradingClock
    days = TradingClock().calendar.sessions_in_range("2026-10-01", "2026-11-12").tz_localize(None)
    rows = [{"date": day, "symbol": "SPY", "open": 99 + i, "high": 101 + i, "low": 98 + i, "close": 100 + i,
             "available_at": "2026-11-13T00:10:00Z", "event_time": f"{day.date()}T21:00:00Z"}
             for i, day in enumerate(days) if i != 10]
    bundle = SimpleNamespace(prices=pd.DataFrame(rows), metadata={
        "asof_date_et": str(days[-1].date()), "knowledge_cutoff_utc": "2026-11-13T00:20:00Z",
        "source": "ALPACA", "feed": "sip", "source_version_kind": "current_revised_snapshot"})
    result = build_current_observation(bundle)
    features={x['id']:x for x in result['features']}
    assert features['market_return_5']['status']=='OBSERVED'
    assert features['market_return_20']['status']=='MISSING'


def test_retrospective_feature_timestamp_uses_its_actual_inputs():
    from quant_research.clock import TradingClock
    days=TradingClock().calendar.sessions_in_range('2026-10-01','2026-11-12')
    rows=[{'date':day,'symbol':'SPY','open':100+i,'high':102+i,'low':99+i,'close':101+i,
           'available_at':'2026-11-13T00:10:00Z','event_time':f'{day.date()}T21:00:00Z'}
          for i,day in enumerate(days)]
    rows[0]['available_at']='2026-11-13T01:00:00Z'
    bundle=SimpleNamespace(prices=pd.DataFrame(rows),metadata={'asof_date_et':'2026-11-12',
        'knowledge_cutoff_utc':'2026-11-13T02:00:00Z','source':'ALPACA','feed':'sip'})
    result=build_current_observation(bundle)
    feature=next(x for x in result['features'] if x['id']=='market_return_1')
    assert feature['available_at']=='2026-11-13T00:10:00Z'
    assert result['source_time']['available_at']=='2026-11-13T01:00:00Z'


def test_sector_and_credit_proxies_match_complete_etf_windows():
    import numpy as np
    from quant_research.clock import TradingClock
    from quant_research.workflow.l1_current_observation import _SECTOR_ETFS
    days=TradingClock().calendar.sessions_in_range('2026-09-15','2026-11-12')
    symbols=['SPY','RSP','HYG','LQD','IWM',*_SECTOR_ETFS]
    rows=[]
    for j,symbol in enumerate(symbols):
        values=100*np.exp(np.cumsum([.001*np.sin(i*.3+j*.2)+j*.00005 for i in range(len(days))]))
        for day,value in zip(days,values):
            rows.append({'date':day,'symbol':symbol,'open':value,'high':value*1.01,
                         'low':value*.99,'close':value,'available_at':'2026-11-13T00:10:00Z',
                         'event_time':f'{day.date()}T21:00:00Z','adjustment_basis':'raw'})
    prices=pd.DataFrame(rows)
    bundle=SimpleNamespace(prices=prices,metadata={'asof_date_et':'2026-11-12',
        'knowledge_cutoff_utc':'2026-11-13T00:20:00Z','source':'ALPACA','feed':'sip'})
    result=build_current_observation(bundle)
    features={x['id']:x for x in result['features']}
    closes=prices.pivot(index='date',columns='symbol',values='close').sort_index()
    returns=closes[list(_SECTOR_ETFS)].iloc[-21:].pct_change(fill_method=None).iloc[1:]
    matrix=returns.corr().to_numpy()
    expected_corr=matrix[np.triu_indices_from(matrix,1)].mean()
    assert features['sector_corr_20']['value']==pytest.approx(expected_corr)
    expected_dispersion=(closes[list(_SECTOR_ETFS)].iloc[-1]/closes[list(_SECTOR_ETFS)].iloc[-6]-1).std(ddof=0)
    assert features['sector_dispersion_5']['value']==pytest.approx(expected_dispersion)
    ratio=closes.HYG/closes.LQD
    assert features['credit_proxy_relative_return_5']['value']==pytest.approx(ratio.iloc[-1]/ratio.iloc[-6]-1)
    assert all(not x['research_eligible'] for x in result['features'])
    assert result['forecast'] is None


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

