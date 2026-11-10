"""Local, allowlisted data backup and isolated recovery verification."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from uuid import UUID, uuid4

from quant_research.data.http import atomic_write
from quant_research.policy import PolicyError
from .operation_lock import operation_lock


BACKUPS = Path("outputs/ops_backups")
RESTORES = Path("outputs/ops_restore")
MANIFEST = "backup_manifest.json"
FIXED = {
    "pyproject.toml", "uv.lock", "README.md", ".gitignore", "scripts/cron.example",
    "data/catalog/latest.json", "data/real_v21.duckdb", "data/research.duckdb",
    "data/g2_evidence.duckdb", "data/g3_evidence.duckdb",
    "data/managed/corporate_actions/events.duckdb",
    "data/managed/classic_factors/factors.duckdb",
    "data/managed/factor_lab/registry.sqlite3",
    "data/managed/strategies/registry.sqlite3",
    "data/managed/close_snapshots/observations.sqlite3",
}
REQUIRED = {"pyproject.toml", "uv.lock", "configs/data_maintenance.yaml",
            "data/real_v21.duckdb", "data/catalog/latest.json"}
TREES = {
    "configs": {".yaml", ".yml", ".json"},
    "src/quant_research": {".py", ".html"},
    "scripts": {".ps1", ".sh", ".cmd", ".py"},
    "data/raw/objects": {""},
    "data/raw/receipts": {".json"},
    "data/raw/requests": {".json"},
    "data/raw/yahoo/receipts": {".json"},
    "data/raw/yahoo/requests": {".json"},
    "data/catalog/snapshots": {".json", ".csv"},
    "data/managed": {".json"},
}
REPORT_ROOTS = (
    "factor_lab", "market_research", "alpha_research", "styles",
    "strategy_preflight", "daily_observations", "maintenance", "daily_ops",
    "feature_prices", "g2", "g3",
)
REPORT_SUFFIXES = {".json", ".csv", ".parquet", ".html", ".svg"}


def _allowed(name):
    relative = PurePosixPath(name)
    if (not name or relative.as_posix() != name or relative.is_absolute()
            or "\\" in name or ":" in name or ".." in relative.parts):
        return False
    if name in FIXED:
        return True
    if any(part.startswith(".") for part in relative.parts):
        return False
    if relative.is_relative_to("data/raw/objects"):
        return relative.parent.as_posix() == "data/raw/objects" and bool(re.fullmatch(r"[a-f0-9]{64}", relative.name))
    if relative.is_relative_to("data/managed"):
        return (len(relative.parts) == 4 and relative.name == "dataset.json"
                or relative.parent.as_posix() == "data/managed/corporate_actions/snapshots"
                and bool(re.fullmatch(r"[a-f0-9]{64}\.json", relative.name)))
    if len(relative.parts) >= 4 and relative.parts[0] == "outputs" and relative.parts[1] in REPORT_ROOTS:
        try:
            UUID(relative.parts[2])
        except ValueError:
            return False
        return relative.suffix in REPORT_SUFFIXES
    return any(relative.is_relative_to(tree) and relative.suffix in suffixes
               for tree, suffixes in TREES.items())


def _safe_path(root, relative):
    path = root / relative
    if path.resolve() != path or not path.is_relative_to(root):
        raise PolicyError("OPS_PATH_REJECTED", "Backup and recovery require contained, non-linked paths")
    return path


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _inventory(root):
    candidates = {_safe_path(root, name) for name in FIXED if (root / name).is_file()}
    for tree in TREES:
        directory = _safe_path(root, tree)
        candidates.update(path for path in directory.rglob("*") if path.is_file())
    for name in REPORT_ROOTS:
        directory = _safe_path(root, f"outputs/{name}")
        for manifest in directory.glob("*/manifest.json"):
            candidates.update(path for path in manifest.parent.rglob("*") if path.is_file())
    selected = {}
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if not _allowed(relative):
            continue
        _safe_path(root, relative)
        if path.suffix in {".sqlite3", ".duckdb"}:
            if any(path.with_name(path.name + suffix).exists() for suffix in (".wal", "-wal", "-shm", "-journal")):
                raise PolicyError("OPS_DATABASE_BUSY", "Close database writers and checkpoint before backup", [relative])
        selected[relative] = _stamp(path)
    if missing := REQUIRED - selected.keys():
        raise PolicyError("OPS_INPUTS_MISSING", "Required backup inputs are unavailable", sorted(missing))
    return selected


@contextmanager
def _maintenance_pause(root, run_id):
    with operation_lock(root, "maintenance", "ops-backup", run_id, recover=False):
        if (root / "data/catalog/.daily_ops.lock").exists():
            raise PolicyError("DAILY_OPS_LOCKED", "Wait for the daily workflow to finish before backup")
        yield


def create_backup(root):
    root = Path(root).resolve()
    run_id = str(uuid4())
    output = _safe_path(root, BACKUPS / run_id)
    with _maintenance_pause(root, run_id):
        initial = _inventory(root)
        output.mkdir(parents=True, exist_ok=False)
        files = {}
        for name, stamp in sorted(initial.items()):
            source, target = _safe_path(root, name), _safe_path(output, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            digest = _hash(target)
            if _stamp(source) != stamp or target.stat().st_size != stamp[0] or _hash(source) != digest:
                raise PolicyError("OPS_SOURCE_CHANGED", "Source changed while the backup was being written", [name])
            if name.startswith("data/raw/objects/") and target.name != digest:
                raise PolicyError("OPS_RAW_OBJECT_CORRUPT", "Raw object no longer matches its content hash", [name])
            files[name] = {"bytes": stamp[0], "sha256": digest}
        if _inventory(root) != initial:
            raise PolicyError("OPS_SOURCE_CHANGED", "Source inventory changed during backup")
        result = {
            "schema": 1, "status": "BACKUP_COMPLETE", "backup_id": run_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "file_count": len(files), "bytes": sum(item["bytes"] for item in files.values()),
            "files": files, "real_orders_enabled": False,
        }
        atomic_write(output / MANIFEST, json.dumps(result, indent=2).encode())
    return output, result


def _recovery_checks(root):
    from quant_research.data.catalog import cache_inventory, catalog_artifact
    from quant_research.data.close_snapshot import read_snapshot
    from quant_research.data.bundle import load_real_bundle
    from quant_research.research.strategy import StrategyRegistry
    from quant_research.workflow.daily_observation import latest_report

    catalog = json.loads(catalog_artifact(root))
    receipts = cache_inventory(root)
    if len(receipts) != catalog["cache_receipts"] or any(not row["hash_verified"] for row in receipts):
        raise PolicyError("OPS_RESTORED_CACHE_MISMATCH", "Restored receipts differ from the catalog")
    bundle = load_real_bundle(root / "data/real_v21.duckdb", raw_root=root / "data/raw")
    bundle.require("observation")
    bundle.require("raw_prices")
    checks = {"catalog_categories": len(catalog["datasets"]), "cache_receipts": len(receipts),
              "verified_sip_rows": bundle.metadata["source_provenance"]["verified_rows"]}
    if (root / "data/research.duckdb").is_file():
        yahoo = load_real_bundle(root / "data/research.duckdb", "yahoo", "2024-12-31",
                                 raw_root=root / "data/raw")
        yahoo.require("observation")
        yahoo.require("exploratory_price_factors")
        checks["verified_yahoo_research_rows"] = yahoo.metadata["source_provenance"]["verified_rows"]
    if (root / "data/managed/close_snapshots/observations.sqlite3").is_file():
        snapshot = read_snapshot(root)
        checks["latest_capture_sha256"] = snapshot["capture_sha256"]
    if any((root / "outputs/daily_observations").glob("*/manifest.json")):
        report = latest_report(root)
        if read_snapshot(root, report["session_date_et"])["capture_sha256"] != report["capture_sha256"]:
            raise PolicyError("OPS_RESTORED_REPORT_MISMATCH", "Daily report does not match its restored capture")
        checks["daily_report_id"] = report["run_id"]
    strategies = StrategyRegistry(root)
    frozen = [row for row in strategies.versions() if row["status"] == "FROZEN"]
    for strategy in frozen:
        strategies.validate(strategy["id"])
    checks["verified_frozen_strategies"] = len(frozen)
    return checks


def restore_backup(root, backup_id):
    root = Path(root).resolve()
    backup_id = str(UUID(backup_id))
    archive = _safe_path(root, BACKUPS / backup_id)
    manifest_path = _safe_path(archive, MANIFEST)
    if not manifest_path.is_file():
        raise PolicyError("OPS_BACKUP_NOT_COMPLETE", "A completed backup manifest is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise PolicyError("OPS_BACKUP_MANIFEST_INVALID", "Backup manifest is invalid")
    files = manifest.get("files")
    if (not isinstance(files, dict) or manifest.get("schema") != 1 or manifest.get("backup_id") != backup_id
            or manifest.get("status") != "BACKUP_COMPLETE" or not REQUIRED <= files.keys()
            or len({name.casefold() for name in files}) != len(files)
            or any(not _allowed(name) for name in files)
            or any(not isinstance(item, dict) or type(item.get("bytes")) is not int
                   or item["bytes"] < 0 or not re.fullmatch(r"[a-f0-9]{64}", str(item.get("sha256")))
                   for item in files.values())):
        raise PolicyError("OPS_BACKUP_MANIFEST_INVALID", "Backup manifest does not match the reviewed scope")
    actual = {p.relative_to(archive).as_posix() for p in archive.rglob("*") if p.is_file()}
    if actual != set(files) | {MANIFEST}:
        raise PolicyError("OPS_BACKUP_FILESET_MISMATCH", "Backup file set differs from the manifest")
    output = _safe_path(root, RESTORES / str(uuid4()))
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in sorted(files.items()):
        source, target = _safe_path(archive, name), _safe_path(output, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if target.stat().st_size != expected["bytes"] or _hash(target) != expected["sha256"]:
            raise PolicyError("OPS_BACKUP_HASH_MISMATCH", "Archived file failed SHA256 verification", [name])
    result = {"status": "RESTORED_VERIFIED", "backup_id": backup_id, "file_count": len(files),
              "restored_at_utc": datetime.now(timezone.utc).isoformat(),
              "checks": _recovery_checks(output), "real_orders_enabled": False}
    atomic_write(output / "restore_verification.json", json.dumps(result, indent=2).encode())
    return output, result


def execute(args):
    if args.command == "ops-backup":
        output, record = create_backup(Path.cwd())
    else:
        output, record = restore_backup(Path.cwd(), args.backup_id)
    print(json.dumps({**{key: value for key, value in record.items() if key != "files"},
                      "output": str(output)}))
    return 0
