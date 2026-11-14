"""Capture the live local V4 UI at the design package's three viewports.

Requires an already running local research service and Playwright. Screenshots
are evidence of its actual data and empty states, not market test fixtures.
"""
from pathlib import Path
import html
import json
import sys
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'ui_visual_audit'
REFERENCE = ROOT / '.codex_qdr_design_review' / '01_高保真原图'
PAGES = [('overview','01_总览.png'), ('market','02_市场状态预测.png'),
         ('style','03_经典因子跟踪.png'), ('lab','04_自定义因子实验室.png'),
         ('screen','05_因子组选股与模拟回测.png'), ('risk','06_持仓管理与风控预警.png')]
SIZES = [(1920,1080), (1440,900), (375,844)]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':1920,'height':1080}, device_scale_factor=1)
        for route, reference in PAGES:
            try:
                page.goto('http://127.0.0.1:8766/studio?visual-audit=1#'+route,
                          wait_until='domcontentloaded', timeout=30000)
                page.locator('#content .heading').wait_for(state='visible', timeout=120000)
                for width, height in SIZES:
                    page.set_viewport_size({'width':width,'height':height})
                    name=f'{route}_{width}x{height}.png'
                    page.screenshot(path=str(OUT/name))
                    dimensions=page.evaluate('''() => ({width:innerWidth,
                        documentWidth:document.documentElement.scrollWidth,
                        bodyWidth:document.body.scrollWidth,
                        duplicateIds:[...document.querySelectorAll('[id]')].map(x=>x.id)
                          .filter((id,i,all)=>all.indexOf(id)!==i)})''')
                    results.append({'page':route, 'reference':reference, 'image':name,
                                    'viewport':[width,height], **dimensions})
            except Exception as exc:
                results.append({'page':route,'reference':reference,'error':str(exc)})
        browser.close()
    (OUT/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=[]
    for route, ref in PAGES:
        source='../../.codex_qdr_design_review/01_高保真原图/'+ref
        rows.append('<h2>'+html.escape(route)+'</h2><div class="pair"><figure><figcaption>参考原图</figcaption>'
                    '<img src="'+html.escape(source,quote=True)+'"></figure><figure><figcaption>本地实际页面 1920 × 1080</figcaption>'
                    '<img src="'+route+'_1920x1080.png"></figure></div>')
    report='<!doctype html><meta charset="utf-8"><title>QDR 六页视觉对照</title><style>body{background:#101827;color:#eee;font:16px sans-serif}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}img{width:100%}figcaption{padding:8px}</style><h1>QDR 六页视觉对照</h1><p>右侧为本地真实数据与空状态。窗口适配截图及尺寸检查见同目录 results.json。</p>'+''.join(rows)
    (OUT/'comparison.html').write_text(report,encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    failures=[r for r in results if 'error' in r or r.get('documentWidth',0)>r['viewport'][0]
              or r.get('bodyWidth',0)>r['viewport'][0] or r.get('duplicateIds')]
    if len(results)!=len(PAGES)*len(SIZES) or failures:
        sys.exit(1)

if __name__ == '__main__':
    main()
