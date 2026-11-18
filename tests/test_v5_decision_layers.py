"""V5 decision desk renders P6 layer qualification without changing decisions."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"src/quant_research"
JS=APP/"assets/v5_decision.js"
CSS=APP/"assets/v5_system.css"


def test_decision_desk_wires_read_only_four_layer_status():
    js=JS.read_text(encoding="utf-8")
    css=CSS.read_text(encoding="utf-8")
    assert "/api/v1/v4/layers?horizon=3" in js
    assert "研究链资格" in js
    assert "desk-layer-chain" in js
    assert ".desk-layer-chain" in css
    assert "real_orders_enabled" not in js


@pytest.mark.skipif(shutil.which("node") is None,reason="Node.js not installed")
def test_decision_desk_layer_blockers_are_context_not_trade_instructions():
    runner=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(process.argv[1],'utf8'),calls=[];
const fresh={asof_session:'2026-01-30',modules:{market_observation:{freshness_status:'CURRENT'}}};
const l1={schema:'qdr.l1.market.v1',status:'FROZEN_FORWARD_RESEARCH_ONLY',
 asof_session:'2026-01-30',research_only:true,model_admitted:false,real_orders_enabled:false,
 source_snapshot_sha256:'a'.repeat(64),model_version:'l1-v1',
 knowledge_cutoff_utc:'2026-01-30T21:15:00Z',frozen_at_utc:'2026-01-30T21:16:00Z',
 entry_at_utc:'2026-02-02T14:30:00Z',
 forecast:{horizon:3,p_up:.54,expected_return:.002,quantiles:[-.02,-.01,0,.01,.02]}};
const l2={status:'OBSERVATION_ONLY',asof_session:'2026-01-30',
 latest:[{style_id:'quality',relative_return_20d:.03}],
 rotation:{latest:[{style_id:'quality',rotation_state:'STRONG_ACCELERATING'}]}};
const layers={status:'RESEARCH_ONLY',asof_session:'2026-01-30',complete_four_layer_context:false,
 blockers:['L1_NOT_MODEL_ADMITTED','L2_NO_MODEL_ADMITTED_STYLE_CONTEXT','L3_L2_STYLE_BINDING_NOT_VERIFIED'],
 layers:{
  l1_market:{downstream_context_eligible:false},
  l2_style:{l3_style_context_available:false,admitted_units:0},
  l3_alpha:{style_input_binding_verified:false,style_historical_pit_attested:false},
  l4_risk:{status:'BLOCKED'}
 }};
const responses={
 '/api/v1/v4/freshness':fresh,
 '/api/v1/l1/market/overview?horizon=3':l1,
 '/api/v1/l2/styles/overview?rotation=1':l2,
 '/api/v1/v4/plans':{records:[]},
 '/api/v1/paper/risk':{status:'CONCENTRATION_MEASURED',gross_weight:0,alerts:[]},
 '/api/v1/v4/daily':{runs:[]},
 '/api/v1/v4/layers?horizon=3':layers
};
const V4={pages:{},e:x=>String(x??'').replace(/[&<>"]/g,''),n:(v,d=2)=>v==null?'—':Number(v).toFixed(d),
 pct:v=>v==null?'—':(Number(v)*100).toFixed(1)+'%',
 signed:v=>v==null?'—':((Number(v)>0?'+':'')+(Number(v)*100).toFixed(2)+'%'),
 date:v=>v?String(v).slice(0,10):'—',
 settle:async path=>{calls.push(path);return responses[path]!==undefined?{ok:true,data:responses[path]}:{ok:false,error:{message:'missing'}};}};
const document={addEventListener:()=>{},getElementById:()=>null};
vm.runInNewContext(code,{window:{V4},document,MutationObserver:function(){this.observe=()=>{}},console});
(async()=>{
 const page=await V4.pages.overview();
 assert(calls.includes('/api/v1/v4/layers?horizon=3'));
 assert.match(page.html,/研究链资格/);
 assert.match(page.html,/L1 市场/);
 assert.match(page.html,/L2 风格/);
 assert.match(page.html,/L3 Alpha/);
 assert.match(page.html,/L4 风控/);
 assert.match(page.html,/L3_L2_STYLE_BINDING_NOT_VERIFIED/);
 assert.match(page.html,/今日无候选/);
 assert.match(page.html,/0 个/);
 assert.doesNotMatch(page.html,/下单|买入|卖出/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run(
        ["node","-e",runner,str(JS)],
        capture_output=True,text=True,timeout=20,check=False,
    )
    assert result.returncode==0,result.stderr or result.stdout


@pytest.mark.skipif(shutil.which("node") is None,reason="Node.js not installed")
def test_decision_desk_ready_chain_still_remains_research_context_only():
    runner=r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync(process.argv[1],'utf8');
const fresh={asof_session:'2026-01-30',modules:{market_observation:{freshness_status:'CURRENT'}}};
const l1={schema:'qdr.l1.market.v1',status:'MODEL_OOS_ADMITTED',
 asof_session:'2026-01-30',model_admitted:true,historical_pit_verified:true,
 source_independently_attested:true,real_orders_enabled:false,
 source_snapshot_sha256:'a'.repeat(64),model_version:'l1-v1',
 knowledge_cutoff_utc:'2026-01-30T21:15:00Z',frozen_at_utc:'2026-01-30T21:16:00Z',
 entry_at_utc:'2026-02-02T14:30:00Z',
 forecast:{horizon:3,p_up:.56,expected_return:.003,quantiles:[-.02,-.01,0,.01,.03]}};
const l2={status:'OBSERVATION_ONLY',asof_session:'2026-01-30',
 latest:[{style_id:'quality',relative_return_20d:.03}],
 rotation:{latest:[{style_id:'quality',rotation_state:'STRONG_ACCELERATING'}]}};
const layers={status:'FOUR_LAYER_RESEARCH_CONTEXT_READY',
 asof_session:'2026-01-30',complete_four_layer_context:true,blockers:[],
 decision_eligible:false,execution_eligible:false,real_orders_enabled:false,
 layers:{
  l1_market:{downstream_context_eligible:true},
  l2_style:{l3_style_context_available:true,admitted_units:3},
  l3_alpha:{style_input_binding_verified:true,style_historical_pit_attested:true,
            downstream_context_eligible:true},
  l4_risk:{status:'RESEARCH_PLANS_ONLY'}
 }};
const responses={
 '/api/v1/v4/freshness':fresh,
 '/api/v1/l1/market/overview?horizon=3':l1,
 '/api/v1/l2/styles/overview?rotation=1':l2,
 '/api/v1/v4/plans':{records:[]},
 '/api/v1/paper/risk':{status:'CONCENTRATION_MEASURED',gross_weight:0,alerts:[]},
 '/api/v1/v4/daily':{runs:[]},
 '/api/v1/v4/layers?horizon=3':layers
};
const V4={pages:{},e:x=>String(x??'').replace(/[&<>"]/g,''),
 n:(v,d=2)=>v==null?'—':Number(v).toFixed(d),
 pct:v=>v==null?'—':(Number(v)*100).toFixed(1)+'%',
 signed:v=>v==null?'—':((Number(v)>0?'+':'')+(Number(v)*100).toFixed(2)+'%'),
 date:v=>v?String(v).slice(0,10):'—',
 settle:async path=>responses[path]!==undefined?{ok:true,data:responses[path]}:{ok:false,error:{message:'missing'}}};
const document={addEventListener:()=>{},getElementById:()=>null};
vm.runInNewContext(code,{window:{V4},document,MutationObserver:function(){this.observe=()=>{}},console});
(async()=>{
 const page=await V4.pages.overview();
 assert.match(page.html,/四层研究证据已对齐/);
 assert.match(page.html,/绑定 \+ PIT/);
 assert.match(page.html,/3 单元/);
 assert.doesNotMatch(page.html,/下单|买入|卖出|可交易|交易许可/);
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result=subprocess.run(
        ["node","-e",runner,str(JS)],
        capture_output=True,text=True,timeout=20,check=False,
    )
    assert result.returncode==0,result.stderr or result.stdout
