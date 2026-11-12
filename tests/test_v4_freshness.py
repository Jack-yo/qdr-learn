"""The market clock and source timestamp must remain separate facts."""

from datetime import datetime, timezone

import duckdb
import pytest

from quant_research.policy import SYMBOLS
from quant_research.workflow.v4_freshness import current_v4_freshness


def _store(tmp_path, day, count, available_at):
    path = tmp_path / "data/real_v21.duckdb"
    path.parent.mkdir(parents=True)
    with duckdb.connect(str(path)) as con:
        con.execute("""CREATE TABLE prices_daily (
            symbol VARCHAR, date DATE, source VARCHAR, feed VARCHAR,
            adjustment_basis VARCHAR, available_at TIMESTAMPTZ)""")
        con.executemany("INSERT INTO prices_daily VALUES (?, ?, 'ALPACA', 'sip', 'raw', ?)",
                        [(symbol, day, available_at) for symbol in SYMBOLS[:count]])


def test_latest_completed_session_uses_new_york_close_not_local_date(tmp_path):
    _store(tmp_path, "2026-11-10", len(SYMBOLS), "2026-11-10T22:00:00Z")
    result = current_v4_freshness(tmp_path,
        now_utc=datetime(2026, 11, 12, 8, tzinfo=timezone.utc))
    assert result["asof_session"] == "2026-11-11"
    assert result["knowledge_cutoff_utc"] == "2026-11-11T21:15:00+00:00"
    assert result["modules"]["market_observation"]["freshness_status"] == "STALE"
    assert result["modules"]["L1_market_prediction"]["freshness_status"] == "BLOCKED"


def test_complete_current_bars_arriving_after_signal_are_observation_only(tmp_path):
    _store(tmp_path, "2026-11-11", len(SYMBOLS), "2026-11-12T08:00:00Z")
    result = current_v4_freshness(tmp_path,
        now_utc=datetime(2026, 11, 12, 8, 5, tzinfo=timezone.utc))
    observed = result["modules"]["market_observation"]
    assert observed["freshness_status"] == "CURRENT"
    assert observed["known_by_decision_cutoff"] is False
    assert "PRICE_ARRIVED_AFTER_DECISION_CUTOFF" in result["modules"]["L1_market_prediction"]["blocked_reason"]


def test_incomplete_or_naive_clock_fails_closed(tmp_path):
    _store(tmp_path, "2026-11-11", len(SYMBOLS) - 1, "2026-11-11T21:05:00Z")
    result = current_v4_freshness(tmp_path,
        now_utc=datetime(2026, 11, 12, 8, tzinfo=timezone.utc))
    assert result["modules"]["market_observation"]["freshness_status"] == "STALE"
    with pytest.raises(ValueError, match="Timezone-aware"):
        current_v4_freshness(tmp_path, now_utc=datetime(2026, 11, 12, 8))


def test_future_source_arrival_is_not_available_yet(tmp_path):
    _store(tmp_path, "2026-11-11", len(SYMBOLS), "2026-11-12T09:00:00Z")
    result = current_v4_freshness(tmp_path,
        now_utc=datetime(2026, 11, 12, 8, tzinfo=timezone.utc))
    assert result["latest_available_price_session"] is None
    assert result["modules"]["market_observation"]["freshness_status"] == "BLOCKED"
