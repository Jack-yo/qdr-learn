"""Deterministic contracts for the scoped L1 benchmark history sync."""
from datetime import datetime, timezone
import hashlib

import pytest

from quant_research.clock import TradingClock
from quant_research.data.l1_light_sources import SourceUnavailable
from quant_research.workflow.l1_benchmark_history import (
    BENCHMARK_SYMBOLS, BAR_PROVIDER, sync_benchmark_history,
)


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class FakeSources:
    def __init__(self, *, fred_blocked=False):
        self.bar_calls = []
        self.fred_blocked = fred_blocked

    def bars(self, *, days, symbols, start_date, end_date, adjustment,
             history_feed=None, refresh=False):
        self.bar_calls.append({
            "days": days, "symbols": tuple(symbols), "start_date": start_date,
            "end_date": end_date, "adjustment": adjustment,
            "history_feed": history_feed, "refresh": refresh,
        })
        clock = TradingClock()
        sessions = [x.date().isoformat() for x in clock.calendar.sessions
                    if start_date <= x.date().isoformat() <= end_date]
        raw = {}
        for j, symbol in enumerate(symbols):
            rows = []
            for i, day in enumerate(sessions):
                close = 100.0 + j + i * 0.01
                rows.append({
                    "t": day + "T21:00:00Z", "o": close - 0.2,
                    "h": close + 0.5, "l": close - 0.5, "c": close,
                    "v": 100000 + i, "vw": close, "n": 1000 + i,
                })
            raw[symbol] = rows
        receipt = {
            "fetched_at": "2026-11-17T23:00:00+00:00",
            "sha256": _digest(start_date + end_date + str(len(symbols))),
            "feed": history_feed or "sip", "adjustment": adjustment,
            "start": start_date, "end": end_date, "page": 1,
        }
        return raw, [receipt]

    def cboe_vix(self, *, refresh=False):
        return {
            "2026-11-13": 20.0, "2026-11-16": 21.0, "2026-11-17": 19.5,
        }, {
            "fetched_at": "2026-11-17T23:00:00+00:00",
            "sha256": _digest("vix"), "source": "CBOE_VIX",
            "pit": "CURRENT_VINTAGE",
        }

    def fred(self, series_id, *, refresh=False, days=530):
        if self.fred_blocked:
            raise SourceUnavailable("MISSING_FRED_CREDENTIALS")
        values = {}
        base = {
            "BAMLH0A0HYM2": 3.2, "DFII10": 1.7, "T10YIE": 2.3,
            "DGS2": 3.8, "DGS10": 4.1, "SOFR": 3.9, "EFFR": 3.85,
            "DTWEXBGS": 120.0,
        }[series_id]
        clock = TradingClock()
        sessions = [x.date().isoformat() for x in clock.calendar.sessions
                    if "2026-10-20" <= x.date().isoformat() <= "2026-11-17"]
        for i, day in enumerate(sessions):
            values[day] = base + i * 0.01
        return values, {
            "fetched_at": "2026-11-17T23:00:00+00:00",
            "sha256": _digest("fred:" + series_id),
            "source": "FRED_" + series_id,
            "pit": "CURRENT_VINTAGE",
        }


def test_benchmark_bootstrap_is_scoped_to_28_etfs_and_persists_quality(tmp_path):
    pytest.importorskip("duckdb")
    source = FakeSources()
    result = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=False,
        now=datetime(2026, 11, 17, 23, tzinfo=timezone.utc),
        history_feed="iex",
    )
    assert result["bars"]["mode"] == "BOOTSTRAP"
    assert result["bars"]["status"] == "OBSERVED"
    assert result["bars"]["coverage"]["coverage_pct"] >= 99.5
    assert len(result["benchmark_symbols"]) == 28
    assert tuple(result["benchmark_symbols"]) == BENCHMARK_SYMBOLS
    assert source.bar_calls[0]["symbols"] == BENCHMARK_SYMBOLS
    assert source.bar_calls[0]["history_feed"] == "iex"
    assert result["historical_pit_verified"] is False
    assert result["forecast_eligible"] is False

    from quant_research.data.l1_market_store import L1MarketStore
    with L1MarketStore(tmp_path) as store:
        bars = store.read_bars(symbols=BENCHMARK_SYMBOLS)
        bars = bars.loc[bars.provider.eq(BAR_PROVIDER)]
        assert set(bars.symbol) == set(BENCHMARK_SYMBOLS)
        checks = store.conn.execute(
            "SELECT status,reason,coverage_n,expected_n "
            "FROM l1_market_quality_checks "
            "WHERE reason='CORE_BENCHMARK_HISTORY_SYNC'"
        ).fetchall()
        assert checks and checks[-1][0] == "OBSERVED"
        assert checks[-1][2] == checks[-1][3]

    from quant_research.workflow.l1_market_ingest import market_data_snapshot
    snapshot = market_data_snapshot(tmp_path)
    assert snapshot["benchmark_history"]["status"] == "OBSERVED"
    assert snapshot["benchmark_history"]["symbol_count"] == 28
    assert snapshot["benchmark_history"]["coverage_pct"] >= 99.5
    assert snapshot["benchmark_history"]["historical_pit_verified"] is False


