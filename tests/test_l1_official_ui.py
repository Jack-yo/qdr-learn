"""L1 independent official feed integration must not block market model loading."""
from pathlib import Path
import shutil
import subprocess
import pytest

JS = Path(__file__).resolve().parents[1] / "src/quant_research/assets/v4_ui_market_v2.js"


def test_official_public_data_renders_without_faking_prediction():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    program=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ids=['price','breadth','volatility','options_pricing','options_positioning',
 'microstructure','correlation','cross_asset','positioning','events','funding','path'];
const market={schema:'qdr.l1.v2',status:'OBSERVATION_ONLY',asof_session:'2026-11-13',
 data_feed:'delayed_sip',scores:{momentum:52,sell_pressure:60,pressure_decay:62},
 horizons:{3:{status:'INSUFFICIENT_ANALOG_SAMPLES'}},
 domains:ids.map(id=>({id,name:id,status:id==='price'?'OBSERVED':'MISSING',
 features:id==='price'?[{id:'spy_return_5',label:'SPY',value:.03,status:'OBSERVED'}]:[],
 coverage:{available:id==='price'?1:0,registered:id==='price'?1:0}}))};
const official={schema:'qdr.l1.official.v1',status:'OBSERVATION_ONLY',
 asof_session:'2026-11-13',
 features:[
 {domain:'cross_asset',id:'treasury_2y_pct',label:'2Y',value:3.62,status:'OBSERVED',source:'US_TREASURY'},
 {domain:'funding',id:'nyfed_sofr',label:'SOFR',value:3.92,status:'OBSERVED',source:'NYFED'},
 {domain:'positioning',id:'cftc_emini_sp500_lev_net_pct_oi',label:'CFTC',value:-8,status:'OBSERVED',source:'CFTC'}],
 source_health:{treasury:{status:'OBSERVED'},nyfed_sofr:{status:'OBSERVED'},
  nyfed_effr:{status:'MISSING',code:'HTTP_503'},cftc_sp500:{status:'OBSERVED'}}};
const seen=[];let mainReady=true;
const V={pages:{},state:{marketHorizon:3},e:x=>String(x??'').replace(/[&<>"']/g,''),
 n:(v,d=2)=>Number(v).toFixed(d),pct:v=>(Number(v)*100).toFixed(2)+'%',
 date:x=>String(x??'').slice(0,10),show(){},
 settle:async url=>{seen.push(url);return url.includes('v2/official')?{ok:true,data:official}:
 url.includes('v2/overview')?(mainReady?{ok:true,data:market}:{ok:false,pending:true}):
 {ok:false,pending:true}}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),
 {window:{V4:V},document:{querySelectorAll:()=>[],querySelector:()=>null}});
(async()=>{
let html=(await V.pages.market()).html;
assert.equal(seen.length,2);
assert.match(html,/新增官方数据源/);
assert.match(html,/3\/4 已取得观测/);
assert.match(html,/3\.62%/);
assert.match(html,/3\.92%/);
assert.match(html,/-8\.00%/);
assert.match(html,/不是完整 12 维综合预测/);
assert.doesNotMatch(html,/0 \/ 0 项特征/);
mainReady=false; seen.length=0; html=(await V.pages.market()).html;
assert.match(html,/3\.62%/);
assert.match(html,/市场未来展望/);
assert.equal(seen.length,2);
console.log('PASS independent official data and graceful missing Alpaca model');
})().catch(err=>{console.error(err);process.exitCode=1;});
"""
    result=subprocess.run([node,"-e",program,str(JS)],
                          text=True,capture_output=True,check=False,timeout=15)
    assert result.returncode==0, result.stderr or result.stdout
