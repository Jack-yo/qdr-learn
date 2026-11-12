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
        "state_history":[],
        "summary":{"direction":[{"brier":0.22,"naive_brier":0.24,
                                 "log_loss":0.65,"naive_log_loss":0.69,
                                 "dates":63}],
                   "downside":[{"brier":0.12,"naive_brier":0.15}],
                   "calibration":[{"bin":1,"count":18,
                                   "mean_probability":0.27,
                                   "observed_up_rate":0.30}]}}
    if route in ("/api/status","/api/v1/system/status"):
        return {"prices":[],"dataset":{"asof_date_et":"2024-12-30"}}
    if route=="/api/v1/market/research":
        return market
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
                "experiments":[]}
    if route=="/api/v1/factor-lab/compare":
        return {"status":"DESCRIPTIVE_COMPARISON_ONLY",
                "rows":[{"partition":"validation","horizon":3,
                         "rank_ic_mean_left":0.03,"rank_ic_mean_right":0.06,
                         "delta_rank_ic":0.03,"label_pair_coverage_left":0.65}]}
    if route=="/api/v1/strategies":
        return {"strategies":[{"id":"S1","name":"反转组合","version":1,
                               "status":"FROZEN","config":{"strategy":{"horizon":3}}}],
                "factor_experiments":[]}
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
            pytest.skip("Playwright Chromium browser not installed")
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
            assert tabs.nth(0).get_attribute("aria-selected")=="true"
            tabs.nth(0).press("ArrowRight")
            assert tabs.nth(1).get_attribute("aria-selected")=="true"
            assert page.locator("#v4-panel-"+name+"-1").is_visible()
            assert not page.locator("#v4-panel-"+name+"-0").is_visible()
        finally:
            page.close()


def test_overview_research_flow_and_market_validation(browser,local_app):
    page=_open(browser,local_app,"overview")
    try:
        assert page.locator(".v4-workflow-step").count()==5
        page.locator("#v4-run-observation").click()
        assert page.get_by_text("已提交日终观察").count()>=1
        page.locator("#nav-market").click()
        page.get_by_role("tab",name="预测验证").click()
        assert page.get_by_text("历史样本外概率可靠性").count()==1
        assert page.get_by_text("0.2200").count()>=1
        assert page.locator(".v4-calibration-row").count()==1
        page.get_by_role("tab",name="风险驱动").click()
        assert page.get_by_text("5D / 20D 波动比").count()>=1
    finally:
        page.close()


def test_screen_candidate_master_detail_uses_actual_api_scores(browser,local_app):
    page=_open(browser,local_app,"screen")
    try:
        page.get_by_role("tab",name="候选股票与解释").click()
        assert page.get_by_text("历史候选股票").count()>=1
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
        assert page.get_by_text("IC增量").count()>=1
        assert page.get_by_text("0.0300").count()>=1
    finally:
        page.close()
    risk=_open(browser,local_app,"risk")
    try:
        risk.get_by_role("tab",name="交易复盘").click()
        assert risk.get_by_text("交易复盘与实际研究观察").count()==1
        assert risk.get_by_text("没有完成期限的研究复盘").count()==1
    finally:
        risk.close()
