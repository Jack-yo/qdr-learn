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
PAGES = ('v4_ui_pages_a.js','v4_ui_pages_b.js','v4_ui_l3.js','v4_ui_pages_c.js')
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
                '/api/v1/l3/overview','/api/v1/l3/active-strategy',
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



def test_research_readiness_workspace_is_separate_from_data_warehouse():
    shell=SHELL.read_text(encoding='utf-8')
    source=(APP/'assets'/'v4_ui_pages_c.js').read_text(encoding='utf-8')
    assert '>研究准入<' in shell
    assert '数据 · 回测 · 验证' in shell
    start=source.index('pages.data=async()=>{')
    page=source[start:]
    assert "settle('/api/v1/research/readiness')" in page
    for forbidden in ('实际接入证券','行情来源与使用边界',
                      '统一决策时点与模块新鲜度','数据快照 SHA256'):
        assert forbidden not in page
    for heading in ('研究准入与资格','历史数据与 PIT 准入',
                    '严格回测准入','前向研究准入','当前阻断与下一步'):
        assert heading in page


def test_loading_states_use_shared_rolling_icon():
    core=(APP/'assets'/CORE).read_text(encoding='utf-8')
    light=(APP/'assets'/'v4_ui_light.css').read_text(encoding='utf-8')
    l2=(APP/'assets'/'v4_ui_l2.js').read_text(encoding='utf-8')
    alpha=(APP/'assets'/'v4_ui_pages_b.js').read_text(encoding='utf-8')
    assert 'v4-loading-icon' in core
    assert 'v4-page-loading' in core
    assert 'v4-skeleton-block' not in core
    assert '正在加载' not in core
    assert '@keyframes v4-loading-spin' in light
    assert "moduleLoading(title)" in l2
    assert "moduleLoading('因子预览')" in alpha
    assert '正在读取真实价格计算' not in alpha


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
    assert 'v4_ui_l3.js' in shell
    assert 'v4_ui_l3.css' in shell
    assert '.v4-subtab[aria-selected="true"]' in shell
    assert '.v4-tabpanel[hidden]' in shell
    for name in ('market','style','lab','risk'):
        assert " "+name+":" in source
    assert " screen:" not in source
    for tab in ('状态识别','风险驱动','预测验证','ETF 代理观察','领先性验证',
                '因子有效性','因子相关性','实时预警','交易复盘'):
        assert tab in source
    l3=(APP/'assets'/'v4_ui_l3.js').read_text(encoding='utf-8')
    for tab in ('今日选股','因子组合','因子实验室','验证与回测'):
        assert tab in l3
    assert 'l3-stock-open' in l3
    assert 'l3-candidate-detail' in l3
    assert '/api/v1/strategies/' in l3
    assert '/api/v1/factor-lab/compare' in source
    assert 'calibrationHistory' in source
    assert 'historicalTransitions' in source
    assert 'const view={tabs:{}' in source
    assert 'RETROSPECTIVE_CURRENT_VINTAGE_NOT_PIT_NOT_FORWARD' in (
        APP/'web.py').read_text(encoding='utf-8')
    assert 'Math.random' not in source
    assert 'demoProbabilities' not in source


def test_mobile_navigation_stays_on_one_scrollable_row():
    shell=SHELL.read_text(encoding='utf-8')
    assert '@media(max-width:800px){body{overflow:auto}' in shell
    assert 'aside{position:sticky;top:0' in shell
    assert 'flex-wrap:nowrap' in shell
    assert 'overflow-x:auto' in shell
    assert '.v4-metric-strip.v4-five-metrics{grid-template-columns:repeat(5' in shell
