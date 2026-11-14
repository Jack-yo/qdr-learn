"""Browser contract for L1 single-workspace interface, independent of real feeds."""
from pathlib import Path
import shutil
import pytest

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'src/quant_research/assets'


def _html():
    css=(APP/'v4_ui_market_v2.css').read_text(encoding='utf8')
    js=(APP/'v4_ui_market_v2.js').read_text(encoding='utf8')
    stub='''
      window.V4=(function(){
        const state={marketHorizon:3}, pages={};
        const e=(s)=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
        const n=(x,d=2)=>Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
        const pct=(x)=>n(Number(x)*100)+'%';
        const api={state,pages,e,n,pct,date:(v)=>String(v??''),settle:async()=>({ok:false})};
        api.show=async()=>{const result=await pages.market();document.getElementById('content').innerHTML=result.html;result.mount?.()};
        return api;
      })();'''
    return '<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><style>'+css+'</style></head><body style="background:#0b1627;margin:0"><main id="content" style="max-width:1440px;margin:auto"></main><script>'+stub+'</script><script>'+js+'</script><script>window.V4.show()</script></body></html>'


@pytest.mark.parametrize('width,height',[(1440,900),(375,844)])
def test_l1_browser_horizons_domains_replay_no_overflow(width,height):
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        try:
            browser=p.chromium.launch(headless=True, executable_path=shutil.which('chromium') or shutil.which('google-chrome'))
        except Exception:
            pytest.skip('No permitted Chromium runtime; execute visual contract on developer machine')
        page=browser.new_page(viewport={'width':width,'height':height})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.set_content(_html(),wait_until='domcontentloaded')
        page.locator('.l1-cockpit').wait_for(timeout=15000)
        assert page.locator('.l1-domain').count()==12
        page.locator('[data-l1-horizon="5"]').click()
        assert 'H5' in page.locator('.l1-period button.active').inner_text()
        page.locator('[data-l1-open-domain="volatility"]').click()
        assert page.locator('.l1-domain-details').count()==1
        page.locator('[data-l1-domain="风险"]').click()
        assert page.locator('.l1-domain').count()==3
        page.locator('#l1-replay-date').fill('2023-01-03')
        page.locator('[data-l1-replay]').click()
        assert page.locator('.l1-cockpit').count()==1
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        assert errors==[]
        browser.close()