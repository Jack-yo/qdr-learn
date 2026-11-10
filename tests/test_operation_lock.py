import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from quant_research.policy import PolicyError
from quant_research.workflow.operation_lock import operation_lock


SOURCE = Path(__file__).resolve().parents[1] / "src"


def _worker(root, code, identifier):
    return subprocess.run(
        [sys.executable, "-c", code, str(root), identifier],
        env={**os.environ, "PYTHONPATH": str(SOURCE)}, capture_output=True,
        text=True, timeout=20, check=False,
    )


def test_live_process_owns_lock_and_marker_is_unchanged(tmp_path):
    marker = tmp_path / "data/catalog/.daily_ops.lock"
    with operation_lock(tmp_path, "daily_ops", "daily-ops", str(uuid4())):
        before = marker.read_bytes()
        contender = _worker(tmp_path, """
import sys
from quant_research.workflow.operation_lock import operation_lock
from quant_research.policy import PolicyError
try:
    with operation_lock(sys.argv[1], "daily_ops", "daily-ops", sys.argv[2]):
        raise SystemExit(0)
except PolicyError as exc:
    print(exc.code)
    raise SystemExit(4)
""", str(uuid4()))
        assert contender.returncode == 4 and contender.stdout.strip() == "DAILY_OPS_LOCKED"
        assert marker.read_bytes() == before
    assert not marker.exists()


@pytest.mark.parametrize("old_status", ["RUNNING", "COMPLETED"])
def test_abrupt_process_exit_releases_guard_and_preserves_completed_stages(tmp_path, old_status):
    identifier = str(uuid4())
    worker = _worker(tmp_path, f"""
import json
import os
from pathlib import Path
import sys
from quant_research.workflow.operation_lock import operation_lock
root, run_id = Path(sys.argv[1]), sys.argv[2]
with operation_lock(root, "daily_ops", "daily-ops", run_id) as ownership:
    manifest = root / "outputs" / "daily_ops" / run_id / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({{
        "status": {old_status!r}, "operation_token": ownership["token"],
        "stages": {{"capture": {{"status": "COMPLETED"}},
                   "daily-observation": {{"status": "RUNNING"}}}}
    }}), encoding="utf-8")
    os._exit(91)
""", identifier)
    assert worker.returncode == 91, worker.stderr
    old = tmp_path / "outputs/daily_ops" / identifier / "manifest.json"
    original = old.read_bytes()
    with operation_lock(tmp_path, "daily_ops", "daily-ops", str(uuid4())) as ownership:
        recovered = ownership["recovered_lock"]
        assert recovered["run_id"] == identifier
        if old_status == "RUNNING":
            assert recovered["manifest_status"] == "INTERRUPTED"
            data = json.loads(old.read_text(encoding="utf-8"))
            assert data["status"] == "INTERRUPTED"
            assert data["stages"]["capture"]["status"] == "COMPLETED"
            assert data["stages"]["daily-observation"]["status"] == "INTERRUPTED"
        else:
            assert recovered["manifest_status"] == "ALREADY_TERMINAL"
            assert old.read_bytes() == original


def test_unknown_legacy_marker_requires_review(tmp_path):
    marker = tmp_path / "data/catalog/.maintenance.lock"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"pid":1}', encoding="utf-8")
    with pytest.raises(PolicyError) as error:
        with operation_lock(tmp_path, "maintenance", "maintenance", str(uuid4())):
            pytest.fail("Legacy marker was taken over")
    assert error.value.code == "MAINTENANCE_LOCKED"
    assert marker.read_text(encoding="utf-8") == '{"pid":1}'
