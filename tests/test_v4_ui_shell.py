"""Static contracts for the current QDR V5 shell and dedicated research desks.

These checks cover structure, asset order and client syntax only. They do not
claim live data, PIT qualification or model performance.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"src/quant_research"
SHELL=APP/"v4_shell.html"
CORE="v4_ui_core.js"
PAGES=("v4_ui_pages_b.js","v4_ui_pages_c.js")
DEDICATED=("v4_ui_market_v4.js","v4_ui_l2.js","v5_decision.js")
EXTRA=("v4_ui_warehouse.js","v4_ui_theme.js")
JS_ASSETS=(CORE,*PAGES,*EXTRA,*DEDICATED)
LEGACY_UI=(
    "v4_ui_pages_a.js","v4_ui_fidelity.js",
    "v4_ui_market_v2.js","v4_ui_market_v2.css",
    "v4_ui_market_v3.js","v4_ui_market_v3.css",
    "v4_ui_light.css","v5_research.js","v5_ux.css",
)


def test_v5_workspace_hierarchy_and_assets_are_present():
    html=SHELL.read_text(encoding="utf-8")
    for page in (
        "overview","market","style","lab","screen","risk","warehouse","data"
    ):
        assert 'data-page="'+page+'"' in html
    assert '/assets/v5_system.css' in html
    for name in JS_ASSETS:
        assert '/assets/'+name in html
    for name in LEGACY_UI:
        assert name not in html
    assert 'id="v4-trading-date"' in html
    assert 'id="v4-source-status"' in html
    assert 'id="content"' in html
    assert '__TOKEN__' in html
    assert '示意数据' not in html


def test_v5_workspaces_use_real_read_only_research_endpoints():
    scripts={
        name:(APP/"assets"/name).read_text(encoding="utf-8")
        for name in JS_ASSETS
    }
    combined="".join(scripts.values())
    for page in ("overview","market","style","lab","screen","risk","data"):
        assert "pages."+page+"=" in combined
    for url in (
        "/api/v1/v4/daily",
        "/api/v1/v4/forecasts",
        "/api/v1/factor-lab/library",
        "/api/v1/strategies",
        "/api/v1/paper/risk",
        "/api/v1/research/readiness",
        "/api/v1/l2/styles/overview",
        "/api/v1/l2/styles/forecast",
        "/api/v1/l2/styles/validation",
    ):
        assert url in combined
    assert "X-Console-Token" in scripts[CORE]
    assert "location.hash" in scripts[CORE]
    assert "Math.random" not in combined
    assert "mockData" not in combined
    assert "demoProbabilities" not in combined


@pytest.mark.skipif(shutil.which("node") is None,reason="Node.js not installed")
@pytest.mark.parametrize("name",JS_ASSETS)
def test_v5_javascript_syntax(name):
    result=subprocess.run(
        ["node","--check",str(APP/"assets"/name)],
        capture_output=True,text=True,timeout=15,check=False,
    )
    assert result.returncode==0,result.stderr


def test_research_readiness_remains_separate_from_data_assurance():
    shell=SHELL.read_text(encoding="utf-8")
    source=(APP/"assets"/"v4_ui_pages_c.js").read_text(encoding="utf-8")
    assert ">研究准入<" in shell
    assert "PIT · 回测 · 前向研究" in shell
    start=source.index("pages.data=async()=>{")
    page=source[start:]
    assert "settle('/api/v1/research/readiness')" in page
    for heading in (
        "研究准入","历史数据与 PIT 准入",
        "严格回测准入","前向研究准入","当前阻断与下一步",
    ):
        assert heading in page


def test_server_default_entry_and_all_v5_assets_are_allowlisted():
    script=(APP/"web.py").read_text(encoding="utf-8")
    html=SHELL.read_text(encoding="utf-8")
    assert 'if path in {"/","/studio"}' in script
    assert "v4_shell.html" in script
    assert "'/assets/v5_system.css'" in script
    for name in JS_ASSETS:
        assert "'/assets/"+name+"'" in script
    for name in LEGACY_UI:
        assert "'/assets/"+name+"'" not in script
    assert "app_shell.html" in script
    assert 'src="http://' not in html


def test_dedicated_v5_desks_load_after_shared_workspaces():
    html=SHELL.read_text(encoding="utf-8")
    market=(APP/"assets"/"v4_ui_market_v4.js").read_text(encoding="utf-8")
    style=(APP/"assets"/"v4_ui_l2.js").read_text(encoding="utf-8")
    decision=(APP/"assets"/"v5_decision.js").read_text(encoding="utf-8")
    system=(APP/"assets"/"v5_system.css").read_text(encoding="utf-8")
    assert html.index("v4_ui_pages_c.js") < html.index("v4_ui_market_v4.js")
    assert html.index("v4_ui_pages_c.js") < html.index("v4_ui_l2.js")
    assert html.index("v4_ui_l2.js") < html.index("v5_decision.js")
    assert "pages.market=async" in market
    assert "pages.style=async" in style
    assert "pages.overview=async" in decision
    assert "/api/v1/l2/styles/validation" in style
    assert ".v4-subtab[aria-selected=\"true\"]" in system
    assert "v4_ui_pages_a.js" not in html
    assert "v4_ui_fidelity.js" not in html


def test_mobile_navigation_uses_v5_scrollable_sidebar_contract():
    system=(APP/"assets"/"v5_system.css").read_text(encoding="utf-8")
    assert "@media(max-width:800px)" in system
    assert "aside{position:sticky;top:0" in system
    assert "overflow-x:auto" in system
