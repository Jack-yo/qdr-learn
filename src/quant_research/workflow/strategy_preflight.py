"""Freeze-backed backtest admission report. Only real input evidence is inspected."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.data.bundle import load_real_bundle
from quant_research.policy import PolicyError
from quant_research.research.strategy import StrategyRegistry
from .common import report


def preflight(root, identifier):
    root = Path(root).resolve()
    registry = StrategyRegistry(root)
    strategy = registry.get(identifier)
    if strategy["status"] != "FROZEN":
        raise PolicyError("STRATEGY_NOT_FROZEN", "Freeze the validated strategy before preflight")
    registry.validate(identifier)
    config = strategy["config"]
    protocol = config["protocol"]
    checks = {
        "strategy_config": {"status": "PASS", "missing_evidence": []},
        "strategy_signal": {"status": "BLOCKED", "missing_evidence": [
            "decision-eligible factor computation and historical availability"
        ]},
        "execution_adapter": {"status": "BLOCKED", "missing_evidence": [
            "accepted real-data fill and corporate-action settlement integration"
        ]},
    }
    dataset = None
    try:
        bundle = load_real_bundle(root / "data/real_v21.duckdb", "alpaca",
                                  asof=protocol["validation_end"], start=protocol["start"],
                                  raw_root=root / "data/raw")
        dataset = bundle.metadata
        for key in ("observation", "raw_prices", "exploratory_price_factors", "historical_model",
                    "industry_factors", "historical_backtest"):
            checks[key] = bundle.capabilities[key]
    except PolicyError as exc:
        checks["historical_backtest"] = {
            "status": "BLOCKED", "code": exc.code,
            "missing_evidence": [exc.payload()["message"], *exc.missing],
        }

    run_id = str(uuid4())
    output = root / "outputs/strategy_preflight" / run_id
    output.mkdir(parents=True)
    manifest = {
        "run_id": run_id, "workflow": "strategy-preflight", "source": "ALPACA",
        "status": "BACKTEST_BLOCKED", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_version_id": strategy["id"], "strategy_config_sha256": strategy["config_sha256"],
        "strategy_frozen_at_utc": strategy["frozen_at_utc"], "strategy_config": config,
        "source_dataset": dataset, "checks": checks,
        "performance": None, "research_grade": False, "execution_ready": False,
        "real_orders_enabled": False, "sealed_test_used": False,
    }
    (output / "eligibility.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    table = pd.DataFrame([
        {"检查项": name, "状态": check["status"], "缺失证据": " / ".join(check["missing_evidence"])}
        for name, check in checks.items()
    ])
    report(output, "严格回测准入检查", manifest, {"输入证据": table},
           note="本次只核验配置和来源证据。收益、回撤、交易成本实测值及模拟成交均不可用。")
    manifest["artifacts_sha256"] = {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ("eligibility.json", "report.html")
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return {**manifest, "report_path": (output / "report.html").relative_to(root).as_posix(),
            "evidence_path": (output / "eligibility.json").relative_to(root).as_posix()}


def execute(args):
    record = preflight(Path.cwd(), args.strategy_version)
    print(json.dumps(record, ensure_ascii=False))
    return 4
