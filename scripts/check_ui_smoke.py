"""G11 browser-level no-data negative-path smoke; no demo prices, trades or P&L."""
from pathlib import Path
import json
import shutil
import argparse
from playwright.sync_api import sync_playwright

project=Path(__file__).resolve().parents[1]
base=(project/'src/quant_research' if (project/'src/quant_research').exists() else project/'quant_research')
args=argparse.ArgumentParser(description='Blocked-only UI smoke test with no sample market data')
args.add_argument('--screenshots',type=Path,default=None,help='Optional output directory for no-data screenshots')
options=args.parse_args()
if options.screenshots:options.screenshots.mkdir(parents=True,exist_ok=True)
html=(base/'app_shell.html').read_text(encoding='utf-8').replace('__TOKEN__','not-a-real-server-token')
css=(base/'assets/studio.css').read_text(encoding='utf-8')
js=(base/'assets/studio.js').read_text(encoding='utf-8')
paths=['overview','market','styles','factors','strategies','backtests','signals','paper','data']
js_errors=[]
with sync_playwright() as pw:
 executable=shutil.which('chromium') or shutil.which('google-chrome') or shutil.which('chrome')
 browser=pw.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
 page=browser.new_page(viewport={'width':1440,'height':1000})
 page.on('pageerror',lambda error:js_errors.append(str(error)))
 for path in paths:
  page.set_content(html.replace('<link rel="stylesheet" href="/assets/studio.css"/>','').replace('<script src="/assets/studio.js" defer></script>',''))
  page.add_style_tag(content=css)
  page.add_script_tag(content=js.replace("const KEY=(location.pathname.split('/')[1]||'overview');",f"const KEY='{path}';"))
  page.wait_for_timeout(450)
  assert page.locator('#workspace h1').count()>0,(path,page.locator('#workspace').inner_text()[:500])
  print('UI',path,'OK',page.locator('#workspace h1').first.inner_text())
  if path=='backtests':
   assert page.locator('#verified-backtest-list').count()==1
   if options.screenshots:page.screenshot(path=str(options.screenshots/'G11_backtests_no_data.png'))
  if path=='data':
   assert page.locator('#pages-audit-run').count()==1
   page.locator('#pages-audit-run').click()
   page.wait_for_timeout(400)
   assert page.locator('#pages-result').count()==1
   if options.screenshots:page.screenshot(path=str(options.screenshots/'G11_data_evidence_no_data.png'))
 browser.close()
if js_errors:
 print('JS errors',js_errors)
 raise SystemExit(1)
print('G11 nine-page no-source browser smoke passed, no fabricated market state')
