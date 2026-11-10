"""Terminate two real offline runs in a new, verified recovery copy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import UUID, uuid4


WORKER = """
import json, os, sys, time
from pathlib import Path
folder, phase, nonce = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
def publish(name, **fields):
    path = folder / (name + ".json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pid": os.getpid(), "ppid": os.getppid(),
                               "nonce": nonce, **fields}), encoding="utf-8")
    tmp.replace(path)
publish("identity")
def pause(**fields):
    publish("barrier", phase=phase, **fields)
    time.sleep(120)
    raise RuntimeError("The isolated drill did not terminate the paused worker")
if phase == "maintenance":
    from quant_research.data.store import Warehouse
    original = Warehouse.put_prices
    def put(self, records, clock):
        inserted = original(self, records, clock)
        pause(inserted_rows=inserted, real_rows=len(records))
        return inserted
    Warehouse.put_prices = put
else:
    from quant_research.workflow import daily_observation
    original = daily_observation.generate
    def generate(root, asof):
        pause(session_date_et=asof)
        return original(root, asof)
    daily_observation.generate = generate
from quant_research.cli import main
raise SystemExit(main(["daily-ops", "--offline"]))
"""


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root, path):
    if path.resolve() != path or not path.is_relative_to(root):
        raise ValueError("Drill paths must be contained in the verified workspace")
    return path


def await_worker(path, process, nonce):
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Worker exited before {path.name}: {process.returncode}")
        if path.is_file():
            item = read(path)
            if (item["nonce"] != nonce or type(item["pid"]) is not int or item["pid"] <= 0
                    or not (item["pid"] == process.pid or item["ppid"] == process.pid)):
                raise RuntimeError("Worker identity does not match the launched process")
            return item
        time.sleep(0.1)
    raise TimeoutError(f"Worker did not reach {path.name}")


def cli(root, environment, log, args, expected):
    process = subprocess.run([sys.executable, "-m", "quant_research.cli", *args], cwd=root,
                             env=environment, capture_output=True, timeout=120, check=False)
    log.write_bytes(process.stdout + process.stderr)
    if process.returncode != expected:
        raise RuntimeError(f"{log.name} exited {process.returncode}, expected {expected}")
    return json.loads(process.stdout.splitlines()[-1])


def stage_manifest(root, folder, run_id):
    return root / "outputs" / folder / str(UUID(run_id)) / "manifest.json"


def report_ids(root, day):
    return {p.parent.name for p in (root / "outputs/daily_observations").glob("*/manifest.json")
            if read(p)["session_date_et"] == day}


def drill(root, environment, folder, phase):
    folder.mkdir()
    nonce = uuid4().hex
    daily_marker = root / "data/catalog/.daily_ops.lock"
    maint_marker = root / "data/catalog/.maintenance.lock"
    identity = None
    with (folder / "interrupted-worker.log").open("wb") as log:
        worker = subprocess.Popen([sys.executable, "-u", "-c", WORKER, str(folder), phase, nonce],
                                  cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            identity = await_worker(folder / "identity.json", worker, nonce)
            barrier = await_worker(folder / "barrier.json", worker, nonce)
            assert identity["pid"] == barrier["pid"]
            owner = read(daily_marker)
            assert owner["pid"] == identity["pid"]
            interrupted_path = stage_manifest(root, "daily_ops", owner["run_id"])
            paused = read(interrupted_path)
            day = paused["session_date_et"]
            maintenance_path = stage_manifest(root, "maintenance", paused["maintenance_run_id"])
            reports_before = report_ids(root, day)
            pending = "maintain-data" if phase == "maintenance" else "daily-observation"
            assert paused["stages"][pending]["status"] == "RUNNING"
            markers = {daily_marker: daily_marker.read_bytes()}
            if phase == "maintenance":
                assert read(maint_marker)["pid"] == identity["pid"]
                assert read(maintenance_path)["tasks"][0]["status"] == "RUNNING"
                markers[maint_marker] = maint_marker.read_bytes()
                assert barrier["real_rows"] > 0 and barrier["inserted_rows"] == 0
                blocked = cli(root, environment, folder / "live-maintenance-contender.log",
                              ["maintain-data", "--offline", "--groups", "prices", "--end", day], 4)
                assert blocked["code"] == "MAINTENANCE_LOCKED"
            else:
                assert not maint_marker.exists() and not reports_before
                assert paused["stages"]["capture"]["result"]["inserted"] is True
            blocked = cli(root, environment, folder / "live-daily-contender.log", ["daily-ops", "--offline"], 4)
            assert blocked["code"] == "DAILY_OPS_LOCKED"
            assert all(path.read_bytes() == data for path, data in markers.items())
            assert worker.poll() is None and read(daily_marker)["pid"] == identity["pid"]
            os.kill(identity["pid"], signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
            termination_code = worker.wait(timeout=20)
            assert termination_code != 0
        finally:
            if worker.poll() is None and identity is not None:
                os.kill(identity["pid"], signal.SIGTERM if os.name == "nt" else signal.SIGKILL)
                worker.wait(timeout=20)

    assert all(path.read_bytes() == data for path, data in markers.items())
    outcome = cli(root, environment, folder / "retry.log", ["daily-ops", "--offline"], 0)
    retry = read(stage_manifest(root, "daily_ops", outcome["run_id"]))
    maintenance = read(stage_manifest(root, "maintenance", retry["maintenance_run_id"]))
    old = read(interrupted_path)
    assert old["status"] == "INTERRUPTED" and old["stages"][pending]["status"] == "INTERRUPTED"
    assert retry["recovered_lock"]["run_id"] == old["run_id"]
    assert retry["recovered_lock"]["manifest_status"] == "INTERRUPTED"
    assert all(item["inserted_rows"] == 0 for item in maintenance["tasks"])
    assert retry["stages"]["capture"]["result"]["inserted"] is False
    assert not daily_marker.exists() and not maint_marker.exists()
    if phase == "maintenance":
        assert read(maintenance_path)["status"] == "INTERRUPTED"
        assert maintenance["recovered_lock"]["run_id"] == paused["maintenance_run_id"]
        assert report_ids(root, day) == reports_before
    else:
        assert old["stages"]["capture"] == paused["stages"]["capture"]
        assert retry["capture_sha256"] == paused["capture_sha256"]
        assert retry["stages"]["daily-observation"]["result"]["reused"] is False
        assert len(report_ids(root, day)) == 1
    again = cli(root, environment, folder / "repeat.log", ["daily-ops", "--offline"], 0)
    repeated = read(stage_manifest(root, "daily_ops", again["run_id"]))
    assert repeated["capture_sha256"] == retry["capture_sha256"]
    assert repeated["stages"]["capture"]["result"]["inserted"] is False
    assert repeated["stages"]["daily-observation"]["result"]["reused"] is True
    assert repeated["stages"]["daily-observation"]["result"]["run_id"] == retry["stages"]["daily-observation"]["result"]["run_id"]
    return {"phase": phase, "barrier": barrier, "live_contender_exit": 4, "termination_exit": termination_code,
            "interrupted": old, "maintenance_recovery": maintenance["recovered_lock"],
            "retry": retry, "repeat": repeated}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    restore_base = project / "outputs/ops_restore"
    root = args.restore_root.resolve()
    if root.parent != restore_base or str(UUID(root.name)) != root.name:
        raise ValueError("Use a new direct child of the local ops_restore directory")
    evidence = contained(project / "outputs/crash_recovery", args.evidence_dir.resolve())
    if evidence.parent != project / "outputs/crash_recovery":
        raise ValueError("Use a fresh evidence directory under outputs/crash_recovery")
    if read(root / "restore_verification.json")["status"] != "RESTORED_VERIFIED":
        raise ValueError("Verified restore required")
    for name in (".daily_ops.lock", ".maintenance.lock"):
        if (root / "data/catalog" / name).exists():
            raise ValueError("Recovery drill requires a quiescent restore directory")
    evidence.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, "PYTHONPATH": str(project / "src")}
    protected = ["data/real_v21.duckdb", "data/managed/close_snapshots/observations.sqlite3", "data/catalog/latest.json"]
    before = {name: digest(project / name) for name in protected}
    record = {"restore_root": str(root), "cases": [], "offline": True, "real_orders_enabled": False}
    try:
        record["cases"].append(drill(root, environment, evidence / "case1", "maintenance"))
        quarantine = contained(root, root / ("drill-quarantine-" + uuid4().hex))
        quarantine.mkdir()
        for name in ("data/managed/close_snapshots/observations.sqlite3", "outputs/daily_observations"):
            source = contained(root, root / name)
            source.rename(contained(root, quarantine / source.name))
        record["quarantine"] = str(quarantine)
        record["cases"].append(drill(root, environment, evidence / "case2", "observation"))
        assert {name: digest(project / name) for name in protected} == before
        record.update(status="VERIFIED", original_checked_files_unchanged=True)
        return 0
    except Exception as exc:
        record.update(status="BLOCKED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        write(evidence / "machine_evidence.json", record)


if __name__ == "__main__":
    raise SystemExit(main())
