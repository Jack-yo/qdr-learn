"""QDR L1 market cockpit V4 integration and evidence-gating tests."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "quant_research"
JS = APP / "assets" / "v4_ui_market_v4.js"
CSS = APP / "assets" / "v4_ui_market_v4.css"


def test_v4_market_cockpit_is_loaded_after_theme_and_served():
    shell = (APP / "v4_shell.html").read_text(encoding="utf-8")
    web = (APP / "web.py").read_text(encoding="utf-8")
    assert shell.index("v4_ui_light.css") < shell.index("v4_ui_market_v4.css")
    assert shell.index("v4_ui_theme.js") < shell.index("v4_ui_market_v4.js")
    assert "'/assets/v4_ui_market_v4.js'" in web
    assert "'/assets/v4_ui_market_v4.css'" in web


def test_cockpit_uses_existing_l1_contract_and_all_twelve_domains():
    src = JS.read_text(encoding="utf-8")
    contract = (ROOT / "docs" / "L1_MARKET_UI_CONTRACT.md").read_text(encoding="utf-8")
    domains = (
        "price", "breadth", "volatility", "options_pricing",
        "options_positioning", "microstructure", "correlation",
        "cross_asset", "positioning", "events", "funding", "path",
    )
    for domain in domains:
        assert f"['{domain}'," in src
    for endpoint in (
        "/api/v1/l1/market/overview",
        "/api/v1/v4/freshness",
        "/api/status",
        "/api/v1/market/research",
        "/api/v1/l1/anomalies",
        "/api/v1/l1/validation",
        "/api/v1/l1/replay",
    ):
        assert endpoint in src
    assert "qdr.l1.market.v1" in src
    assert "v4_ui_market_v4.js" in (APP / "v4_shell.html").read_text(encoding="utf-8")
    assert "qdr.l1.market.v1" in contract
    assert "Math.random" not in src


def test_forecast_requires_current_asof_hash_clock_and_admission_evidence():
    src = JS.read_text(encoding="utf-8")
    assert "data.asof_session !== fresh?.asof_session" in src
    assert "DIGEST.test(data.source_snapshot_sha256 || '')" in src
    assert "Number.isFinite(cutoff)" in src
    assert "frozen < cutoff || cutoff >= entry" in src
    assert "f.quantiles.some((q,i) => i > 0 && Number(q)<Number(f.quantiles[i-1]))" in src
    assert "x.model_admitted === false" in src
    assert "x.historical_pit_verified === true" in src
    assert "first_passage_calibration_status==='CALIBRATED_TEMP_HOLDOUT'" in src
    assert "Math.random" not in src


def test_cockpit_styles_use_the_shared_light_palette():
    css = CSS.read_text(encoding="utf-8")
    assert "--l1-bg:#f7faff" in css
    assert "#27384e" in css
    assert "#dce5ef" in css
    assert "#0c1627" not in css
    assert "#121f32" not in css


def test_market_cockpit_js_syntax():
    node = shutil.which("node")
    if not node:
        pytest.skip("NODE_NOT_INSTALLED")
    subprocess.run([node, "--check", str(JS)], check=True, capture_output=True, text=True)


def test_market_cockpit_runtime_observation_only_and_strict_forecast_gating():
    node = shutil.which("node")
    if not node:
        pytest.skip("NODE_NOT_INSTALLED")
    runner = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const domains=[
 ['price','价格与趋势'],['breadth','真实市场广度'],['volatility','波动率结构'],
 ['options_pricing','期权风险定价'],['options_positioning','期权仓位与对冲'],
 ['microstructure','市场微观结构'],['correlation','相关性与离散度'],
 ['cross_asset','跨资产风险传导'],['positioning','资金流与持仓拥挤'],
 ['events','宏观与事件冲击'],['funding','融资与金融条件'],['path','路径与极端事件']
].map(([id,name])=>({id,name,status:'MISSING',value:null,coverage:{available:0,registered:1}}));
const freshness={asof_session:'2026-11-17',
 modules:{market_observation:{freshness_status:'CURRENT',covered_symbols:28,required_symbols:28}}};
let overview={schema:'qdr.l1.market.v1',status:'OBSERVATION_ONLY',
 asof_session:'2026-11-17',domains,drivers:[],features:[],forecast:null};
let calls=[];
const V={pages:{},state:{marketHorizon:3},e:x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
 n:(x,d=2)=>Number(x).toFixed(d),pct:x=>(Number(x)*100).toFixed(1)+'%',
 date:x=>String(x??'').slice(0,10),show:()=>{},
 settle:async url=>{calls.push(url);
  if(url.startsWith('/api/v1/l1/market/overview'))return {ok:true,data:overview};
  if(url==='/api/v1/v4/freshness')return {ok:true,data:freshness};
  if(url==='/api/status')return {ok:true,data:{}};
  if(url.startsWith('/api/v1/market/research'))return {ok:false,error:{message:'no legacy research'}};
  if(url==='/api/v1/l1/anomalies')return {ok:true,data:{status:'OBSERVATION_ONLY',anomalies:[]}};
  if(url==='/api/v1/l1/validation')return {ok:true,data:{status:'RETROSPECTIVE_RESEARCH_ONLY',metrics:[]}};
  return {ok:false,error:{message:'not found'}};
 }};
const context={window:{V4:V},document:{querySelectorAll:()=>[],querySelector:()=>null}};
vm.runInNewContext(source,context);
(async()=>{
 let page=await V.pages.market();
 assert.match(page.html,/已读取市场观察/);
 assert.match(page.html,/暂无合格预测/);
 assert.match(page.html,/12 维市场自动观测/);
 for(const [,name] of [
 ['price','价格与趋势'],['breadth','真实市场广度'],['volatility','波动率结构'],
 ['options_pricing','期权风险定价'],['options_positioning','期权仓位与对冲'],
 ['microstructure','市场微观结构'],['correlation','相关性与离散度'],
 ['cross_asset','跨资产风险传导'],['positioning','资金流与持仓拥挤'],
 ['events','宏观与事件冲击'],['funding','融资与金融条件'],['path','路径与极端事件']
 ])assert.ok(page.html.includes(name),name);
 assert.ok(calls.some(x=>x==='/api/v1/l1/market/overview?horizon=3'));
 assert.doesNotMatch(page.html,/NaN|undefined/);

 // An invalid hash must not promote an otherwise plausible frozen payload.
 overview={...overview,status:'FROZEN_FORWARD_RESEARCH_ONLY',research_only:true,
  model_admitted:false,real_orders_enabled:false,source_snapshot_sha256:'bad',
  model_version:'l1-test',knowledge_cutoff_utc:'2026-11-17T21:00:00Z',
  frozen_at_utc:'2026-11-17T21:05:00Z',entry_at_utc:'2026-11-18T14:30:00Z',
  forecast:{horizon:3,expected_return:.005,p_up:.56,p_downside:.17,
   quantiles:[-.03,-.01,.004,.012,.025]}};
 page=await V.pages.market();
 assert.match(page.html,/暂无合格预测/);
 assert.doesNotMatch(page.html,/\+0\.50%|56\.0%/);

 // A valid, correctly timed frozen research payload may render as research-only.
 overview={...overview,source_snapshot_sha256:'a'.repeat(64),
  forecast:{horizon:3,expected_return:.005,p_up:.56,p_downside:.17,
   probability_calibration_status:'NOT_CALIBRATED_RESEARCH_ONLY',
   downside_threshold:-.02,
   quantiles:[-.03,-.01,.004,.012,.025],
   first_passage:{up_first:.35,down_first:.25,neither:.40,up_threshold:.02,down_threshold:-.02},
   first_passage_calibration_status:'CALIBRATED_TEMP_HOLDOUT'}};
 page=await V.pages.market();
 assert.match(page.html,/已读取冻结预测/);
 assert.match(page.html,/\+0\.50%/);
 assert.match(page.html,/56\.0%/);
 assert.match(page.html,/17\.0%/);
 assert.match(page.html,/独立时间序列校准/);

 // An admitted model without independent PIT/source evidence remains hidden.
 overview={...overview,status:'MODEL_OOS_ADMITTED',research_only:false,
  model_admitted:true,historical_pit_verified:false,source_independently_attested:false};
 page=await V.pages.market();
 assert.match(page.html,/暂无合格预测/);
 console.log('PASS L1 V4 observation-only, strict clock/hash/PIT gating, and calibrated first-touch display');
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", runner, str(JS)],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
