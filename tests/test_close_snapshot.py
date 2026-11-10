import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from quant_research.data.bundle import load_real_bundle, verify_lineage
from quant_research.data.close_snapshot import STORE, capture, read_snapshot
from quant_research.policy import PolicyError, SYMBOLS
from quant_research.workflow.bundle_audit import timing_coverage


def test_real_capture_preserves_source_and_is_idempotent():
    root = Path.cwd()
    if not (root / STORE).is_file():
        pytest.skip("BLOCKED_NO_REAL_PREOPEN_CAPTURE")
    snapshot = read_snapshot(root, "2026-11-06")
    rows = snapshot["rows"]
    assert {row["symbol"] for row in rows} == set(SYMBOLS)
    assert len(rows) == 20
    start = datetime.fromisoformat(snapshot["capture_started_at_utc"])
    frozen = datetime.fromisoformat(snapshot["frozen_at_utc"])
    next_open = datetime.fromisoformat(snapshot["next_open_utc"])
    assert all(datetime.fromisoformat(row["event_time"]) <= datetime.fromisoformat(row["available_at"])
               <= start <= frozen < next_open for row in rows)
    assert snapshot["published_at_utc"] is None
    assert not snapshot["decision_eligible"] and not snapshot["execution_ready"]
    assert capture(root, "2026-11-06") == (snapshot, False)


def test_snapshot_rejects_after_open_and_detects_corruption(tmp_path):
    with pytest.raises(PolicyError) as error:
        capture(tmp_path, "2024-12-31")
    assert error.value.code == "CLOSE_WINDOW_EXPIRED"
    assert not (tmp_path / STORE).exists()
    if not STORE.is_file():
        pytest.skip("BLOCKED_NO_REAL_PREOPEN_CAPTURE")
    target = tmp_path / STORE
    target.parent.mkdir(parents=True)
    shutil.copyfile(STORE, target)
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("UPDATE snapshots SET payload = '{}'")
    with pytest.raises(PolicyError) as error:
        read_snapshot(tmp_path)
    assert error.value.code == "CLOSE_SNAPSHOT_HASH_MISMATCH"


def test_receipt_timestamp_is_exact_and_does_not_backfill_history():
    db = Path("data/real_v21.duckdb")
    if not db.is_file():
        pytest.skip("BLOCKED_REAL_SIP_DATABASE_UNAVAILABLE")
    bundle = load_real_bundle(db, asof="2024-12-31", start="2024-12-31")
    frame = bundle.prices
    audit = timing_coverage(frame)
    assert audit.selected_rows.sum() == 20
    assert audit.known_at_signal.sum() == 0
    assert audit.known_before_next_open.sum() == 0
    assert audit.permanent_identity_unverified.sum() == 20
    frame["available_at"] += pd.Timedelta(microseconds=1)
    frame["ingested_at"] += pd.Timedelta(microseconds=1)
    with pytest.raises(PolicyError) as error:
        verify_lineage(frame, Path("data/raw"))
    assert error.value.code == "AVAILABILITY_EVIDENCE_MISMATCH"
