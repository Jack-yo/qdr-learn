"""Post-close evidence report, separate from forecasts and execution state."""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.close_snapshot import latest_ready_session, read_snapshot
from quant_research.data.http import atomic_write
from quant_research.data.store import duckdb
from quant_research.policy import PolicyError
from .common import report


OUTPUT = Path("outputs/daily_observations")
ARTIFACTS = ("observation.json", "quotes.csv", "report.html")


def expected_session():
    return latest_ready_session(TradingClock(), datetime.now(timezone.utc)).date().isoformat()


def _style_context(root, day, cutoff):
    from .styles import calculate

    try:
        _, _, _, evidence = calculate(root, cutoff=cutoff)
        if evidence["asof_date_et"] > day:
            raise PolicyError("STYLE_DATE_AFTER_OBSERVATION", "Style evidence extends past the observation session")
    except (ValueError, OSError, duckdb.Error) as exc:
        return {"status": "BLOCKED", "code": getattr(exc, "code", type(exc).__name__)}
    return {name: evidence[name] for name in (
        "status", "source", "use_policy", "asof_date_et", "data_cutoff_utc",
        "snapshot_sha256", "source_provenance", "latest",
    )}


def generate(root, asof=None):
    root = Path(root).resolve()
    day = date.fromisoformat(asof).isoformat() if asof else expected_session()
    snapshot = read_snapshot(root, day)
    if (snapshot["source"], snapshot["feed"], snapshot["adjustment_basis"]) != ("ALPACA", "sip", "raw"):
        raise PolicyError("DAILY_SCOPE_REJECTED", "Daily observation requires the reviewed SIP raw snapshot")
    cutoff = datetime.fromisoformat(snapshot["frozen_at_utc"])
    prices = pd.DataFrame(snapshot["rows"])
    prices["bar_open_to_close"] = prices.close.div(prices.open).sub(1)
    for field in ("source", "feed", "adjustment_basis", "capture_sha256"):
        prices[field] = snapshot[field]
    spy = prices.loc[prices.symbol.eq("SPY"), "bar_open_to_close"].item()
    changes = prices.bar_open_to_close
    style = _style_context(root, day, cutoff)
    run_id = str(uuid4())
    data = {
        "run_id": run_id, "workflow": "daily-observation", "status": "OBSERVATION_READY",
        "source": snapshot["source"], "feed": snapshot["feed"],
        "adjustment_basis": snapshot["adjustment_basis"], "session_date_et": day,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_cutoff_utc": snapshot["capture_started_at_utc"],
        "frozen_at_utc": snapshot["frozen_at_utc"], "next_open_utc": snapshot["next_open_utc"],
        "capture_sha256": snapshot["capture_sha256"], "source_provenance": snapshot["source_provenance"],
        "market_observation": {
            "scope": "EXPLICIT_ETF_LIST_SAME_VENDOR_BAR",
            "spy_bar_open_to_close": float(spy),
            "etf_up": int(changes.gt(0).sum()), "etf_down": int(changes.lt(0).sum()),
            "etf_flat": int(changes.eq(0).sum()), "etf_count": len(changes),
        },
        "style_observation": style, "model_version": None, "strategy_version": None,
        "signal_status": "BLOCKED_NO_ELIGIBLE_MODEL", "candidates": [],
        "signal_missing_evidence": [
            "accepted decision-time price features and permanent security identities",
            "frozen eligible model and strategy decision for this session",
            "accepted corporate-action ledger and executable risk inputs",
        ],
        "execution_ready": False, "decision_eligible": False, "real_orders_enabled": False,
        "research_grade": False, "sealed_test_used": False,
    }
    output = root / OUTPUT / run_id
    output.mkdir(parents=True)
    quotes = prices[["symbol", "date", "open", "high", "low", "close", "volume",
                     "bar_open_to_close", "event_time", "available_at", "raw_sha256",
                     "source", "feed", "adjustment_basis", "capture_sha256"]]
    quotes.to_csv(output / "quotes.csv", index=False, encoding="utf-8-sig")
    atomic_write(output / "observation.json", json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode())
    report(output, "每日真实行情观察", data, {
        "SIP 原始行情及单根日线开收变化": quotes,
        "French 风格观察（独立数据日期）": pd.DataFrame(style.get("latest", [])),
    }, note="SIP 指标使用同一根供应商日线的开盘和收盘。French 风格按独立可用日期展示。候选生成资格缺失。")
    manifest = {
        **data, "artifacts_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ARTIFACTS
        },
    }
    atomic_write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode())
    return manifest


def latest_report(root, asof=None):
    root = Path(root).resolve()
    matches = []
    for path in (root / OUTPUT).glob("*/manifest.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("workflow") != "daily-observation" or metadata.get("run_id") != path.parent.name:
            raise PolicyError("DAILY_REPORT_MANIFEST_INVALID", "Daily observation manifest is invalid")
        if asof is None or metadata["session_date_et"] == asof:
            matches.append((metadata["session_date_et"], metadata["generated_at_utc"], path, metadata))
    if not matches:
        raise PolicyError("DAILY_OBSERVATION_NOT_FOUND", "Freeze the SIP session then generate its observation report")
    _, _, path, metadata = max(matches, key=lambda item: item[:2])
    for name in ARTIFACTS:
        artifact = path.parent / name
        expected = metadata["artifacts_sha256"].get(name)
        if (not artifact.resolve().is_relative_to(path.parent.resolve()) or not artifact.is_file()
                or hashlib.sha256(artifact.read_bytes()).hexdigest() != expected):
            raise PolicyError("DAILY_REPORT_ARTIFACT_CORRUPT", "Daily observation artifact failed SHA256 verification")
    data = json.loads((path.parent / "observation.json").read_text(encoding="utf-8"))
    if (data["status"] != "OBSERVATION_READY" or data["candidates"] != []
            or any(data[key] != metadata[key] for key in ("run_id", "session_date_et", "capture_sha256"))
            or any(data[key] is not False for key in ("decision_eligible", "execution_ready",
                                                    "real_orders_enabled", "sealed_test_used"))):
        raise PolicyError("DAILY_REPORT_SCOPE_REJECTED", "Daily observation report failed scope verification")
    current = expected_session()
    return {**data, "expected_session_et": current,
            "freshness": "CURRENT_SESSION" if data["session_date_et"] == current else "ARCHIVED_SESSION",
            "artifacts": {name: (path.parent / name).relative_to(root).as_posix() for name in ARTIFACTS}}


def execute(args):
    manifest = generate(Path.cwd(), args.asof)
    print(json.dumps({
        "run_id": manifest["run_id"], "status": manifest["status"],
        "session_date_et": manifest["session_date_et"], "signal_status": manifest["signal_status"],
        "style_status": manifest["style_observation"]["status"],
    }))
    return 0
