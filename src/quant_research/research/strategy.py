"""Immutable strategy configuration backed by verified research dependencies."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, model_validator

from quant_research.models.settings import load_settings, SystemConfig
from quant_research.policy import PolicyError
from quant_research.research.factor_lab import canonical, fingerprint, valid_id
from quant_research.workflow.factor_lab import result as factor_result


STORE = Path("data/managed/strategies/registry.sqlite3")


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    factor_experiment_id: str
    parent_version_id: str | None = None
    horizon: StrictInt
    max_stock_weight: StrictFloat = Field(gt=0, le=0.10)
    max_total_weight: StrictFloat = Field(gt=0, le=0.50)
    max_sector_weight: StrictFloat = Field(gt=0, le=0.25)
    minimum_adv20: StrictFloat = Field(ge=20_000_000, allow_inf_nan=False)
    stop_atr_multiple: StrictFloat = Field(ge=2, le=20, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_limits(self):
        if self.horizon not in (1, 3, 5):
            raise ValueError("Unsupported holding horizon")
        valid_id(self.factor_experiment_id)
        if self.parent_version_id is not None:
            valid_id(self.parent_version_id)
        if self.max_stock_weight > min(self.max_total_weight, self.max_sector_weight):
            raise ValueError("Single security limit exceeds portfolio or sector limit")
        return self


def research_dependency(root, identifier, horizon):
    evaluated = factor_result(root, identifier)
    if evaluated["status"] != "COMPLETED":
        raise PolicyError("FACTOR_EXPERIMENT_NOT_COMPLETE", "The selected factor experiment must be complete")
    result = evaluated["result"]
    if (result["source"] != "YAHOO" or result.get("historical_decision_eligible") is not False
            or result.get("sealed_test_used") is not False or not result.get("source_provenance")
            or result.get("config_sha256") != evaluated["experiment"]["config_sha256"]):
        raise PolicyError("STRATEGY_FACTOR_SCOPE_REJECTED", "Only the reviewed Yahoo retrospective experiments are supported")
    if not any(row["partition"] == "validation" and row["horizon"] == horizon
               and row.get("rank_ic_mean") is not None for row in result["summary"]):
        raise PolicyError("FACTOR_HORIZON_UNAVAILABLE", "Selected horizon has no evaluable validation factor result")
    version = result["factor_version"]
    return {
        "experiment_id": identifier, "factor_version_id": version["id"],
        "factor_name": version["name"], "factor_version": version["version"],
        "factor_sha256": version["config_sha256"], "experiment_sha256": result["config_sha256"],
        "snapshot_sha256": result["data_sha256"], "result_sha256": fingerprint(result),
        "source": result["source"], "adjustment_basis": result["adjustment_basis"],
        "report_path": evaluated["report_path"],
        "historical_decision_eligible": False,
    }


class StrategyRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.path = self.root / STORE

    @contextmanager
    def _connect(self, *, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=15)
        else:
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=15)
        with closing(connection) as db, db:
            db.row_factory = sqlite3.Row
            if write:
                db.execute("""CREATE TABLE IF NOT EXISTS strategy_versions (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
                    config TEXT NOT NULL, config_sha256 TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL, frozen_at_utc TEXT,
                    UNIQUE(name,version)
                )""")
            yield db

    def _record(self, row):
        if row is None:
            raise PolicyError("STRATEGY_NOT_FOUND", "Strategy version is unavailable")
        record = dict(row)
        configuration = json.loads(record["config"])
        if fingerprint(configuration) != record["config_sha256"]:
            raise PolicyError("STRATEGY_CONFIG_CORRUPT", "Frozen configuration SHA256 mismatch")
        return {**record, "config": configuration,
                "status": "FROZEN" if record["frozen_at_utc"] else "DRAFT"}

    def versions(self):
        if not self.path.is_file():
            return []
        with self._connect() as db:
            return [self._record(row) for row in db.execute(
                "SELECT * FROM strategy_versions ORDER BY created_at_utc DESC"
            )]

    def get(self, identifier):
        identifier = valid_id(identifier)
        if not self.path.is_file():
            raise PolicyError("STRATEGY_NOT_FOUND", "Strategy version is unavailable")
        with self._connect() as db:
            return self._record(db.execute(
                "SELECT * FROM strategy_versions WHERE id=?", [identifier]
            ).fetchone())

    def create(self, body):
        spec = StrategySpec.model_validate(body)
        base = load_settings(self.root / "configs/experiments/baseline.yaml")
        limits = spec.model_dump(include={
            "max_stock_weight", "max_total_weight", "max_sector_weight",
            "minimum_adv20", "stop_atr_multiple",
        })
        protocol = SystemConfig.model_validate({**base.model_dump(), **limits})
        dependency = research_dependency(self.root, valid_id(spec.factor_experiment_id), spec.horizon)
        configuration = {
            "strategy": spec.model_dump(), "factor_dependency": dependency,
            "protocol": protocol.model_dump(mode="json"),
            "universe": "EXPLICIT_ETF_RESEARCH_SCOPE_ONLY",
            "entry_rule": "NEXT_SESSION_OPEN", "exit_rule": "HORIZON_CLOSE_OR_ATR_STOP",
            "ranking_rule": "DESCENDING_SELECTED_FACTOR_VALUE",
            "historical_decision_eligible": False,
        }
        identifier = str(uuid4())
        with self._connect(write=True) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT max(version) FROM strategy_versions WHERE name=?", [spec.name]).fetchone()[0]
            if spec.parent_version_id:
                parent = self._record(db.execute(
                    "SELECT * FROM strategy_versions WHERE id=?", [valid_id(spec.parent_version_id)]
                ).fetchone())
                if parent["name"] != spec.name:
                    raise ValueError("Copied strategies must retain their name")
            elif previous is not None:
                raise ValueError("Name already exists. Copy an existing version to revise it.")
            db.execute("INSERT INTO strategy_versions VALUES (?,?,?,?,?,?,NULL)", [
                identifier, spec.name, (previous or 0) + 1, canonical(configuration),
                fingerprint(configuration), datetime.now(timezone.utc).isoformat(),
            ])
        return self.get(identifier)

    def validate(self, identifier):
        item = self.get(identifier)
        config = item["config"]
        spec = StrategySpec.model_validate(config["strategy"])
        SystemConfig.model_validate(config["protocol"])
        current = research_dependency(self.root, valid_id(spec.factor_experiment_id), spec.horizon)
        if current != config["factor_dependency"]:
            raise PolicyError("STRATEGY_DEPENDENCY_CHANGED", "Factor research evidence no longer matches the saved configuration")
        return {"strategy": item, "status": "CONFIG_VALID",
                "research_dependency": "RETROSPECTIVE_ONLY", "execution_ready": False}

    def freeze(self, identifier):
        item = self.validate(identifier)["strategy"]
        if item["status"] == "FROZEN":
            return item
        with self._connect(write=True) as db:
            db.execute("""UPDATE strategy_versions SET frozen_at_utc=?
                          WHERE id=? AND config_sha256=? AND frozen_at_utc IS NULL""", [
                datetime.now(timezone.utc).isoformat(), item["id"], item["config_sha256"],
            ])
        frozen = self.get(identifier)
        if frozen["status"] != "FROZEN" or frozen["config_sha256"] != item["config_sha256"]:
            raise PolicyError("STRATEGY_FREEZE_CONFLICT", "The strategy changed during freeze")
        return frozen
