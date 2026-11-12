"""Run the actual loopback QDR server in Chromium and retain UI evidence."""

from __future__ import annotations

import json
import argparse
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright

from quant_research.web import Console, ThreadingHTTPServer, handler


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/local_acceptance/browser"
ROUTES = ("overview", "market", "style", "lab", "screen", "risk", "data")
WIDTHS = (1440, 1920, 375)
HEADINGS = dict(zip(ROUTES, ("研究总览", "市场状态预测", "经典因子与风格跟踪",
                             "自定义因子实验室", "因子组选股与模拟回测",
                             "持仓管理与风控预警", "数据中心与研究资格")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", default="1440,1920,375")
    args = parser.parse_args()
    widths = tuple(int(x) for x in args.widths.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    report = {"base": base, "routes": [], "api": {}, "advanced": []}
    try:
        with sync_playwright() as browser_runtime:
            browser = browser_runtime.chromium.launch(headless=True)
            try:
                for width in widths:
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
                    for route in ROUTES:
                        entry = {"width": width, "route": route}
                        try:
                            response = page.goto(f"{base}/studio#{route}", wait_until="domcontentloaded")
                            page.get_by_role("heading", name=HEADINGS[route]).first.wait_for(timeout=45000)
                            page.wait_for_timeout(350)
                            entry.update({"http": response.status if response else "same-document-navigation",
                                          "heading": page.locator("#content h1").first.inner_text(),
                                          "tabs": page.get_by_role("tab").count(),
                                          "horizontal_overflow_px": page.evaluate("Math.max(0, document.documentElement.scrollWidth-innerWidth)"),
                                          "trading_date": page.locator("#v4-trading-date").inner_text(),
                                          "source_status": page.locator("#v4-source-status").inner_text()})
                            if route == "data":
                                entry["freshness_table_visible"] = page.get_by_text("统一决策时点与模块新鲜度").count() > 0
                            if route in ("overview", "market", "data", "risk"):
                                page.screenshot(path=str(OUT / f"{route}_{width}.png"), full_page=True)
                        except Exception as exc:
                            entry["failure"] = f"{type(exc).__name__}: {str(exc)[:180]}"
                        entry["page_errors"] = list(errors)
                        errors.clear()
                        report["routes"].append(entry)
                        print(width, route, entry.get("heading", entry.get("failure")), flush=True)
                    page.close()
                page = browser.new_page()
                for route in ("/factors", "/strategies", "/backtests", "/signals", "/paper", "/data"):
                    response = page.goto(base + route, wait_until="domcontentloaded")
                    report["advanced"].append({"route": route, "http": response.status,
                                               "title": page.title()})
                for route in ("/api/v1/v4/freshness", "/api/v1/v4/daily", "/api/v1/v4/plans"):
                    response = page.request.get(base + route)
                    body = response.json()
                    report["api"][route] = {"http": response.status,
                                             "status": body.get("status"),
                                             "asof_session": body.get("asof_session")}
                page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    target = OUT / ("summary_" + "-".join(str(width) for width in widths) + ".json")
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target.relative_to(ROOT))
    print("route checks", len(report["routes"]), "page errors", sum(len(x["page_errors"]) for x in report["routes"]))
    print("overflow", [f"{x['route']}:{x['width']}={x['horizontal_overflow_px']}" for x in report["routes"] if x["horizontal_overflow_px"]])


if __name__ == "__main__":
    main()
