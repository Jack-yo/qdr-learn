import json
from pathlib import Path
import shutil

import pytest

from quant_research.policy import PolicyError
from quant_research.research.factor_lab import Registry
from quant_research.research.strategy import StrategyRegistry
from quant_research.workflow.strategy_preflight import preflight


def test_strategy_version_uses_real_evidence_and_blocks_execution(tmp_path):
    source = Registry(Path.cwd())
    if not source.path.is_file():
        pytest.skip("BLOCKED_NO_REAL_FACTOR_EXPERIMENTS")
    experiment = next((item for item in source.experiments()
                       if item["status"] == "COMPLETED" and item["config"]["source"] == "yahoo"), None)
    if experiment is None:
        pytest.skip("BLOCKED_NO_REAL_FACTOR_EXPERIMENTS")
    target = Registry(tmp_path).path
    target.parent.mkdir(parents=True)
    shutil.copyfile(source.path, target)
    artifacts = Path(experiment["result_path"])
    shutil.copytree(artifacts, tmp_path / artifacts)
    settings = Path("configs/experiments/baseline.yaml")
    (tmp_path / settings).parent.mkdir(parents=True)
    shutil.copyfile(settings, tmp_path / settings)

    registry = StrategyRegistry(tmp_path)
    spec = {"name": "real-research-review", "factor_experiment_id": experiment["id"], "horizon": 3,
            "max_stock_weight": .10, "max_total_weight": .50, "max_sector_weight": .25,
            "minimum_adv20": 20_000_000, "stop_atr_multiple": 2}
    with pytest.raises(ValueError):
        registry.create({**spec, "max_stock_weight": .11})
    with pytest.raises(ValueError):
        registry.create({**spec, "validation_end": "2025-01-02"})
    draft = registry.create(spec)
    assert draft["status"] == "DRAFT"
    with pytest.raises(PolicyError, match="Freeze"):
        preflight(tmp_path, draft["id"])
    assert registry.validate(draft["id"])["status"] == "CONFIG_VALID"
    first = registry.freeze(draft["id"])
    assert first["status"] == "FROZEN" and first["config_sha256"] == draft["config_sha256"]
    assert registry.freeze(draft["id"]) == first
    copy = registry.create({**spec, "max_total_weight": .4, "parent_version_id": first["id"]})
    assert copy["version"] == 2 and copy["config_sha256"] != first["config_sha256"]
    assert registry.get(first["id"]) == first

    outcome = preflight(tmp_path, first["id"])
    assert outcome["status"] == "BACKTEST_BLOCKED"
    assert outcome["strategy_config_sha256"] == first["config_sha256"]
    assert outcome["performance"] is None and not outcome["sealed_test_used"]
    assert outcome["checks"]["historical_backtest"]["code"] == "NO_REAL_DATA"
    assert not list((tmp_path / "outputs/strategy_preflight").glob("**/*trades*"))

    path = tmp_path / artifacts / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    del manifest["artifacts_sha256"]["result.json"]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PolicyError, match="required artifact hashes"):
        registry.freeze(first["id"])
