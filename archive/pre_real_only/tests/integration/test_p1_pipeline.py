from datetime import timedelta
import hashlib
import json
import socket

import pyarrow.parquet as pq
import pytest

from quant_research.cli import main
from quant_research.clock import TradingClock
from quant_research.data.pipeline import fixture_records, month_ranges
from quant_research.data.quality import audit
from quant_research.data.store import Warehouse


def test_store_idempotency_parquet_and_vintages(tmp_path):
    clock = TradingClock()
    rows, _ = fixture_records(clock, "2024-11-27", "2024-11-29")
    with Warehouse(tmp_path / "research.duckdb") as store:
        assert store.put_prices(rows, clock) == 40
        assert store.put_prices(rows, clock) == 0
        assert store.count("prices_daily") == 40
        original = rows[0]
        revised = original.model_copy(update={"close": original.open, "available_at": original.available_at + timedelta(days=3),
            "ingested_at": original.ingested_at + timedelta(days=3), "raw_sha256": hashlib.sha256(b"revision").hexdigest()})
        assert store.put_prices([revised], clock) == 1
        old = store.prices("SYNTHETIC_FIXTURE", "fixture", cutoff=original.available_at).to_pylist()
        assert next(r for r in old if r["security_id"] == original.security_id)["close"] == original.close
        latest = store.prices("SYNTHETIC_FIXTURE", "fixture").to_pylist()
        assert next(r for r in latest if r["security_id"] == original.security_id)["close"] == original.open
        reverted = original.model_copy(update={"available_at": original.available_at + timedelta(days=4),
                                               "ingested_at": original.ingested_at + timedelta(days=4)})
        assert store.put_prices([reverted], clock) == 0
        reverted_view = store.prices("SYNTHETIC_FIXTURE", "fixture").to_pylist()
        assert next(r for r in reverted_view if r["security_id"] == original.security_id)["close"] == original.close
        corrected_view = store.prices("SYNTHETIC_FIXTURE", "fixture", revised.available_at).to_pylist()
        assert next(r for r in corrected_view if r["security_id"] == original.security_id)["close"] == revised.close
        path = store.export_prices(tmp_path / "silver", "SYNTHETIC_FIXTURE", "fixture")
        assert pq.read_table(path).num_rows == 40
        assert store.prices("ALPACA", "iex").num_rows == 0


def test_invalid_batch_atomic_and_audit_gaps(tmp_path):
    clock = TradingClock()
    rows, _ = fixture_records(clock, "2024-11-27", "2024-11-29")
    with Warehouse(tmp_path / "research.duckdb") as store:
        with pytest.raises(ValueError, match="Duplicate"):
            store.put_prices([rows[0], rows[0]], clock)
        assert store.count("prices_daily") == 0
        store.put_prices(rows[:1], clock)
        report = audit(store, clock, ["SPY", "IWM"], "2024-11-27", "2024-11-29", "SYNTHETIC_FIXTURE", "fixture")
        assert report["missing_sessions"] == 3
        assert not report["coverage_complete"]
        assert not report["research_grade"]
        assert store.count("prices_daily") == 1


def test_fixture_ingestion_cli_offline_twice(tmp_path, monkeypatch):
    def forbidden(*_):
        raise AssertionError("No network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    args = ["--db", str(tmp_path / "research.duckdb"), "--data-dir", str(tmp_path / "data"), "--output", str(tmp_path / "out")]
    for _ in range(2):
        assert main(["ingest", "--source", "fixture", "--start", "2024-11-01", "--end", "2024-12-06", "--offline", *args]) == 0
    manifests = [json.loads(p.read_text()) for p in (tmp_path / "out").glob("*/manifest.json")]
    assert sorted(m["inserted_rows"] for m in manifests) == [0, 500]
    assert all(m["rows"] == 500 for m in manifests)
    assert manifests[0]["data_sha256"] == manifests[1]["data_sha256"]
    assert all(not m["research_grade"] for m in manifests)
    assert len(list((tmp_path / "out").glob("*/audit.html"))) == 2


def test_failed_ingest_records_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    code = main(["ingest", "--start", "2024-11-27", "--end", "2024-11-27", "--symbols", "SPY",
                 "--db", str(tmp_path / "research.duckdb"), "--output", str(tmp_path / "out")])
    assert code == 3
    manifest = json.loads(next((tmp_path / "out").glob("*/manifest.json")).read_text())
    assert manifest["status"] == "FAILED"
    assert manifest["table_counts"]["prices_daily"] == 0


def test_monthly_restart_chunks():
    assert list(month_ranges("2024-01-30", "2024-03-01")) == [
        ("2024-01-30", "2024-01-31"), ("2024-02-01", "2024-02-29"), ("2024-03-01", "2024-03-01")]


def test_real_feed_separation_and_historical_availability(tmp_path):
    from datetime import datetime, timezone
    clock = TradingClock()
    fixture, _ = fixture_records(clock, "2024-11-27", "2024-11-27")
    values = fixture[0].model_dump()
    now = datetime.now(timezone.utc)
    from quant_research.data.schema import PriceRecord
    iex = PriceRecord.model_validate({**values, "source": "ALPACA", "feed": "iex", "availability_basis": "first_observed",
                                    "available_at": now, "ingested_at": now})
    sip = PriceRecord.model_validate({**iex.model_dump(), "feed": "sip", "close": iex.open})
    with Warehouse(tmp_path / "research.duckdb") as store:
        assert store.put_prices([iex, sip], clock) == 2
        assert store.prices("ALPACA", "iex").num_rows == 1
        assert store.prices("ALPACA", "sip").num_rows == 1
        assert store.prices("ALPACA", "iex", cutoff=clock.signal("2024-11-27")).num_rows == 0
