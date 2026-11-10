import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from quant_research.data.close_snapshot import STORE
from quant_research.workflow.forward_observations import inventory


def test_empty_observation_archive_is_structured_blocked(tmp_path):
    path = tmp_path / STORE
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE snapshots (session_date TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")

    result = inventory(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["observations"]["registered_count"] == 0
    assert result["observations"]["verified_displayed_count"] == 0
    assert result["account"] == {"cash": None, "equity": None, "positions": None, "fills": None}
    assert result["real_orders_enabled"] is False


def test_missing_archive_has_zero_observations_and_null_account(tmp_path):
    result = inventory(tmp_path)
    assert result["status"] == "BLOCKED"
    assert result["error"]["code"] == "NO_ARCHIVED_OBSERVATIONS"
    assert result["observations"]["observation_dates"] == []
    assert all(value is None for value in result["account"].values())


def test_existing_real_archive_is_verified():
    """Use only the repository's real archive; never fabricate market rows."""
    source = Path.cwd() / STORE
    if not source.is_file():
        pytest.skip("BLOCKED_NO_REAL_PREOPEN_CAPTURE")
    result = inventory(Path.cwd())
    assert result["status"] == "BLOCKED" and "error" not in result
    assert 1 <= result["observations"]["verified_displayed_count"] <= 20
    assert all(row["rows"] == 20 for row in result["observations"]["snapshots"])
    assert all(value is None for value in result["account"].values())
