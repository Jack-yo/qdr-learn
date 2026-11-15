"""QDR L1 information architecture and source-coverage UX regression."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src" / "quant_research" / "assets" / "v4_ui_market_v2.js"


def test_l1_organized_as_summary_forecast_then_evidence():
    src = JS.read_text(encoding="utf-8")
    for marker in ("今日市场怎么了？", "未来 1 / 3 / 5 日", "底层数据与覆盖情况",
                   "不是完整 12 维综合预测", "l1-evidence-expander"):
        assert marker in src


def test_l1_evidence_grouping_units_and_lazy_loading():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable for JS rendering test")
    runner = r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ids=['price','breadth','volatility','options_pricing','options_positioning',
'microstructure','correlation','cross_asset','positioning','events','funding','path'];
const observation={price:['spy_return_5',.03],breadth:['breadth_proxy_rsp_spy_5',-.001],
volatility:['rv5',.02],options_pricing:['vix',19.3],microstructure:['spy_level1_spread_bps',2.4],
correlation:['sector_dispersion_1',.01],cross_asset:['credit_proxy_hyg_lqd_5',.013],path:['drawdown20',-.02]};
const data={schema:'qdr.l1.v2',scores:{momentum:52,sell_pressure:69,pressure_decay:66},
source:'ALPACA',asof_session:'2026-11-13',data_feed:'delayed_sip',
horizons:{3:{status:'INSUFFICIENT_ANALOG_SAMPLES',analog:null,validation:null}},
domains:ids.map(id=>{
const q=observation[id];
return {id,name:id,status:q?(id==='price'||id==='volatility'?'OBSERVED':'PARTIAL'):'MISSING',
coverage:{available:q?1:0,registered:q?1:0},
features:q?[{id:q[0],label:q[0],value:q[1],status:'OBSERVED',source:'ALPACA_ETF_PROXY'}]:[],
reason:q?null:'SOURCE_NOT_CONNECTED'};
})};
const requests=[];
const document={querySelectorAll:()=>[],querySelector:()=>null};
const V={pages:{},state:{marketHorizon:3},
settle:async url=>{requests.push(url);return url.includes('/l1/v2/overview')?
{ok:true,data}:{ok:false,pending:true};},
e:x=>String(x??'').replace(/[<>&"']/g,''),
n:(v,d=2)=>Number(v).toFixed(d),pct:v=>(v*100).toFixed(2)+'%',
date:x=>String(x).slice(0,10),show(){}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window:{V4:V},document,console});
(async()=>{
const first=await V.pages.market();const html=first.html;
assert.match(html,/今日市场怎么了/);
assert.match(html,/卖压出现缓和迹象/);
assert.match(html,/不是完整 12 维综合预测/);
assert.equal((html.match(/class="l1-evidence-group"/g)||[]).length,4);
assert.equal((html.match(/data-l1-open-domain/g)||[]).length,12);
assert.match(html,/3\.00%/);
assert.match(html,/19\.30 点/);
assert.match(html,/2\.40 bps/);
assert.doesNotMatch(html,/0 \/ 0 项特征/);
assert.match(html,/当前待补数据：/);
assert.equal(requests.length,3);
assert.match(requests[0],/\/l1\/v2\/overview\?horizon=3/);
assert.match(requests[1],/\/l1\/v2\/official/);
assert.match(requests[2],/\/l1\/v2\/extended/);
console.log('PASS grouped evidence, source gaps, units and lazy loading');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
    result = subprocess.run(
        [node, "-e", runner, str(JS)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
