"""Explicit immutable-version pointer for the Alpha strategy used by L3 daily research."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from quant_research.policy import PolicyError
from quant_research.research.factor_lab import fingerprint, valid_id
from quant_research.research.strategy import StrategyRegistry


_ACTIVE = Path("data/managed/strategies/active.json")
_SCHEMA = "qdr.l3.active-strategy.v1"


def _path(root) -> Path:
    return Path(root).resolve() / _ACTIVE


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def active_strategy(root) -> dict:
    """Read the explicitly activated frozen strategy; never select latest implicitly."""
    path = _path(root)
    if not path.is_file():
        return {
            "schema": _SCHEMA,
            "status": "NO_ACTIVE_ALPHA_STRATEGY",
            "strategy": None,
            "research_only": True,
            "execution_ready": False,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError("ACTIVE_STRATEGY_POINTER_INVALID",
                          "The active Alpha strategy pointer is unreadable") from exc
    digest = payload.pop("content_sha256", None)
    if (payload.get("schema") != _SCHEMA
            or not isinstance(digest, str)
            or digest != fingerprint(payload)
            or payload.get("research_only") is not True
            or payload.get("execution_ready") is not False):
        raise PolicyError("ACTIVE_STRATEGY_POINTER_INVALID",
                          "The active Alpha strategy pointer failed integrity checks")
    identifier = valid_id(payload.get("strategy_version_id"))
    strategy = StrategyRegistry(root).get(identifier)
    if strategy["status"] != "FROZEN":
        raise PolicyError("ACTIVE_STRATEGY_NOT_FROZEN",
                          "Only a frozen Alpha strategy may remain active")
    if strategy["config_sha256"] != payload.get("strategy_config_sha256"):
        raise PolicyError("ACTIVE_STRATEGY_CHANGED",
                          "The active strategy no longer matches its frozen configuration")
    return {
        **payload,
        "content_sha256": digest,
        "status": "ACTIVE_ALPHA_STRATEGY",
        "strategy": strategy,
    }


def activate_strategy(root, identifier: str) -> dict:
    """Point L3 at one already-frozen, dependency-validated strategy version."""
    registry = StrategyRegistry(root)
    checked = registry.validate(valid_id(identifier))
    strategy = checked["strategy"]
    if strategy["status"] != "FROZEN":
        raise PolicyError("STRATEGY_MUST_BE_FROZEN_BEFORE_ACTIVATION",
                          "Freeze the Alpha strategy version before activating it")
    payload = {
        "schema": _SCHEMA,
        "strategy_version_id": strategy["id"],
        "strategy_config_sha256": strategy["config_sha256"],
        "activated_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "execution_ready": False,
        "real_orders_enabled": False,
    }
    payload["content_sha256"] = fingerprint(payload)
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".active-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    indent=2, allow_nan=False))
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return active_strategy(root)
