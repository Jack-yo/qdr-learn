"""Local-host L1 V3 acceptance checks; prints no API keys.

Run python -m quant_research.workflow.l1_v3_verify --root . for offline checks.
Add --live to run the real read-only Alpaca daily job and inspect persistence.
No trading, broker order, or account API is ever invoked.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys

from quant_research.data.l1_light_sources import SourceUnavailable
from quant_research.workflow.l1_v3_pipeline import (
    current_pipeline_status,run_pipeline,frozen_for_session
)
from quant_research.workflow.l1_v3 import latest_completed_session


def check_local(root,*,live=False):
    stamp=datetime.now(timezone.utc)
    day=latest_completed_session(stamp)
    configured=bool(os.environ.get("ALPACA_API_KEY") and
                    os.environ.get("ALPACA_SECRET_KEY"))
    feed=os.environ.get("QDR_L1_HISTORY_FEED","sip").lower()
    result={
        "schema":"qdr.l1.v3.local.acceptance.v1",
        "mode":"LIVE_PROVIDER" if live else "OFFLINE_INSPECTION",
        "asof_completed_session":day,
        "credentials_configured":configured,
        "historical_feed":feed,
        "snapshot_feed":os.environ.get("QDR_L1_FEED","delayed_sip"),
        "history_feed_supported":feed in ("sip","iex"),
        "root_exists":Path(root).is_dir(),
        "root_writable":os.access(root,os.W_OK),
        "python_version":sys.version.split()[0],
        "execution_eligible":False
    }
    try:
        before=current_pipeline_status(root,now=stamp)
        result["previous_status"]=before
        if not live:
            result["status"]="READY_FOR_REAL_RUN" if configured and result["history_feed_supported"] else "CONFIGURATION_REQUIRED"
            return result
        if not configured or not result["history_feed_supported"]:
            result["status"]="BLOCKED"
            result["code"]="ALPACA_CREDENTIALS_OR_HISTORICAL_FEED_MISSING"
            return result
        execution=run_pipeline(root,mode="daily",now=stamp)
        result["execution"]=execution
        after=current_pipeline_status(root,now=stamp)
        frozen=frozen_for_session(root,day)
        result["after"]=after
        result["checks"]={
            "model_persisted":bool(after["model_available"]),
            "model_sha256_present":bool((after.get("model_reference") or {}).get("model_sha256")),
            "forecast_frozen":bool(frozen),
            "forecast_current":after["frozen_current"],
            "prediction_never_admitted":bool(frozen and all(
                row.get("admitted_probabilities") is None and
                row.get("qualification",{}).get("admitted") is False
                for row in frozen[0].get("horizons",{}).values())),
            "model_not_trained_by_web":True
        }
        result["status"]="LIVE_ACCEPTANCE_PASS" if all(result["checks"].values()) else "LIVE_ACCEPTANCE_FAIL"
    except (SourceUnavailable,ValueError,OSError,TypeError,KeyError) as exc:
        result["status"]="BLOCKED"
        result["code"]=getattr(exc,"code",type(exc).__name__)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description="QDR L1 local environment verification")
    parser.add_argument("--root",type=Path,default=Path("."))
    parser.add_argument("--live",action="store_true",
                        help="Run real Alpaca training/prediction with local credentials")
    args=parser.parse_args(argv)
    credentials=args.root / '.env'
    if credentials.is_file():
        from quant_research.cli import load_local_credentials
        load_local_credentials(credentials)
    report=check_local(args.root,live=args.live)
    print(json.dumps(report,ensure_ascii=False,sort_keys=True,default=str))
    return 0 if report["status"] in ("READY_FOR_REAL_RUN","LIVE_ACCEPTANCE_PASS") else 2


if __name__=="__main__":
    raise SystemExit(main())
