"""Headless six-workspace regression using only deterministic mock API contracts.

The mocks stand in for the transport, not for trading results: they assert
DOM navigation and selection semantics, never forecast skill or real prices.
Run with playwright+Chromium installed; static JS checks run separately.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src/quant_research"


def _payload(path: str):
    route=urlsplit(path).path
    market={
        "status":"DESCRIPTIVE_CURRENT_VINTAGE_ONLY",
        "manifest":{"asof_date_et":"2024-12-30",
                    "historical_decision_eligible":False,
                    "prediction_rows":1},
        "predictions":[{"p_up":0.61,"p_downside":0.14,
                         "predicted_return":0.004}],
        "states":[{"date":"2024-12-30","market_state":"UP_LOW_VOL",
                   "state_available_at":"2024-12-30T22:00:00Z",
                   "market_return_20":0.023,"market_return_5":0.008,
                   "market_vol_20":0.17,"market_vol_5":0.13,
                   "market_vol_ratio":0.765,
                   "style_small_relative_return_5d":0.004,
                   "style_small_relative_return_20d":0.015}],
        "state_history":[
            {"date":"2024-12-26","market_state":"UP_LOW_VOL","market_return_20":0.012},
            {"date":"2024-12-27","market_state":"UP_LOW_VOL","market_return_20":0.018},
            {"date":"2024-12-30","market_state":"UP_LOW_VOL","market_return_20":0.023}],
        "summary":{"direction":[{"brier":0.22,"naive_brier":0.24,
                                 "log_loss":0.65,"naive_log_loss":0.69,
                                 "dates":63}],
                   "downside":[{"brier":0.12,"naive_brier":0.15}],
                   "calibration":[{"bin":1,"count":18,
                                   "mean_probability":0.27,
                                   "observed_up_rate":0.30}]}}
    if route in ("/api/status","/api/v1/system/status"):
        return {"prices":[{"symbol":"SPY","date":"2024-12-30","close":100.0,"basis":"raw"}],
                "dataset":{"asof_date_et":"2024-12-30","source":"ALPACA","feed":"sip","adjustment_bases":["raw"]}}
    if route=="/api/v1/v4/freshness":
        return {"asof_session":"2024-12-30","modules":{"market_observation":{
            "freshness_status":"CURRENT","source_data_asof":"2024-12-30","known_by_decision_cutoff":False}}}
    if route=="/api/v1/market/research":
        horizon=int(urlsplit(path).query.split('horizon=')[-1].split('&')[0]) if 'horizon=' in path else 1
        prediction={**market["predictions"][0],"horizon":horizon,"date":"2024-12-30"}
        return {**market,"horizon":horizon,"predictions":[prediction]}
    if route=="/api/v1/styles":
        return {"asof_date_et":"2024-12-30",
                "latest":[{"factor_name":"MOM","factor_label":"动量",
                           "sum_5d":0.015,"sum_20d":0.023,"state":"领先"},
                          {"factor_name":"HML","factor_label":"价值",
                           "sum_5d":-0.003,"sum_20d":0.002,"state":"走弱"}],
                "series":[{"factor_name":"MOM","sum_20d":0.01},
                          {"factor_name":"MOM","sum_20d":0.023}]}
    if route=="/api/v1/factor-lab/library":
        return {"factor_versions":[{"id":"F1","name":"反转A","version":1,
                                    "config":{"template":"reversal"}},
                                   {"id":"F2","name":"动量B","version":1,
                                    "config":{"template":"momentum"}}],
                "experiments":[
                   {"id":"E1","status":"COMPLETED","config":{"factor_version_id":"F1","source":"yahoo"}},
                   {"id":"E2","status":"COMPLETED","config":{"factor_version_id":"F2","source":"yahoo"}}]}
    if route=="/api/v1/factor-lab/experiments/E1":
        return {"status":"COMPLETED","result":{"summary":[{
          "partition":"validation","horizon":3,
          "rank_ic_mean":0.12,"icir_unannualized":0.45,"daily_ic_count":70,
          "label_pair_coverage":0.8,"q1_mean_forward_price_return":-0.02,
          "q2_mean_forward_price_return":-0.01,"q3_mean_forward_price_return":0.0,
          "q4_mean_forward_price_return":0.01,"q5_mean_forward_price_return":0.02}]}}
    if route=="/api/v1/factor-lab/experiments/E2":
        return {"status":"COMPLETED","result":{"summary":[{
          "partition":"validation","horizon":3,
          "rank_ic_mean":0.03,"icir_unannualized":0.11,"daily_ic_count":60,
          "label_pair_coverage":0.7,"q1_mean_forward_price_return":-0.01,
          "q2_mean_forward_price_return":0.005,"q3_mean_forward_price_return":0.02,
          "q4_mean_forward_price_return":0.015,"q5_mean_forward_price_return":0.0}]}}
    if route=="/api/v1/factor-lab/compare":
        return {"status":"DESCRIPTIVE_COMPARISON_ONLY",
                "rows":[{"partition":"validation","horizon":3,
                         "rank_ic_mean_left":0.03,"rank_ic_mean_right":0.06,
                         "delta_rank_ic":0.03,"label_pair_coverage_left":0.65}]}
    if route=="/api/v1/strategies":
        return {"strategies":[
                   {"id":"S0","name":"旧单因子策略","version":1,"status":"FROZEN",
                    "config":{"strategy":{"horizon":3,"factor_experiment_id":"E1"}}},
                   {"id":"S1","name":"反转组合","version":1,"status":"FROZEN",
                    "config":{"strategy":{"horizon":3,"factors":[
                      {"factor_experiment_id":"E1","weight":0.4},
                      {"factor_experiment_id":"E2","weight":0.6}]}}}],
                "factor_experiments":[{"id":"E1","factor_name":"反转A","factor_version":1},
                                      {"id":"E2","factor_name":"动量B","factor_version":1}]}
    if route=="/api/v1/strategies/S1/composite":
        return {"status":"RETROSPECTIVE_COMPOSITE_RESEARCH_ONLY",
                "asof_date_et":"2024-12-30",
                "latest_composite_ranking":[
                   {"security_id":"SID-A","score":0.84,
                    "weighted_factor_contributions":{"F1":0.55,"F2":0.29}},
                   {"security_id":"SID-B","score":0.78,
                    "weighted_factor_contributions":{"F1":0.18,"F2":0.60}}]}
    if route=="/api/v1/research/readiness":
        return {"stages":{}}
    if route=="/api/v1/v4/daily":
        return {"runs":[]}
    if route=="/api/v1/v4/forecasts":
        return {"records":[]}
    if route=="/api/v1/v4/plans":
        return {"records":[]}
    if route=="/api/v1/v4/outcomes":
        return {"records":[]}
    if route=="/api/v1/v4/research/runs":
        return {"runs":[]}
    if route=="/api/v1/v4/forward-scorecard":
        return {"comparable_sessions":0}
    if route=="/api/v1/backtests/verified":
        return {"results":[]}
    if route=="/api/v1/paper/risk":
        return {"status":"BLOCKED"}
    if route=="/api/v1/paper/account":
        return {"status":"BLOCKED"}
    if route=="/api/v1/paper/timeline":
        return {"status":"BLOCKED","sessions":[]}
    if route=="/api/v1/paper":
        return {"status":"BLOCKED"}
    return {}


@contextmanager
def _server():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,directory=str(APP),**kwargs)

        def do_GET(self):
            route=urlsplit(self.path).path
            if route=="/studio":
                self.path="/v4_shell.html"
                return super().do_GET()
            if route.startswith("/api/"):
                raw=json.dumps(_payload(self.path),ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type","application/json; charset=utf-8")
                self.send_header("Content-Length",str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            return super().do_GET()

        def do_POST(self):
            route=urlsplit(self.path).path
            if route!="/api/run/daily-observation":
                self.send_error(404)
                return
            raw=b'{"status":"RUNNING","action":"daily-observation"}'
            self.send_response(202)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self,*args):
            pass

    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    t=threading.Thread(target=server.serve_forever,daemon=True)
    t.start()
    try:
        yield "http://127.0.0.1:"+str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    playwright=pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        try:
            browser=p.chromium.launch(headless=True)
        except playwright.Error:
            try:
                browser=p.chromium.launch(channel="chrome",headless=True)
            except playwright.Error:
                pytest.skip("Neither Playwright Chromium nor system Chrome is available")
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="module")
def local_app():
    with _server() as url:
        yield url


def _open(browser,base,route):
    page=browser.new_page(viewport={"width":1536,"height":900})
    page.goto(base+"/studio#"+route,wait_until="domcontentloaded")
    page.locator("#content .heading").wait_for(timeout=10000)
    if route!="overview":
        page.locator(".v4-subtab").first.wait_for(timeout=10000)
    return page


def test_six_page_information_architecture_and_keyboard_tabs(browser,local_app):
    expected={"market":4,"style":5,"lab":4,"screen":4,"risk":5}
    for name,count in expected.items():
        page=_open(browser,local_app,name)
        try:
            tabs=page.get_by_role("tab")
            assert tabs.count()==count
            selected=1 if name=="screen" else 0
            following=(selected+1)%count
            assert tabs.nth(selected).get_attribute("aria-selected")=="true"
            tabs.nth(selected).press("ArrowRight")
            assert tabs.nth(following).get_attribute("aria-selected")=="true"
            assert page.locator("#v4-panel-"+name+"-"+str(following)).is_visible()
            assert not page.locator("#v4-panel-"+name+"-"+str(selected)).is_visible()
            if name=="market":
                assert page.locator(".v4-five-metrics .kpi").count()==5
                assert page.get_by_text("历史 H1 上涨概率").count()==1
            if name=="risk":
                assert page.locator(".v4-five-metrics .kpi").count()==5
            if name=="lab":
                assert page.locator("details #v4-factor-hypothesis").count()==1
                assert not page.locator("#v4-factor-hypothesis").is_visible()
            if name=="market":
                tabs.nth(3).click()
                assert "undefined" not in page.locator("#v4-panel-market-3").inner_text()
        finally:
            page.close()


def test_overview_research_flow_and_market_validation(browser,local_app):
    page=_open(browser,local_app,"overview")
    try:
        assert page.get_by_text('最新已收盘行情观察').count()==1
        assert page.locator('.v4-current-quotes').get_by_text('$100.00').count()==1
        assert page.get_by_text('采集时间晚于当日决策截止',exact=False).count()==1
        assert page.locator(".v4-workflow-step").count()==5
        assert page.locator(".v4-overview-trend .v4-spark").count()==1
        page.locator("#v4-run-observation").click()
        page.get_by_text("已提交日终观察", exact=False).first.wait_for()
        page.locator("#nav-market").click()
        page.get_by_role("tab",name="预测验证").click()
        panel=page.locator("#v4-panel-market-3")
        assert panel.get_by_text("历史样本外概率可靠性").count()==1
        assert page.get_by_text("0.2200").count()>=1
        assert panel.locator(".v4-calibration-row").count()==1
        page.get_by_role("tab",name="风险驱动").click()
        assert page.get_by_text("5D / 20D 波动比").count()>=1
    finally:
        page.close()


def test_latest_quote_does_not_use_freshness_for_a_different_date(browser,local_app):
    page=browser.new_page(viewport={'width':1536,'height':900})
    try:
        payload={'modules':{'market_observation':{'source_data_asof':'2024-12-27',
                  'freshness_status':'CURRENT','known_by_decision_cutoff':True}}}
        page.route('**/api/v1/v4/freshness',lambda route:route.fulfill(
            status=200,content_type='application/json',body=json.dumps(payload)))
        page.goto(local_app+'/studio#overview',wait_until='domcontentloaded')
        page.locator('.v4-current-quotes').wait_for(timeout=10000)
        strip=page.locator('.v4-current-quotes')
        assert strip.get_by_text('日期待核验',exact=False).count()==1
        assert strip.get_by_text('到达时间待核验',exact=False).count()==1
    finally:
        page.close()


def test_style_monitor_does_not_fetch_market_research_archive(browser,local_app):
    page=browser.new_page(viewport={'width':1536,'height':900})
    requests=[]
    page.on('request',lambda req:requests.append(req.url))
    try:
        page.goto(local_app+'/studio#style',wait_until='domcontentloaded')
        page.get_by_role('tab',name='风格总览').wait_for(timeout=10000)
        assert not any('/api/v1/market/research' in url for url in requests)
        assert page.locator('#v4-panel-style-0').get_by_text('最新相对收益暂不可用',exact=False).count()==1
    finally:
        page.close()


def test_screen_candidate_master_detail_uses_actual_api_scores(browser,local_app):
    page=_open(browser,local_app,"screen")
    try:
        page.get_by_role("tab",name="候选股票与解释").click()
        assert page.get_by_text("历史候选股票").count()>=1
        assert page.locator("#v4-workspace-strategy").input_value()=="S1"
        page.locator('[data-v4-stock="1"]').click()
        detail=page.locator("#v4-stock-detail")
        assert detail.get_by_text("SID-B").count()>=1
        assert detail.get_by_text("0.7800").count()>=1
        assert detail.get_by_text("F2").count()>=1
        assert page.get_by_text("2024-12-30").count()>=1
    finally:
        page.close()


def test_factor_comparison_and_risk_tabs(browser,local_app):
    page=_open(browser,local_app,"lab")
    try:
        page.get_by_role("tab",name="因子相关性").click()
        page.locator("#v4-compare-left").select_option("F1")
        page.locator("#v4-compare-right").select_option("F2")
        page.locator("#v4-compare-run").click()
        page.get_by_text("IC增量").first.wait_for()
        assert page.get_by_text("0.0300").count()>=1
    finally:
        page.close()
    risk=_open(browser,local_app,"risk")
    try:
        overview=risk.locator('#v4-panel-risk-0')
        assert overview.get_by_role('columnheader',name='持仓市值').count()==1
        assert overview.get_by_text('当前没有具备内部对账的持仓').count()==1
        assert overview.get_by_text('最大行业暴露').count()==1
        risk.get_by_role("tab",name="交易复盘").click()
        assert risk.get_by_text("交易复盘与实际研究观察").count()==1
        assert risk.get_by_text("没有完成期限的研究复盘").count()==1
    finally:
        risk.close()



def test_factor_lab_quintile_chart_tracks_selected_factor_version(browser,local_app):
    page=_open(browser,local_app,"lab")
    try:
        search=page.locator('#v4-library-search')
        search.fill('动量B')
        assert not page.locator('[data-factor-version="F1"]').is_visible()
        assert page.locator('[data-factor-version="F2"]').is_visible()
        search.fill('')
        page.get_by_role("tab",name="因子有效性").click()
        assert page.locator("#v4-panel-lab-1 .v4-factor-chart").count()==1
        assert page.get_by_text("0.1200").count()>=1
        page.get_by_role("tab",name="因子实验室").click()
        page.locator('[data-factor-version="F2"]').click()
        page.get_by_role("tab",name="因子有效性").click()
        assert page.locator("#v4-panel-lab-1 .v4-factor-chart").count()==1
        assert page.get_by_text("0.0300").count()>=1
        assert page.locator("#v4-panel-lab-1 .v4-factor-chart").get_by_text("2.00%").count()>=1
    finally:
        page.close()


def test_light_theme_and_market_color_convention_in_browser(browser,local_app):
    """Full V4 shell uses the light palette and preserves color preference."""
    page=browser.new_page(viewport={"width":1440,"height":900})
    try:
        page.goto(local_app+"/studio#overview",wait_until="domcontentloaded")
        toggle=page.locator("#v4-color-mode")
        toggle.wait_for(timeout=10000)
        assert toggle.inner_text()=="绿涨红跌"
        assert page.evaluate("getComputedStyle(document.querySelector('.app')).backgroundColor")=="rgb(245, 247, 251)"
        assert page.evaluate("getComputedStyle(document.querySelector('aside')).backgroundColor")=="rgb(255, 255, 255)"
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--rise').trim()")=="#087e5c"
        toggle.click()
        assert toggle.inner_text()=="红涨绿跌"
        assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--rise').trim()")=="#ca3d50"
        page.reload(wait_until="domcontentloaded")
        toggle=page.locator("#v4-color-mode")
        toggle.wait_for(timeout=10000)
        assert toggle.inner_text()=="红涨绿跌"
        assert page.evaluate("getComputedStyle(document.querySelector('.app')).backgroundColor")=="rgb(245, 247, 251)"
    finally:
        page.close()
