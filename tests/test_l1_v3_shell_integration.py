"""Real V4 shell JS loading order smoke, including V2/V3 compatibility."""
from pathlib import Path
import shutil
import subprocess

import pytest

ASSETS=Path(__file__).resolve().parents[1]/"src/quant_research/assets"
SCRIPTS=("v4_ui_core.js","v4_ui_pages_a.js","v4_ui_pages_b.js",
         "v4_ui_pages_c.js","v4_ui_fidelity.js",
         "v4_ui_market_v2.js","v4_ui_market_v3.js")


def test_original_v4_shell_renders_new_market_first_without_waiting_for_api():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node unavailable for UI test")
    runner=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const paths=process.argv.slice(1);
const root={scrollTop:0,children:[],contains(){return false},querySelectorAll(){return[]}};
Object.defineProperty(root,'innerHTML',{get(){return this.html||''},
 set(s){this.html=s;this.children=s?[{}]:[]}});
const dummy={textContent:'',innerHTML:'',style:{},addEventListener(){},
 setAttribute(){},querySelectorAll(){return[]},querySelector(){return null},
 classList:{toggle(){}}};
const doc={getElementById(id){return id==='content'?root:dummy},
 querySelector(){return dummy},querySelectorAll(){return[]},
 addEventListener(){},activeElement:{id:''},createElement(){return {...dummy}},title:''};
const win={CONSOLE_TOKEN:'',addEventListener(){}};
const wait=()=>new Promise(()=>{});let requestCount=0;
const fetch=(url)=>{requestCount++;return wait()};
const timers=(fn,ms)=>({fn,ms});
const Controller=class{constructor(){this.signal={}}abort(){}};
const ctx={window:win,document:doc,location:{hash:'#market'},fetch,
 setTimeout:timers,clearTimeout(){},AbortController:Controller,console};
for(const p of paths)vm.runInNewContext(fs.readFileSync(p,'utf8'),ctx,{filename:p});
(async()=>{
await win.V4.show('market');
assert.match(root.innerHTML,/市场状态与情景研究/);
assert.match(root.innerHTML,/H3 · 这次概率如何算出/);
assert.match(root.innerHTML,/市场原始数据监测/);
assert.match(root.innerHTML,/v4-pending-banner/);
assert.doesNotMatch(root.innerHTML,/研究数据暂不可用/);
assert.equal(requestCount,5);
console.log('PASS V4 shell, V2 preservation, V3 override, nonblocking lazy loading');
})().catch(err=>{console.error(err);process.exitCode=1});
"""
    res=subprocess.run([node,"-e",runner,*[str(ASSETS/p) for p in SCRIPTS]],
                       text=True,capture_output=True,timeout=15,check=False)
    assert res.returncode==0,res.stderr or res.stdout
