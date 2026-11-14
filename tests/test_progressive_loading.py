"""Regression checks for non-blocking six-workspace loading and L1 research deferral."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "src/quant_research/assets"


def test_l1_history_is_not_requested_when_research_panel_is_closed():
    src = (ASSET / "v4_ui_market_v2.js").read_text(encoding="utf-8")
    assert "const whenExpanded=(url)=>S.legacyOpen?settle(url):Promise.resolve(deferred)" in src
    assert "whenExpanded('/api/v1/l1/anomalies')" in src
    assert "S.legacyOpen=event.target.open" in src
    assert "overview?horizon=3" in src  # One dataset for all three research horizons.


def test_actual_core_renders_before_all_api_requests_complete():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable; browser smoke tests required in JS-capable environment")
    js = r"""
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
const timers = [], pending = new Map();
const root = {scrollTop:0,children:[],contains(){return false},querySelectorAll(){return []}};
Object.defineProperty(root,'innerHTML',{get(){return this._html||''},
  set(html){this._html=html;this.children=html?[{}]:[]}});
const document = {
  getElementById(id){return id==='content'?root:null},
  querySelector(){return null}, querySelectorAll(){return []},
  addEventListener(){},activeElement:{id:''},title:''
};
const window = {CONSOLE_TOKEN:'',addEventListener(){}};
const setTimeout=(fn,ms)=>{const t={fn,ms,active:true};timers.push(t);return t};
const clearTimeout=t=>{if(t)t.active=false};
const fetch=url=>new Promise(resolve=>pending.set(url,resolve));
vm.runInNewContext(source,{window,document,location:{hash:'#overview'},
  fetch,setTimeout,clearTimeout,AbortController,console});
const V=window.V4;
V.pages.overview=async()=>{
 const [a,b]=await Promise.all([V.settle('/api/one'),V.settle('/api/two')]);
 return {title:'test',html:'<section>'+(a.ok?a.data.name:'等待一')+
 '</section><section>'+(b.ok?b.data.name:'等待二')+'</section>'};
};
async function flush(){
 for(let i=0;i<15;i++)await Promise.resolve();
 for(const t of timers.filter(t=>t.active&&t.ms===120)){t.active=false;t.fn()}
 for(let i=0;i<15;i++)await Promise.resolve();
}
(async()=>{
 await V.show('overview');
 assert.match(root.innerHTML,/v4-pending-banner/);
 assert.match(root.innerHTML,/等待一/);
 assert.match(root.innerHTML,/等待二/);
 assert.equal(pending.size,2);
 pending.get('/api/one')({ok:true,json:async()=>({name:'一已加载'})});
 await flush();
 assert.match(root.innerHTML,/一已加载/);
 assert.match(root.innerHTML,/等待二/);
 pending.get('/api/two')({ok:true,json:async()=>({name:'二已加载'})});
 await flush();
 assert.match(root.innerHTML,/一已加载/);
 assert.match(root.innerHTML,/二已加载/);
 assert.doesNotMatch(root.innerHTML,/v4-pending-banner/);
 console.log('PASS independent progressive loading');
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run(
        [node, "-e", js, str(ASSET / "v4_ui_core.js")],
        capture_output=True, text=True, timeout=12, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
