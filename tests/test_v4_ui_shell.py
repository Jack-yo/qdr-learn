"""Static contract checks for the approved six-page V4 visual implementation.

They verify structure, asset loading and client syntax, not browser rendering,
live data, PIT qualification or financial model performance.
"""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'src/quant_research'
SHELL = APP / 'v4_shell.html'
CORE = 'v4_ui_core.js'
PAGES = ('v4_ui_pages_a.js','v4_ui_pages_b.js','v4_ui_pages_c.js')
FIDELITY = 'v4_ui_fidelity.js'


def test_approved_six_page_hierarchy_is_present():
    html = SHELL.read_text(encoding='utf-8')
    for page in ('overview','market','style','lab','screen','risk','data'):
        assert 'data-page="'+page+'"' in html
    for name in (CORE,*PAGES,FIDELITY):
        assert '/assets/'+name in html
    assert 'id="v4-trading-date"' in html
    assert 'id="v4-source-status"' in html
    assert 'id="v4-model-status"' in html
    assert 'id="content"' in html
    assert '__TOKEN__' in html
    assert '示意数据' not in html
    assert 'height:1080px' not in html


def test_workspaces_protect_real_research_data_and_navigation():
    root=(APP/'assets'/CORE).read_text(encoding='utf-8')
    script=''.join((APP/'assets'/name).read_text(encoding='utf-8') for name in (*PAGES,FIDELITY))
    for page in ('overview','market','style','lab','screen','risk','data'):
        assert 'pages.'+page+'=' in script
    for url in ('/api/v1/v4/daily','/api/v1/v4/forecasts',
                '/api/v1/factor-lab/library','/api/v1/strategies',
                '/api/v1/paper/risk','/api/v1/research/readiness'):
        assert url in script
    assert 'X-Console-Token' in root
    assert "location.hash" in root
    assert 'Math.random' not in root+script
    assert 'mockData' not in root+script
    assert 'demoProbabilities' not in root+script


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js not installed')
@pytest.mark.parametrize('name',(CORE,*PAGES,FIDELITY))
def test_javascript_syntax(name):
    asset=APP/'assets'/name
    result=subprocess.run(['node','--check',str(asset)],capture_output=True,
                          text=True,timeout=15,check=False)
    assert result.returncode==0,result.stderr


def test_server_default_entry_and_legacy_tools():
    script=(APP/'web.py').read_text(encoding='utf-8')
    assert 'if path in {"/","/studio"}' in script
    assert 'v4_shell.html' in script
    for name in (CORE,*PAGES,FIDELITY):
        assert '/assets/'+name in script
    assert 'app_shell.html' in script
    assert 'src="http://' not in SHELL.read_text(encoding='utf-8')


def test_fidelity_workspace_implements_real_tabs_and_stock_master_detail():
    source=(APP/'assets'/FIDELITY).read_text(encoding='utf-8')
    shell=SHELL.read_text(encoding='utf-8')
    assert 'v4_ui_fidelity.js' in shell
    assert '.v4-subtab[aria-selected="true"]' in shell
    assert '.v4-tabpanel[hidden]' in shell
    for name in ('market','style','lab','screen','risk'):
        assert " "+name+":" in source
    for tab in ('状态识别','风险驱动','预测验证','ETF 代理观察','领先性验证',
                '因子有效性','因子相关性','候选股票与解释',
                '样本外实验','实时预警','交易复盘'):
        assert tab in source
    assert 'data-v4-stock' in source
    assert 'v4-stock-detail' in source
    assert '/api/v1/strategies/' in source
    assert '/api/v1/factor-lab/compare' in source
    assert 'calibrationHistory' in source
    assert 'historicalTransitions' in source
    assert 'RETROSPECTIVE_CURRENT_VINTAGE_NOT_PIT_NOT_FORWARD' in (
        APP/'web.py').read_text(encoding='utf-8')
    assert 'Math.random' not in source
    assert 'demoProbabilities' not in source
