"""L2 V5 style desk: API wiring, honest forecast gating, no demo values."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"src/quant_research"
SHELL=APP/"v4_shell.html"
WEB=APP/"web.py"
JS=APP/"assets/v4_ui_l2.js"
CSS=APP/"assets/v4_ui_l2.css"

def test_l2_desk_assets_and_contract():
    shell=SHELL.read_text(encoding="utf-8")
    web=WEB.read_text(encoding="utf-8")
    js=JS.read_text(encoding="utf-8")
    css=CSS.read_text(encoding="utf-8")
    assert shell.index("v5_system.css") < shell.index("v4_ui_l2.css")
    assert shell.index("v4_ui_theme.js") < shell.index("v4_ui_l2.js")
    assert "'/assets/v4_ui_l2.js'" in web
    assert "'/assets/v4_ui_l2.css'" in web
    for marker in ("pages.style=async","overview?rotation=1","rotation_state",
                   "/api/v1/l2/styles/forecast","/api/v1/l2/styles/validation",
                   "轮动总览","领先预测","方法与证据"):
        assert marker in js
    assert ".l2-layout" in css
    assert ".l2-tape" in css
    assert "Math.random" not in js

def test_l2_desk_runtime_observation_and_forecast_gating():
    node=shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    runner=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(process.argv[1],'utf8');
const calls=[];let forecastMode='blocked';
const snapshot={
 status:'OBSERVATION_ONLY',asof_session:'2025-04-09',source_snapshot_sha256:'a'.repeat(64),
 latest:[{style_id:'size',relative_return_5d:.012,relative_return_20d:.033,relative_return_60d:.08}],
 series:[{style_id:'size',date:'2025-04-07',relative_return_20d:.01},{style_id:'size',date:'2025-04-09',relative_return_20d:.03}],
 coverage:{required_symbols:14,symbols_with_asof_price:14},
 rotation:{latest:[{style_id:'size',rotation_state:'STRONG_ACCELERATING',
 strength_relative_return_20d:.033,acceleration_relative_return_5d:.004,
 last_transition_session:'2025-04-08'}]}
};
const e=x=>String(x??'').replace(/[&<>"]/g,'');
const V4={pages:{},state:{},e,n:(v,d=2)=>v==null?'—':Number(v).toFixed(d),
 signed:v=>v==null?'—':((Number(v)>0?'+':'')+(Number(v)*100).toFixed(2)+'%'),
 date:v=>v?String(v).slice(0,10):'—',show:()=>{},
 settle:async path=>{
  calls.push(path);
  if(path.startsWith('/api/v1/l2/styles/overview'))return {ok:true,data:snapshot};
  if(path.startsWith('/api/v1/l2/styles/forecast')){
   if(forecastMode==='blocked')return {ok:true,data:{status:'BLOCKED',code:'L2_VERIFIED_LABEL_BUNDLE_REQUIRED',forecasts:[]}};
   return {ok:true,data:{status:'RESEARCH_ONLY',forecasts:[1,3,5].map(h=>({style_id:'size',horizon:h,predicted_relative_return:.001*h,forecast_status:'RESEARCH_ONLY'}))}};
  }
  if(path.startsWith('/api/v1/l2/styles/validation'))return {ok:true,data:{status:'P5_RESEARCH_VALIDATION',summary:{oos_validated_units:1,genuine_forward_units:0}}};
  if(path==='/api/v1/styles?mode=observation')return {ok:true,data:{latest:[{factor_name:'MOM',sum_5d:.01,sum_20d:.02}]}};
  return {ok:false,error:{message:'unavailable'}};
 }};
vm.runInNewContext(code,{window:{V4},document:{querySelectorAll:()=>[],querySelector:()=>null},console});
(async()=>{
 let page=await V4.pages.style();
 assert.equal(calls.length,1);
 assert.match(page.html,/风格轮动/);
 assert.match(page.html,/规模/);
 assert.match(page.html,/强势加速/);
 assert.match(page.html,/20D 相对领先/);
 assert.doesNotMatch(page.html,/BLOCKED|PIT|real_orders_enabled/);
 V4.state.l2Tab='forecast';
 page=await V4.pages.style();
 assert.match(page.html,/领先预测待验证/);
 assert.match(page.html,/L2_VERIFIED_LABEL_BUNDLE_REQUIRED/);
 forecastMode='eligible';
 page=await V4.pages.style();
 assert.match(page.html,/H1/);
 assert.match(page.html,/\+0\.10%/);
 V4.state.l2Tab='evidence';
 page=await V4.pages.style();
 assert.match(page.html,/数据指纹/);
 assert.match(page.html,/French 因子独立对照/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run([node,"-e",runner,str(JS)],capture_output=True,text=True,timeout=20,check=False)
    assert result.returncode==0,result.stderr or result.stdout
