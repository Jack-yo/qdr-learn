"""One-command four-layer EOD research progression.

Sequence:
1) freeze genuine-forward L2 P4 evidence;
2) stop normally while L2 admission is still pending;
3) once admitted, derive a new immutable L2-bound V4 bundle;
4) run L3/L4 research pipeline;
5) return read-only four-layer evidence status.

No P5 walk-forward is silently rerun here and no order path is enabled.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from quant_research.workflow.l2_downstream import build_downstream_context
from quant_research.workflow.l2_forecast_freeze import freeze_current_forecast
from quant_research.workflow.v4_l2_bind_bundle import create_l2_bound_v4_bundle
from quant_research.workflow.v4_layer_status import four_layer_status
from quant_research.workflow.v4_ops import run_v4_pipeline_day


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _default_bound_id(source_bundle_id: str, session_date: str) -> str:
    suffix = "-l2-" + session_date.replace("-", "")
    keep = 64 - len(suffix)
    value = source_bundle_id[:keep] + suffix
    if not _ID.fullmatch(value):
        raise ValueError("Unable to derive safe bound bundle ID")
    return value


def run_four_layer_research_day(
    root: Path,
    session_date: str,
    *,
    source_bundle_id: str,
    bound_bundle_id: str | None = None,
    research_budget: float | None = None,
) -> dict:
    """Advance only evidence-supported research stages for one completed session."""
    if not _ID.fullmatch(str(source_bundle_id)):
        raise ValueError("Invalid source V4 bundle ID")
    bound_bundle_id = (
        bound_bundle_id
        or _default_bound_id(source_bundle_id, session_date)
    )
    if not _ID.fullmatch(str(bound_bundle_id)):
        raise ValueError("Invalid bound V4 bundle ID")
    root = Path(root).resolve()

    l2_forward = freeze_current_forecast(
        root,
        asof=session_date,
        prospective_only=True,
    )
    if l2_forward.get("status") != "FROZEN_L2_FORWARD_RESEARCH_ONLY":
        return {
            "status": "L2_FORWARD_FREEZE_BLOCKED_NO_L3_WRITE",
            "code": l2_forward.get("code") or l2_forward.get("status"),
            "session_date_et": session_date,
            "l2_forward": l2_forward,
            "bound_bundle_id": None,
            "l3_l4_pipeline": None,
            "four_layer": four_layer_status(
                root, asof=session_date, horizon=3
            ),
            "decision_eligible": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
        }

    l2_context = build_downstream_context(root, asof=session_date)
    if l2_context.get("status") != "MODEL_ADMITTED_CONTEXT":
        return {
            "status": "L2_FORWARD_EVIDENCE_CAPTURED_ADMISSION_PENDING",
            "code": l2_context.get("code") or "L2_MODEL_ADMISSION_PENDING",
            "session_date_et": session_date,
            "l2_forward": l2_forward,
            "l2_admitted_units": int(l2_context.get("admitted_units") or 0),
            "bound_bundle_id": None,
            "l3_l4_pipeline": None,
            "four_layer": four_layer_status(
                root, asof=session_date, horizon=3
            ),
            "decision_eligible": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
        }

    try:
        bound = create_l2_bound_v4_bundle(
            root,
            source_bundle_id=source_bundle_id,
            output_bundle_id=bound_bundle_id,
            expected_current_session=session_date,
        )
    except (OSError, ValueError, KeyError, TypeError, FileExistsError) as exc:
        return {
            "status": "L2_L3_BOUND_BUNDLE_BLOCKED",
            "code": str(exc)[:180] or type(exc).__name__,
            "session_date_et": session_date,
            "l2_forward": l2_forward,
            "l2_admitted_units": int(l2_context.get("admitted_units") or 0),
            "bound_bundle_id": bound_bundle_id,
            "l3_l4_pipeline": None,
            "four_layer": four_layer_status(
                root, asof=session_date, horizon=3
            ),
            "decision_eligible": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
        }

    pipeline = run_v4_pipeline_day(
        root,
        session_date,
        bundle_id=bound_bundle_id,
        research_budget=research_budget,
    )
    layers = four_layer_status(root, asof=session_date, horizon=3)
    pipeline_ok = pipeline.get("status") == "RESEARCH_PLAN_AND_DIARY_SAVED"
    return {
        "status": (
            "FOUR_LAYER_RESEARCH_DAY_SAVED"
            if pipeline_ok and layers.get("complete_four_layer_context") is True
            else "FOUR_LAYER_RESEARCH_DAY_PARTIALLY_BLOCKED"
        ),
        "code": None if pipeline_ok else pipeline.get("code") or pipeline.get("status"),
        "session_date_et": session_date,
        "l2_forward": l2_forward,
        "l2_admitted_units": int(l2_context.get("admitted_units") or 0),
        "bound_bundle": bound,
        "bound_bundle_id": bound_bundle_id,
        "l3_l4_pipeline": pipeline,
        "four_layer": layers,
        "decision_eligible": False,
        "execution_eligible": False,
        "real_orders_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="QDR four-layer EOD research progression; never places orders"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--bound-bundle", default=None)
    parser.add_argument("--research-budget", type=float, default=None)
    args = parser.parse_args(argv)
    result = run_four_layer_research_day(
        args.root,
        args.date,
        source_bundle_id=args.source_bundle,
        bound_bundle_id=args.bound_bundle,
        research_budget=args.research_budget,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] in {
        "L2_FORWARD_EVIDENCE_CAPTURED_ADMISSION_PENDING",
        "FOUR_LAYER_RESEARCH_DAY_SAVED",
    } else 4


if __name__ == "__main__":
    raise SystemExit(main())
