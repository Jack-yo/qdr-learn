"""V3 UI: numeric trace, shared light shell, no fake results, independent loading."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
JS=ROOT/"src/quant_research/assets/v4_ui_market_v3.js"
HTML=ROOT/"src/quant_research/v4_shell.html"
WEB=ROOT/"src/quant_research/web.py"


def test_light_shell_new_assets_and_strict_api():
    shell=HTML.read_text(encoding="utf-8")
    api=WEB.read_text(encoding="utf-8")
    assert 'href="/assets/v4_ui_light.css"' in shell
    assert 'src="/assets/v4_ui_theme.js"' in shell
    assert 'id="v4-color-mode"' in shell
    assert shell.index("v4_ui_market_v3.css") < shell.index("v4_ui_light.css")
    for suffix in ("v4_ui_market_v3.js","v4_ui_market_v3.css","v4_ui_light.css","v4_ui_theme.js"):
        assert "/assets/"+suffix in shell
        assert "/assets/"+suffix in api
    assert "if path in ('/api/v1/l1/v3/latest'," in api
    assert "if path == '/api/v1/l1/v3/history':" in api
    assert "V3_QUERY_NOT_ALLOWED_READ_ONLY" in api


def test_actual_page_uses_independent_real_data_and_numeric_trace():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    runner=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const f=[
['spy_return_5','SPY五日收益','%',1.23,.55,.21],
['breadth_proxy_rsp_spy_5','等权相对强度','%',.22,.30,.09],
['small_cap_relative_5','小盘股相对强度','%',-.5,-.1,-.13],
['vol_ratio','短长波动比','倍',1.08,.23,-.10],
['credit_proxy_hyg_lqd_5','信用相对强度','%',.11,.10,.05],
['downside_rv20','下行波动','%',.82,-.3,-.08],
['drawdown20','二十日回撤','%',-2.2,.12,.15]
];
const h={horizon:3,status:'RESEARCH_ONLY',boundary_return:.0082,
research_estimates:{UP:.43,FLAT:.37,DOWN:.20},
qualification:{admitted:false,reasons:['HISTORICAL_PIT_UNVERIFIED']},
validation:{status:'RETROSPECTIVE_OOS_NOT_PIT_ATTESTED',samples:244,
model_brier:.55,baseline_brier:.61,model_log_loss:.9,baseline_log_loss:.96,
ece:.087,folds:5,numeric_gates_passed:false},
trace:{feature_inputs:f.map(x=>({key:x[0],name:x[1],unit:x[2],raw_value:x[3],
standardized:x[4],up_logit_contribution:x[5]})),
up_logit_intercept:.42,up_logit_sum:.61,temperature:1.15,
class_logits:[.62,.38,.22],raw_probabilities:{UP:.47,FLAT:.34,DOWN:.19},
calibrated_probabilities:{UP:.43,FLAT:.37,DOWN:.20}},
train_samples:720,calibration_samples:150,trace_sha256:'a'.repeat(64)};
const V3={schema:'qdr.l1.probability.v3',status:'RESEARCH_ONLY',
asof_session:'2026-11-13',data_feed:'iex',model_version:'L1_V3_ETF7.1',
feature_version:'L1_V3_ETF7',horizons:{1:{...h,horizon:1},3:h,5:{...h,horizon:5}},
raw_observations:[{id:'SPY',label:'SPY收盘',value:670,unit:'美元',delta:3,
history:[660,665,667,670],category:'price',source:'ALPACA',
observed_date:'2026-11-13'},{id:'vol_ratio',label:'短长波动比',value:1.5,
unit:'倍',category:'options',history:[1.1,1.3,1.5],observed_date:'2026-11-13'}]};
const V2={schema:'qdr.l1.v2',asof_session:'2026-11-13',
scores:{momentum:65,sell_pressure:52},domains:[{id:'price',status:'PARTIAL',
features:[{status:'OBSERVED'}]}]};
const extended={schema:'qdr.l1.extended.v1',asof_session:'2026-11-13',
features:[{id:'ofr_fsi',value:-1.2,unit:'指数点',domain:'funding',
status:'OBSERVED',source:'OFR',observed_date:'2026-11-12'}],
source_health:{ofr_fsi:{status:'OBSERVED'}},
calendar_events:[{name:'CPI',start_utc:'2026-11-19T14:00:00+00:00'}]};
let ready=true,seen=[],oldCount=0,events={};
const document={querySelectorAll:()=>[],
querySelector:()=>({addEventListener(type,fn){events[type]=fn}})};
const V={pages:{market:async()=>{oldCount++;return{html:'原版研究'};}},
state:{marketHorizon:3},e:x=>String(x??'').replace(/[&<>"]/g,'_'),
n:(x,d=2)=>Number(x).toFixed(d),show(){},
settle:async url=>{seen.push(url);
if(url.includes('/v3/status'))return {ok:true,data:{schema:'qdr.l1.v3.pipeline.status',status:'CURRENT_RESEARCH',model_retrain_due:false,model_reference:{asof_session:'2026-11-01'}}};
if(url.includes('/v3/outcomes'))return {ok:true,data:{
 schema:'qdr.l1.v3.outcomes',records:[{asof_session:'2026-11-10',horizon:1,
 actual_scenario:'UP',actual_return:.011,brier_3class:.15,frozen_sha256:'b'.repeat(64)}]}};
if(url.startsWith('/api/v1/l1/v3/'))return ready?{ok:true,data:V3}:{ok:false,pending:true};
if(url.includes('/v2/overview'))return {ok:true,data:V2};
if(url.includes('/v2/extended'))return {ok:true,data:extended};
return {ok:false,pending:true};}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window:{V4:V},document});
(async()=>{
const page=await V.pages.market();
const html=page.html;
assert.equal(seen.length,6);
assert.match(seen[0],/v3\/latest$/);
assert.match(seen[1],/v3\/status$/);
assert.match(html,/H3 · 这次概率如何算出/);
assert.match(html,/SPY五日收益/);
assert.match(html,/1\.23 %/);
assert.match(html,/47\.0%/);
assert.match(html,/43\.0%/);
assert.match(html,/0\.5500/);
assert.match(html,/0\.6100/);
assert.match(html,/当前来源 iex/);
assert.match(html,/原始数据与本次因子值/);
assert.match(html,/市场原始数据监测/);
assert.match(html,/OFR/);
assert.match(html,/2026-11-10/);
assert.match(html,/0\.1500/);
assert.match(html,/实际近20次观测变化/);
assert.match(html,/lv3-change is-up/);
assert.match(html,/未取得正式预测资格/);
assert.doesNotMatch(html,/62\.0%/);
assert.doesNotMatch(html,/第二屏/);
assert.equal(oldCount,0);
ready=false;seen=[];
const partial=(await V.pages.market()).html;
assert.equal(seen.length,5);
assert.match(partial,/正在读取真实数据/);
assert.doesNotMatch(partial,/47\.0%/);
assert.doesNotMatch(partial,/43\.0%/);
assert.match(partial,/OFR/);
assert.equal(oldCount,0);
console.log('PASS model trace, old palette, raw metrics, fallback and six progressive requests');
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result=subprocess.run([node,"-e",runner,str(JS)],
                          capture_output=True,text=True,timeout=15,check=False)
    assert result.returncode==0,result.stderr or result.stdout
