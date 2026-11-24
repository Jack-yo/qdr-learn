"""Background task runner with single-task locking for the loopback console."""

import secrets
import subprocess
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

from quant_research.app.services.data_queries import action_commands
from quant_research.data.bundle import load_real_bundle
from quant_research.policy import PolicyError


class TaskRunner:
    """Run one approved research task at a time and retain a safe status record."""

    _VALID_ACTIONS = frozenset(
        {
            "refresh",
            "market",
            "factors",
            "daily",
            "daily-observation",
            "acceptance",
            "market-model",
            "alpha-model",
            "maintain-daily",
            "style-report",
            "market-research-yahoo",
            "alpha-research-yahoo",
            "close-snapshot",
            "asset-universe",
        }
    )

    def __init__(self, root: Path, source: str = "alpaca", database: Path | None = None):
        self.root = root.resolve()
        self.source = source
        self.database = database or self.root / (
            "data/real_v21.duckdb" if source == "alpaca" else "data/research.duckdb"
        )
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.job: dict = {"status": "IDLE"}

    @property
    def is_busy(self) -> bool:
        return self.lock.locked()

    def _maintenance_locked(self) -> bool:
        return (self.root / "data/catalog/.maintenance.lock").is_file()

    def start_experiment(self, identifier: str) -> bool:
        from quant_research.research.factor_lab import Registry, valid_id

        identifier = valid_id(identifier)
        if self._maintenance_locked():
            raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance is running")
        experiment = Registry(self.root).experiment(identifier)
        if experiment["status"] != "CREATED":
            raise PolicyError("EXPERIMENT_FINALIZED", "Create a new experiment to preserve prior results")
        if not self.lock.acquire(blocking=False):
            return False
        self.job = {
            "status": "RUNNING",
            "action": "factor-experiment",
            "experiment_id": identifier,
            "started_at": datetime.now(UTC).isoformat(),
            "log_path": f"outputs/factor_lab/jobs/{identifier}.log",
        }
        threading.Thread(target=self._run_experiment, args=(identifier,), daemon=True).start()
        return True

    def _run_experiment(self, identifier: str) -> None:
        log = self.root / self.job["log_path"]
        log.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log.open("w", encoding="utf-8") as stream:
                code = subprocess.run(
                    [sys.executable, "-m", "quant_research.cli", "factor-lab-run", "--experiment-id", identifier],
                    cwd=self.root,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    timeout=3600,
                    shell=False,
                ).returncode
            self.job = {
                **self.job,
                "status": "COMPLETED" if code == 0 else "DATA_BLOCKED_NO_ADVICE" if code == 4 else "FAILED",
                "exit_codes": [code],
            }
        except Exception as exc:
            self.job = {**self.job, "status": "FAILED", "error": type(exc).__name__}
        finally:
            self.lock.release()

    def start(self, action: str) -> bool:
        if self._maintenance_locked():
            raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance is running; no concurrent workflow allowed")
        if action not in self._VALID_ACTIONS:
            raise ValueError("Unknown action")
        if self.lock.locked():
            return False
        if action in {"market", "factors", "market-model", "alpha-model"}:
            bundle = load_real_bundle(self.database, self.source, raw_root=self.root / "data/raw")
            bundle.require("exploratory_price_factors")
        if not self.lock.acquire(blocking=False):
            return False
        self.job = {"status": "RUNNING", "action": action, "started_at": datetime.now(UTC).isoformat()}
        threading.Thread(target=self._run, args=(action,), daemon=True).start()
        return True

    def _run(self, action: str) -> None:
        log = self.root / "outputs/real/console.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log.open("w", encoding="utf-8") as stream:
                codes = []
                for command in action_commands(action, self.source, self.database):
                    if action == "acceptance":
                        command = ["bundle-audit", "--source", self.source, "--db", str(self.database)]
                    code = subprocess.run(
                        [sys.executable, "-m", "quant_research.cli", *command],
                        cwd=self.root,
                        stdout=stream,
                        stderr=subprocess.STDOUT,
                        timeout=21600 if action == "acceptance" else 3600,
                        shell=False,
                    ).returncode
                    codes.append(code)
                    if code:
                        break
            self.job = {
                **self.job,
                "status": "COMPLETED" if codes[-1] == 0 else "DATA_BLOCKED_NO_ADVICE" if codes[-1] == 4 else "FAILED",
                "exit_codes": codes,
            }
        except Exception as exc:
            self.job = {**self.job, "status": "FAILED", "error": type(exc).__name__}
        finally:
            self.lock.release()
