from pathlib import Path

import pytest

from quant_research.real_acceptance import classify, commands, freeze_database
from quant_research.data.store import duckdb


def test_free_acceptance_does_not_award_execution_or_missing_evidence():
    assert classify("P5", 0, {"status":"SUCCESS"}) == "DATA_BLOCKED"
    assert classify("P6", 0, {"status":"SUCCESS"}) == "DATA_BLOCKED"
    assert classify("P4", 0, {"prediction_rows":0}) == "DATA_BLOCKED"
    assert classify("P3", 2, {}) == "FAILED"
    assert classify("P2", 0, {}) == "FAILED_MISSING_MANIFEST"
    assert classify("P1", 0, {"coverage_complete":False}) == "DATA_BLOCKED"


def test_stages_keep_real_source_and_sealed_research():
    steps = commands(Path("snapshot.duckdb"),Path("outputs"),"2026-11-06")
    assert [p for p,_ in steps] == ["P1","P2","P3","P4","P5","P6"]
    for stage, command in steps:
        assert command[command.index("--source")+1] == "yahoo"
        assert "--experiment" not in command  # Frozen baseline defaults.
        assert "paper-step" not in command
        if stage in ("P2","P3","P4"):
            assert "--end" not in command and "--asof" not in command


def test_snapshot_refuses_missing_synthetic_only_and_wal(tmp_path):
    source, target = tmp_path/"source.duckdb", tmp_path/"copy.duckdb"
    with pytest.raises(ValueError): freeze_database(source,target)
    with duckdb.connect(str(source)) as db:
        db.execute("CREATE TABLE prices_daily(source VARCHAR)")
        db.execute("INSERT INTO prices_daily VALUES ('SYNTHETIC_FIXTURE')")
    with pytest.raises(ValueError,match="fixture fallback"):
        freeze_database(source,target)
    with duckdb.connect(str(source)) as db:
        db.execute("INSERT INTO prices_daily VALUES ('YAHOO')")
    Path(str(source)+".wal").write_bytes(b"uncheckpointed")
    with pytest.raises(ValueError,match="WAL"):
        freeze_database(source,target)
    Path(str(source)+".wal").unlink()
    assert freeze_database(source,target)
    with duckdb.connect(str(target),read_only=True) as db:
        assert db.execute("SELECT count(*) FROM prices_daily").fetchone()[0] == 2
    with pytest.raises(ValueError,match="exists"):
        freeze_database(source,target)
