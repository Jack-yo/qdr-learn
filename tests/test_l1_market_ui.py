"""L1 market cockpit front-end contract tests (not live model verification)."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'src' / 'quant_research'


def test_v4_page_preserved_and_new_l1_loaded_last():
    shell = (APP / 'v4_shell.html').read_text(encoding='utf-8')
    assert '/assets/v4_ui_market_v2.css' in shell
    assert '/assets/v4_ui_market_v2.js' in shell
    assert shell.index('v4_ui_fidelity.js') < shell.index('v4_ui_market_v2.js')
    for key in ('overview','market','style','lab','screen','risk'):
        assert f'data-page="{key}"' in shell


def test_l1_static_assets_are_whitelisted():
    web = (APP/'web.py').read_text(encoding='utf-8')
    assert "'/assets/v4_ui_market_v2.js'" in web
    assert "'/assets/v4_ui_market_v2.css'" in web


def test_l1_has_twelve_domains_and_interactive_horizons():
    src=(APP/'assets/v4_ui_market_v2.js').read_text(encoding='utf-8')
    ids=('price','breadth','volatility','options_pricing','options_positioning',
         'microstructure','correlation','cross_asset','positioning','events','funding','path')
    for domain in ids:
        assert f"['{domain}'," in src
    assert 'data-l1-horizon' in src
    assert 'data-l1-domain' in src
    assert 'state.marketHorizon=h' in src
    assert 'Math.random' not in src
    assert 'pages.market=async()' in src
    assert 'qdr.l1.market.v1' in src


def test_l1_rejects_unsupported_forecast_and_retrospective_promotion():
    src=(APP/'assets/v4_ui_market_v2.js').read_text(encoding='utf-8')
    assert "data.asof_session !== fresh?.asof_session" in src
    assert 'DIGEST.test' in src
    assert 'f.quantiles.some' in src
    assert 'Math.abs(Number(p.up_first)+Number(p.down_first)+Number(p.neither)-1)>0.001' in src
    assert "'/api/v1/market/research?horizon='" in src
    assert '旧历史回放拼接为当前预测' in src


def test_l1_js_parse():
    node=shutil.which('node')
    if not node:
        pytest.skip('NODE_NOT_INSTALLED')
    subprocess.run([node,'--check',str(APP/'assets/v4_ui_market_v2.js')],check=True,capture_output=True,text=True)
