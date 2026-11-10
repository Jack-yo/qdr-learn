import json
from uuid import uuid4

import pytest

from quant_research.policy import PolicyError
from quant_research.workflow.ops_backup import BACKUPS, MANIFEST, RESTORES, REQUIRED, _allowed, create_backup, restore_backup


def test_backup_scope_excludes_credentials_and_runtime():
    assert all(_allowed(name) for name in REQUIRED)
    assert _allowed("data/raw/objects/" + "a" * 64)
    assert _allowed("data/managed/close_snapshots/observations.sqlite3")
    assert not any(_allowed(name) for name in (
        ".env", "configs/.env", "data/managed/vendor/credentials.json",
        ".venv/Scripts/python.exe", "data/paper.sqlite3", "data/real_v21.duckdb.wal",
        "outputs/real/chrome-qa/Default/Network/Cookies", "../data/real_v21.duckdb",
        "/data/real_v21.duckdb", "data/raw/objects/not-a-content-hash",
    ))


def test_existing_maintenance_lock_is_preserved(tmp_path):
    lock = tmp_path / "data/catalog/.maintenance.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("existing lock", encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        create_backup(tmp_path)
    assert error.value.code == "MAINTENANCE_LOCKED"
    assert lock.read_text(encoding="utf-8") == "existing lock"
    assert not (tmp_path / BACKUPS).exists()


def test_unsafe_archive_is_rejected_before_restoring(tmp_path):
    identifier = str(uuid4())
    archive = tmp_path / BACKUPS / identifier
    archive.mkdir(parents=True)
    entry = {"bytes": 1, "sha256": "a" * 64}
    manifest = {
        "schema": 1, "status": "BACKUP_COMPLETE", "backup_id": identifier,
        "files": {name: entry for name in (*REQUIRED, "configs/../../.env")},
    }
    (archive / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        restore_backup(tmp_path, identifier)
    assert error.value.code == "OPS_BACKUP_MANIFEST_INVALID"
    assert not (tmp_path / RESTORES).exists()
