"""Explicit P4 forecast freeze command; GET endpoints never call this module."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from quant_research.research.l2_forecast_archive import freeze_forecast_snapshot_v1
from quant_research.workflow.l2_forecast import calculate_forecast


def freeze_current_forecast(
    root: Path, *, asof: str | None = None,
    prospective_only: bool = False, now_utc=None
) -> dict:
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
    moment=pd.Timestamp(now_utc or datetime.now(timezone.utc))
    if moment.tzinfo is None:
        raise ValueError("L2_FORECAST_FREEZE_TIME_MUST_BE_AWARE")
    moment=moment.tz_convert("UTC")
    if prospective_only:
        from quant_research.clock import TradingClock
        try:
            window=TradingClock().window(
                forecast["asof_session"],1,now=moment.to_pydatetime()
            )
            in_window=(
                pd.Timestamp(window.signal_time)<=moment
                <pd.Timestamp(window.entry_time)
            )
        except ValueError:
            in_window=False
        if not in_window:
            return {
                "status":"BLOCKED_NO_ARCHIVE_WRITE",
                "code":"L2_NOT_IN_PROSPECTIVE_FREEZE_WINDOW",
                "asof_session":forecast.get("asof_session") or asof,
                "eligible_units":forecast.get("eligible_units",0),
                "blocked_units":forecast.get("blocked_units",21),
                "real_orders_enabled":False,
            }
    frozen=freeze_forecast_snapshot_v1(root,forecast,now_utc=moment)
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
    parser.add_argument(
        "--prospective-only",action="store_true",
        help="Write only between the T signal and T+1 open; otherwise no archive is created",
    )
    args=parser.parse_args(argv)
    result=freeze_current_forecast(
        args.root,asof=args.date,prospective_only=args.prospective_only
    )
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result["status"] in {
        "FROZEN_L2_FORWARD_RESEARCH_ONLY",
        "FROZEN_L2_RETROSPECTIVE_ASOF_ONLY",
        "FROZEN_L2_RESEARCH_ONLY",
    } else 4


if __name__=="__main__":
    raise SystemExit(main())
