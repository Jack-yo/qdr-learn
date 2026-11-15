"""Exercise L1's three independent streams and extended-market detail rendering."""
from pathlib import Path
import shutil
import subprocess
import pytest

JS=Path(__file__).resolve().parents[1]/"src/quant_research/assets/v4_ui_market_v2.js"


def test_extended_readouts_do_not_block_core_or_claim_predictive_value():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node not installed")
    runner=r"""
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const ids=['price','breadth','volatility','options_pricing','options_positioning',
'microstructure','correlation','cross_asset','positioning','events','funding','path'];
const base={schema:'qdr.l1.v2',asof_session:'2026-11-13',status:'OBSERVATION_ONLY',
scores:{momentum:55,sell_pressure:62,pressure_decay:60},horizons:{3:{status:'INSUFFICIENT_ANALOG_SAMPLES'}},
domains:ids.map(id=>({id,name:id,status:id==='price'?'OBSERVED':'MISSING',
  features:id==='price'?[{id:'spy_return_5',value:.03,label:'SPY 五日',status:'OBSERVED',source:'ALPACA'}]:[],
  coverage:{available:id==='price'?1:0,registered:id==='price'?1:0}}))};
const extended={schema:'qdr.l1.extended.v1',asof_session:'2026-11-13',status:'OBSERVATION_ONLY',
features:[
 {domain:'options_pricing',id:'cboe_pcr_total',label:'总成交 P/C',value:.96,status:'OBSERVED',source:'CBOE'},
 {domain:'options_positioning',id:'cboe_spx_put_call_oi',label:'SPX 汇总 OI',value:1.2,status:'OBSERVED',source:'CBOE'},
 {domain:'funding',id:'ofr_fsi',label:'金融压力',value:-1.9,status:'OBSERVED',source:'OFR'},
 {domain:'events',id:'bls_scheduled_next_7d',label:'BLS 近期日程',value:2,status:'OBSERVED',source:'BLS'},
 {domain:'positioning',id:'cftc_gold_net_pct_oi',label:'黄金持仓',value:10,status:'OBSERVED',source:'CFTC'},
 {domain:'breadth',id:'stock_sample_advance_share',label:'固定样本上涨率',value:65,status:'OBSERVED',source:'ALPACA'},
 {domain:'microstructure',id:'cboe_trf_notional_share',label:'TRF 成交占比',value:40,status:'OBSERVED',source:'CBOE'}],
source_health:{cboe_options:{status:'OBSERVED'},ofr_fsi:{status:'OBSERVED'},
bls_calendar:{status:'OBSERVED'},cftc_gold:{status:'OBSERVED'},
stock_sample:{status:'OBSERVED'},cboe_equity_volume:{status:'OBSERVED'}},
calendar_events:[{name:'CPI 预定发布',start_utc:'2026-11-17T13:30:00+00:00'}]};
const observed=[];let coreReady=true;let extendedReady=true;
const V={pages:{},state:{marketHorizon:3},e:x=>String(x??'').replace(/[&<>"']/g,''),
n:(v,d=2)=>Number(v).toFixed(d),pct:v=>(Number(v)*100).toFixed(2)+'%',
date:x=>String(x??'').slice(0,10),show(){},
settle:async url=>{observed.push(url);
 if(url.includes('v2/overview'))return coreReady?{ok:true,data:base}:{ok:false,pending:true};
 if(url.includes('v2/extended'))return extendedReady?{ok:true,data:extended}:{ok:false,pending:true};
 return {ok:false,pending:true};
}};
const doc={querySelector:()=>null,querySelectorAll:()=>[]};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window:{V4:V},document:doc});
(async()=>{
let h=(await V.pages.market()).html;
assert.equal(observed.length,3);
assert.match(h,/市场未来展望/);
assert.match(h,/不是完整 12 维综合预测/);
assert.match(h,/跨市场自动观测/);
assert.match(h,/固定 30 股样本中上涨占比/);
assert.match(h,/0\.96 倍/);
assert.match(h,/1\.20 倍/);
assert.match(h,/-1\.90 指数点/);
assert.match(h,/65\.00%/);
assert.match(h,/40\.00%/);
assert.match(h,/2 项/);
assert.doesNotMatch(h,/真实交易已执行/);
coreReady=false;observed.length=0;
h=(await V.pages.market()).html;
assert.match(h,/0\.96 倍/);
assert.equal(observed.length,3);
extendedReady=false;coreReady=true;observed.length=0;
h=(await V.pages.market()).html;
assert.match(h,/市场未来展望/);
assert.equal(observed.length,3);
assert.doesNotMatch(h,/0\.96 倍/);
console.log('PASS independent L1 stream and source-typed observations');
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    result=subprocess.run([node,"-e",runner,str(JS)],
        text=True,capture_output=True,timeout=20,check=False)
    assert result.returncode==0, result.stderr or result.stdout
