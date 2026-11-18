"""QDR V4 light visual system: routing, CSS semantic colors and accessible switch."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/"src/quant_research"
HTML=APP/"v4_shell.html"
CSS=APP/"assets/v5_system.css"
SCRIPT=APP/"assets/v4_ui_theme.js"
WEB=APP/"web.py"


def test_v5_system_is_single_shared_visual_base():
    html=HTML.read_text(encoding="utf-8")
    css=CSS.read_text(encoding="utf-8")
    routes=WEB.read_text(encoding="utf-8")
    assert "v4_ui_market_v2.css" not in html
    assert "v4_ui_market_v3.css" not in html
    assert "v4_ui_light.css" not in html
    assert "v4_ui_market_v2.js" not in html
    assert "v4_ui_market_v3.js" not in html
    assert '<meta name="color-scheme" content="light">' in html
    for asset in ("v5_system.css","v4_ui_theme.js"):
        assert "/assets/"+asset in html
        assert "'/assets/"+asset+"'" in routes
    assert css.count("{")==css.count("}")
    for token in ("--bg:#f5f7fb","--surface:#fff",
                  "--rise:#087e5c","--fall:#ca3d50"):
        assert token in css
    assert 'html[data-change-palette="red-up"]' in css
    for module in (".nav.active",".card,.kpi",".table th",".v5-summary-strip",".v4-tabpanel[hidden]"):
        assert module in css
    assert "Math.random" not in SCRIPT.read_text(encoding="utf-8")


def test_light_theme_toggle_respects_preference_without_touching_numbers():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    js=r"""
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const saved=new Map();
const attrs={},events={},btn={
 textContent:'',setAttribute(k,v){attrs['btn_'+k]=v},
 addEventListener(t,fn){events[t]=fn}
};
const root={setAttribute(k,v){attrs[k]=v}};
const document={documentElement:root,getElementById:id=>id==='v4-color-mode'?btn:null};
const window={localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v)}};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{document,window});
assert.equal(attrs['data-change-palette'],'green-up');
assert.equal(btn.textContent,'绿涨红跌');
assert.equal(attrs['btn_aria-pressed'],'false');
events.click();
assert.equal(attrs['data-change-palette'],'red-up');
assert.equal(btn.textContent,'红涨绿跌');
assert.equal(attrs['btn_aria-pressed'],'true');
assert.equal(saved.get('qdr.market.direction.palette.v1'),'red-up');
events.click();
assert.equal(attrs['data-change-palette'],'green-up');
assert.equal(saved.get('qdr.market.direction.palette.v1'),'green-up');
console.log('PASS stable, accessible red/green market display switch');
"""
    res=subprocess.run([node,"-e",js,str(SCRIPT)],
                       text=True,capture_output=True,timeout=15,check=False)
    assert res.returncode==0,res.stderr or res.stdout


