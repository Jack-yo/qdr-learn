"""Explicit P4 forecast freeze command; GET endpoints never call this module."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_research.research.l2_forecast_archive import freeze_forecast_snapshot_v1
from quant_research.workflow.l2_forecast import calculate_forecast


def freeze_current_forecast(root: Path, *, asof: str | None = None) -> dict:
    root=Path(root).resolve()
    forecast=calculate_forecast(root,asof=asof)
    if forecast.get("status")!="RESEARCH_ONLY":
        return {
            "status":"BLOCKED_NO_ARCHIVE_WRITE",
            "code":forecast.get("code") or "L2_FORECAST_NOT_RESEARCH_READY",
            "asof_session":forecast.get("asof_session") or asof,
            "eligible_units":forecast.get("eligible_units",0),
            "blocked_units":forecast.get("blocked_units",21),
            "real_orders_enabled":False,
        }
    frozen=freeze_forecast_snapshot_v1(root,forecast)
    return {
        "status":frozen["status"],
        "session_date_et":frozen["session_date_et"],
        "identity":frozen["identity"],
        "model_version":frozen["model_version"],
        "eligible_units":frozen["eligible_units"],
        "blocked_units":frozen["blocked_units"],
        "source_snapshot_sha256":frozen["source_snapshot_sha256"],
        "label_bundle_sha256":frozen["label_bundle_sha256"],
        "real_orders_enabled":False,
    }


def main(argv=None):
    parser=argparse.ArgumentParser(description="Freeze one QDR L2 research forecast snapshot; no orders")
    parser.add_argument("--root",type=Path,default=Path.cwd())
    parser.add_argument("--date",default=None,help="Completed XNYS session YYYY-MM-DD; default latest source session")
    args=parser.parse_args(argv)
    result=freeze_current_forecast(args.root,asof=args.date)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result["status"]=="FROZEN_L2_RESEARCH_ONLY" else 4


if __name__=="__main__":
    raise SystemExit(main())
