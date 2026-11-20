import json

import pytest

from quant_research.policy import PolicyError
from quant_research.workflow import l3_strategy_activation as activation


class FakeRegistry:
    def __init__(self, root, *, status="FROZEN", multi=True):
        self.status=status
        self.multi=multi

    def validate(self, identifier):
        return {"strategy": self.get(identifier)}

    def get(self, identifier):
        return {
            "id": identifier, "name": "Alpha Mix", "version": 2,
            "status": self.status, "config_sha256": "a"*64,
            "config": {"factor_mix": {"allocations": []} if self.multi else None},
        }


def test_no_active_strategy_is_explicit_empty_state(tmp_path):
    result=activation.active_strategy(tmp_path)
    assert result["status"]=="NO_ACTIVE_ALPHA_STRATEGY"
    assert result["strategy"] is None
    assert result["execution_ready"] is False


def test_activation_writes_integrity_bound_frozen_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(activation, "StrategyRegistry", lambda root: FakeRegistry(root))
    result=activation.activate_strategy(tmp_path, "12345678-1234-1234-1234-123456789012")
    assert result["status"]=="ACTIVE_ALPHA_STRATEGY"
    assert result["strategy"]["status"]=="FROZEN"
    stored=json.loads((tmp_path/"data/managed/strategies/active.json").read_text())
    assert stored["research_only"] is True
    assert stored["real_orders_enabled"] is False
    assert len(stored["content_sha256"])==64


def test_draft_and_single_factor_strategies_cannot_become_active(tmp_path, monkeypatch):
    monkeypatch.setattr(activation, "StrategyRegistry",
                        lambda root: FakeRegistry(root, status="DRAFT"))
    with pytest.raises(PolicyError, match="Freeze"):
        activation.activate_strategy(tmp_path, "12345678-1234-1234-1234-123456789012")
    monkeypatch.setattr(activation, "StrategyRegistry",
                        lambda root: FakeRegistry(root, status="FROZEN", multi=False))
    with pytest.raises(PolicyError, match="2–8 factor"):
        activation.activate_strategy(tmp_path, "12345678-1234-1234-1234-123456789012")


def test_tampered_active_pointer_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(activation, "StrategyRegistry", lambda root: FakeRegistry(root))
    activation.activate_strategy(tmp_path, "12345678-1234-1234-1234-123456789012")
    path=tmp_path/"data/managed/strategies/active.json"
    payload=json.loads(path.read_text())
    payload["strategy_config_sha256"]="b"*64
    path.write_text(json.dumps(payload),encoding="utf-8")
    with pytest.raises(PolicyError, match="integrity"):
        activation.active_strategy(tmp_path)