def test_second_sync_is_incremental_with_small_overlap(tmp_path):
    pytest.importorskip("duckdb")
    source = FakeSources()
    now = datetime(2026, 11, 17, 23, tzinfo=timezone.utc)
    first = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=False,
        now=now, history_feed="iex")
    second = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=False,
        now=now, history_feed="iex")
    assert first["bars"]["mode"] == "BOOTSTRAP"
    assert second["bars"]["mode"] == "INCREMENTAL"
    assert len(source.bar_calls) == 2
    assert source.bar_calls[1]["days"] <= 20
    assert second["bars"]["coverage"]["coverage_pct"] >= 99.5


def test_incremental_sync_repairs_old_historical_gap(tmp_path):
    pytest.importorskip("duckdb")
    source = FakeSources()
    now = datetime(2026, 11, 17, 23, tzinfo=timezone.utc)
    sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=False,
        now=now, history_feed="iex")

    from quant_research.data.l1_market_store import L1MarketStore
    with L1MarketStore(tmp_path) as store:
        gap = store.conn.execute(
            "SELECT session_date FROM l1_market_bars "
            "WHERE provider=? AND symbol='SPY' ORDER BY session_date "
            "LIMIT 1 OFFSET 30", [BAR_PROVIDER]).fetchone()[0]
        gap_day = gap.date().isoformat() if hasattr(gap, "date") else str(gap)[:10]
        store.conn.execute(
            "DELETE FROM l1_market_bars WHERE provider=? AND symbol='SPY' "
            "AND session_date=?", [BAR_PROVIDER, gap_day])

    repaired = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=False,
        now=now, history_feed="iex")
    assert repaired["bars"]["mode"] == "GAP_REPAIR"
    assert repaired["bars"]["repairing_gap_from"] == gap_day
    assert repaired["bars"]["request_start"] <= gap_day
    assert repaired["bars"]["coverage"]["coverage_pct"] >= 99.5


def test_macro_history_is_current_download_not_historical_pit(tmp_path):
    pytest.importorskip("duckdb")
    source = FakeSources()
    result = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=True,
        now=datetime(2026, 11, 17, 23, tzinfo=timezone.utc),
        history_feed="iex")
    assert result["macro"]["status"] == "OBSERVED"
    for key in ("vix_close", "hy_oas", "real_yield_10y", "breakeven_10y",
                "treasury_2y_pct", "treasury_10y_pct", "treasury_2s10s_bp",
                "sofr_pct", "effr_pct", "sofr_effr_spread_bp", "dxy_return_5"):
        assert result["macro"]["series"][key] > 0

    from quant_research.data.l1_market_store import L1MarketStore
    with L1MarketStore(tmp_path) as store:
        refs = store.read_reference_series(feature_ids=[
            "vix_close", "hy_oas", "dxy_return_5", "treasury_2s10s_bp"])
        assert not refs.empty
        assert refs.pit_status.eq(
            "CURRENT_VINTAGE_NOT_HISTORICAL_PIT").all()
        assert refs.available_at.astype(str).str.startswith(
            "2026-11-17 23:00:00").all()
        # Reference history is intentionally isolated from live observation
        # coverage and cannot silently become a model input.
        obs = store.read_observations()
        assert not obs.feature_id.isin(
            ["vix_close", "hy_oas", "dxy_return_5", "treasury_2s10s_bp"]).any()
        status = store.status()
        assert status["reference_series"]["series"] >= 4


def test_missing_fred_does_not_block_etf_history_or_vix(tmp_path):
    pytest.importorskip("duckdb")
    source = FakeSources(fred_blocked=True)
    result = sync_benchmark_history(
        tmp_path, years=3, sources=source, include_macro=True,
        now=datetime(2026, 11, 17, 23, tzinfo=timezone.utc),
        history_feed="iex")
    assert result["bars"]["status"] == "OBSERVED"
    assert result["macro"]["status"] == "PARTIAL"
    assert result["macro"]["series"]["vix_close"] == 3
    assert result["macro"]["blocked"]["hy_oas"] == "MISSING_FRED_CREDENTIALS"
    assert result["status"] == "PARTIAL"
