"""L2 P3 cockpit: static API wiring and isolated no-demo runtime checks."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SHELL = ROOT / "src/quant_research/v4_shell.html"
WEB = ROOT / "src/quant_research/web.py"
JS = ROOT / "src/quant_research/assets/v4_ui_l2.js"
CSS = ROOT / "src/quant_research/assets/v4_ui_l2.css"


def test_l2_cockpit_is_loaded_last_and_assets_are_allowlisted():
    shell = SHELL.read_text(encoding="utf-8")
    web = WEB.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert shell.index("/assets/v4_ui_light.css") < shell.index("/assets/v4_ui_l2.css")
    assert shell.index("/assets/v4_ui_fidelity.js") < shell.index("/assets/v4_ui_l2.js")
    assert shell.index("/assets/v4_ui_theme.js") < shell.index("/assets/v4_ui_l2.js")
    assert "'/assets/v4_ui_l2.js'" in web
    assert "'/assets/v4_ui_l2.css'" in web
    assert "pages.style=async" in js
    assert "overview?rotation=1" in js
    assert "rotation_state" in js
    assert "OBSERVATION_ONLY" in js
    assert "/api/v1/l2/styles/forecast" in js
    assert "/api/v1/l2/styles/validation" in js
    assert "L2_VERIFIED_LABEL_BUNDLE_REQUIRED" not in js
    assert "NO_DATA" not in js
    assert ".l2-main-grid" in css


def test_l2_cockpit_browser_logic_has_valid_syntax_and_no_fake_forecast():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    subprocess.run(["node", "--check", str(JS)], check=True, capture_output=True)
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const file = process.argv[1];
const code = fs.readFileSync(file,'utf8');
const calls=[];
let forecastMode='blocked';
const snapshot = {
  status:'OBSERVATION_ONLY',asof_session:'2025-04-09',source_snapshot_sha256:'a'.repeat(64),
  styles:[
    {style_id:'size',numerator:['IWM'],denominator:['SPY']}
  ],
  latest:[
    {style_id:'size',relative_return_5d:0.012,relative_return_20d:0.033,
     relative_return_60d:0.08,relative_acceleration_5d:0.004,
     relative_volatility_20d:0.018,relative_drawdown_60d:-0.02,
     relative_up_days_10:7,available_at:'2025-04-09T22:00:00Z',registry_version:'v1'}
  ],
  series:[
    {style_id:'size',date:'2025-04-07',relative_return_20d:0.01},
    {style_id:'size',date:'2025-04-08',relative_return_20d:null},
    {style_id:'size',date:'2025-04-09',relative_return_20d:0.03}
  ],
  coverage:{
    required_symbols:14,symbols_with_asof_price:14,
    symbols:[{symbol:'IWM',first_session:'2025-01-02',
      last_session:'2025-04-09',asof_present:true,asof_available_by_cutoff:true}]
  },
  rotation:{
    latest:[{style_id:'size',rotation_state:'STRONG_ACCELERATING',
      strength_relative_return_20d:0.033,acceleration_relative_return_5d:0.004,
      consecutive_sessions:2,rotation_state_start_session:'2025-04-08',
      last_transition_session:'2025-04-08'}],
    transitions:[],history:[],styles_with_known_state:1
  }
};
const escape=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const V4={
 pages:{},state:{},
 e:escape,n:(v,d=2)=>v==null?'—':Number(v).toFixed(d),
 pct:v=>v==null?'—':(v*100).toFixed(2)+'%',
 signed:v=>v==null?'—':((v>=0?'+':'')+(v*100).toFixed(2)+'%'),
 date:v=>v?String(v).slice(0,10):'—',
 short:(v,count)=>String(v||'—').slice(0,count),
 badge:(s)=>'<i>'+escape(s)+'</i>',
 heading:(s,d)=>'<h1>'+escape(s)+'</h1><p>'+escape(d)+'</p>',
 card:(s,body)=>'<section>'+escape(s)+body+'</section>',
 empty:(s,b)=>'<div>'+escape(s)+escape(b)+'</div>',
 note:s=>'<p>'+escape(s)+'</p>',
 table:(cols,rows)=>'<table>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>',
 settle:async path=>{
  calls.push(path);
  if(path.startsWith('/api/v1/l2/styles/overview'))return {ok:true,data:snapshot};
  if(path.startsWith('/api/v1/l2/styles/forecast')){
    if(forecastMode==='blocked')return {ok:true,data:{
      schema:'qdr.l2.forecast.v1',status:'BLOCKED',
      code:'L2_VERIFIED_LABEL_BUNDLE_REQUIRED',forecasts:[],
      eligible_units:0,blocked_units:21,
      missing_evidence:['verified labels'],real_orders_enabled:false
    }};
    return {ok:true,data:{
      schema:'qdr.l2.forecast.v1',status:'RESEARCH_ONLY',
      model_version:'ridge-v1',label_bundle_id:'accepted-v1',
      eligible_units:3,blocked_units:18,
      forecasts:[1,3,5].map(h=>({style_id:'size',horizon:h,
        predicted_relative_return:0.001*h,mean_baseline:0.0002,
        momentum_baseline:0.0004,train_sessions:80,
        forecast_status:'RESEARCH_ONLY',block_reason:null}))
    }};
  }
  if(path.startsWith('/api/v1/l2/styles/validation')){
    if(forecastMode==='blocked')return {ok:true,data:{
      schema:'qdr.l2.validation.v1',status:'BLOCKED',
      code:'L2_P5_VALIDATION_REPORT_NOT_FOUND',
      qualification:[],real_orders_enabled:false
    }};
    return {ok:true,data:{
      schema:'qdr.l2.validation-report.v1',status:'P5_RESEARCH_VALIDATION',
      asof_session:'2025-04-08',
      probability_calibration_status:'NOT_APPLICABLE_CONTINUOUS_RETURN_ONLY',
      summary:{oos_validated_units:1,genuine_forward_units:0,
        model_admitted_units:0,total_units:21,model_admission_enabled:false},
      qualification:[{style_id:'size',horizon:1,
        qualification_status:'OOS_VALIDATED',
        reasons:['NO_GENUINE_FORWARD_EVIDENCE']}],
      oos_validation:[{style_id:'size',horizon:1,
        relative_mse_gain_vs_best_baseline:0.08,
        directional_accuracy:0.56,rank_ic:0.12}],
      forward_validation:[]
    }};
  }
  return {ok:false,error:{message:'source unavailable'}};
 },
 show:()=>{}
};
vm.runInNewContext(code,{window:{V4},console});
(async()=>{
 const result=await V4.pages.style();
 assert.equal(calls.length,1,'one combined P1+P2 source request');
 assert(calls[0].includes('rotation=1'));
 assert(result.html.includes('轮动'));
 assert(result.html.includes('强势加速'));
 assert(result.html.includes('2025-04-09'));
 assert(result.html.includes('OBSERVATION_ONLY'));
 assert(result.html.includes('预测模型尚未通过资格验收'));
 assert(!result.html.includes('胜率 80%'));
 V4.state.l2AsOf='2025-04-08';
 V4.state.l2Tab='evidence';
 const replay=await V4.pages.style();
 assert(calls[1].includes('&asof=2025-04-08'),'replay parameter must reach same source');
 assert(replay.html.includes('数据指纹'));
 V4.state.l2Tab='forecast';
 const blockedForecast=await V4.pages.style();
 assert(calls[3].includes('/api/v1/l2/styles/forecast?asof=2025-04-08'));
 assert(calls[4].includes('/api/v1/l2/styles/validation?asof=2025-04-08'));
 assert(blockedForecast.html.includes('L2_VERIFIED_LABEL_BUNDLE_REQUIRED'));
 assert(blockedForecast.html.includes('不会从当前版本 Yahoo 历史临时生成未来标签'));
 forecastMode='eligible';
 const researchForecast=await V4.pages.style();
 assert(researchForecast.html.includes('Ridge 相对收益'));
 assert(researchForecast.html.includes('RESEARCH_ONLY'));
 assert(researchForecast.html.includes('accepted-v1'));
 assert(researchForecast.html.includes('P5'));
 assert(researchForecast.html.includes('OOS_VALIDATED'));
 assert(researchForecast.html.includes('真实前向冻结交易日'));
 assert(!researchForecast.html.includes('胜率'));
 V4.state.l2Tab='french';
 const french=await V4.pages.style();
 assert(calls[9].includes('/api/v1/styles?mode=observation'));
 assert(french.html.includes('French'));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    subprocess.run(["node", "-e", script, str(JS)], check=True, capture_output=True)
