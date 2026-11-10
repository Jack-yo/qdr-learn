"""Explicit gap and anomaly reporting; never silently deletes data or awards research grade."""
from datetime import datetime, timezone
import html
import json
from pathlib import Path


def audit(store, clock, symbols, start, end, source, feed, cutoff=None):
    from datetime import date
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("Start exceeds end")
    sessions = {s.date() for s in clock.calendar.sessions_in_range(start, end)}
    cutoff = cutoff or datetime.now(timezone.utc)
    table = store.prices(source, feed, cutoff)
    rows = [r for r in table.to_pylist() if str(r["date"]) >= start and str(r["date"]) <= end and r["symbol"] in symbols]
    gaps, anomalies, coverage = {}, [], {}
    for symbol in symbols:
        values = sorted((r for r in rows if r["symbol"] == symbol), key=lambda r: r["date"])
        dates = {r["date"] for r in values}
        missing = sorted(sessions - dates)
        gaps[symbol] = [str(d) for d in missing]
        coverage[symbol] = {"rows": len(values), "expected_sessions": len(sessions), "missing": len(missing),
                            "first_date": str(values[0]["date"]) if values else None,
                            "last_date": str(values[-1]["date"]) if values else None}
        previous = None
        for row in values:
            if row["date"] not in sessions:
                anomalies.append({"symbol": symbol, "date": str(row["date"]), "reason": "NON_SESSION"})
            if row["volume"] == 0:
                anomalies.append({"symbol": symbol, "date": str(row["date"]), "reason": "ZERO_VOLUME"})
            if previous is not None and abs(row["close"] / previous - 1) > 0.4:
                anomalies.append({"symbol": symbol, "date": str(row["date"]), "reason": "EXTREME_PRICE_MOVE_ACTION_REVIEW_REQUIRED"})
            previous = row["close"]
    missing_total = sum(c["missing"] for c in coverage.values())
    bases = sorted({r["adjustment_basis"] for r in rows})
    return {"source": source, "feed": feed, "start": start, "end": end, "rows": len(rows),
        "coverage": coverage, "missing_sessions": missing_total, "gaps": gaps, "anomalies": anomalies,
        "coverage_complete": missing_total == 0 and len(rows) > 0,
        "adjustment_bases": bases, "raw_execution_prices_available": bool(rows) and bases == ["raw"] and source != "SYNTHETIC_FIXTURE",
        "adjusted_close_rows": sum(r.get("adj_close") is not None for r in rows),
        "research_grade": False, "status": "DATA_INCOMPLETE",
        "flags": ["DATA_INCOMPLETE", "NOT_READY"] + (["SYNTHETIC"] if source == "SYNTHETIC_FIXTURE" else ["EXPLORATORY", "SURVIVORSHIP_BIASED", "CORPORATE_ACTIONS_UNVERIFIED", "IDENTITY_UNVERIFIED"]) + (["NOT_RAW_EXECUTION_PRICE"] if source == "YAHOO" else []),
        "limitations": ["Current requested symbols are not historical PIT membership", "OHLC price returns are not automatically total returns; vendor adjusted close is stored separately",
                         "First-observed timestamps do not prove historical availability", "No cross-vendor or corporate-action reconciliation"],
        "data_cutoff_utc": cutoff.isoformat(), "created_at_utc": datetime.now(timezone.utc).isoformat()}


def write_audit(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    (destination / "audit.json").write_text(payload, encoding="utf-8")
    body = html.escape(payload)
    (destination / "audit.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Data audit</title>'
        '<style>body{font:15px system-ui;margin:2rem;max-width:1100px}pre{white-space:pre-wrap}</style>'
        '<h1>Data audit — DATA_INCOMPLETE / NOT_READY</h1><p>No strategy performance or research-grade claim.</p><pre>'
        + body + '</pre></html>', encoding="utf-8")
