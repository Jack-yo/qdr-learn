"""QDR V5 decision-first UX contract checks."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"src"/"quant_research"

def test_v5_assets_and_navigation():
    shell=(APP/"v4_shell.html").read_text(encoding="utf-8")
    web=(APP/"web.py").read_text(encoding="utf-8")
    for asset in ("v5_system.css","v5_decision.js"):
        assert "/assets/"+asset in shell
        assert "'/assets/"+asset+"'" in web
    assert ">每日决策<" in shell
    assert ">数据与保障<" in shell
    assert ">研究准入<" in shell
    assert "PIT · 回测 · 前向研究" in shell
    assert "真实证据 · 非券商交易" not in shell

def test_v5_overview_is_decision_first():
    src=(APP/"assets"/"v5_decision.js").read_text(encoding="utf-8")
    for marker in ("每日决策","今日候选","持仓与风险","今日变化","决策上下文"):
        assert marker in src
    for endpoint in ("/api/v1/l1/market/overview?horizon=3","/api/v1/l2/styles/overview?rotation=1","/api/v1/v4/plans/"):
        assert endpoint in src
    assert "DIGEST" in src and "historical_pit_verified" in src
    assert "归档研究预测行数" not in src
    assert "前向 H3 概率预测质量" not in src
    assert "Math.random" not in src

def test_l1_uses_progressive_disclosure_for_evidence():
    src=(APP/"assets"/"v4_ui_market_v4.js").read_text(encoding="utf-8")
    for marker in ("市场展望","关键变化","12 维市场自动观测","模型验证与研究记录","market-details","market-audit"):
        assert marker in src
    assert "完成 Codex 数据接入" not in src
    assert "v4_ui_market_v2" not in src
    assert "lv3-" not in src

def test_v5_visual_system_is_restrained():
    css=(APP/"assets"/"v5_system.css").read_text(encoding="utf-8")
    for marker in (".desk-tape",".desk-layout",".desk-table",".desk-context-list"):
        assert marker in css
    assert ".card,.kpi,.mini-stat" in css
    assert "box-shadow:none" in css
    assert ".v5-top-hidden{display:none!important}" in css
