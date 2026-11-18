"""Opt-in live, read-only browser acceptance against the user's local server."""
import json
import os
from urllib.request import urlopen

import pytest


@pytest.mark.skipif(os.environ.get('QDR_L1_LIVE_E2E')!='1',reason='Live local service acceptance is opt-in')
@pytest.mark.parametrize('width,height',[(1440,900),(375,844)])
def test_live_v3_horizons_and_overflow(width,height):
    sync=pytest.importorskip('playwright.sync_api')
    base='http://127.0.0.1:8766'
    with urlopen(base+'/api/v1/l1/v3/latest',timeout=30) as response:
        latest=json.load(response)
    assert latest['status']=='RESEARCH_ONLY'
    assert latest['execution_eligible'] is False
    errors=[]
    with sync.sync_playwright() as playwright:
        try:
            browser=playwright.chromium.launch(headless=True)
        except sync.Error:
            browser=playwright.chromium.launch(channel='chrome',headless=True)
        try:
            page=browser.new_page(viewport={'width':width,'height':height})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/studio#market',wait_until='domcontentloaded')
            page.get_by_text('研究估计 · 尚未发布').wait_for(timeout=30000)
            page.locator('.lv3-pipeline-state').get_by_text(latest['asof_session'],exact=False).wait_for()
            for h in (1,3,5):
                page.locator(f'[data-lv3-h="{h}"]').click()
                page.get_by_role('heading',name=f'H{h} · 这次概率如何算出').wait_for()
                assert page.locator(f'[data-lv3-h="{h}"]').get_attribute('aria-pressed')=='true'
                assert latest['horizons'][str(h)]['admitted_probabilities'] is None
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert errors==[]
        finally:
            browser.close()
