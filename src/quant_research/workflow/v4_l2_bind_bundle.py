"""Create a new immutable V4 input bundle bound to admitted L2 style context.

The source bundle is never modified. Only market_style.parquet is materialized
with canonical style_l2_* columns; all other verified input bytes are copied.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from quant_research.workflow.l2_l3_binding import (
    build_l2_style_history_binding,
    materialize_l2_style_history,
    validate_l2_style_binding_receipt,
)
from quant_research.workflow.v4_study_cli import _checked_inputs


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _same_base_market_evidence(original: pd.DataFrame, bound: pd.DataFrame) -> None:
    """Require the derived file to change only style_* and state availability."""
    if len(original) != len(bound):
        raise ValueError("L2_BOUND_MARKET_STYLE_ROW_COUNT_CHANGED")
    original_dates = pd.to_datetime(original["date"], errors="raise")
    bound_dates = pd.to_datetime(bound["date"], errors="raise")
    if not original_dates.equals(bound_dates):
        raise ValueError("L2_BOUND_MARKET_STYLE_DATES_CHANGED")
    protected = [
        column for column in original.columns
        if not column.startswith("style_") and column != "state_available_at"
    ]
    missing = set(protected) - set(bound.columns)
    if missing:
        raise ValueError("L2_BOUND_MARKET_EVIDENCE_DROPPED")
    for column in protected:
        left = original[column].reset_index(drop=True)
        right = bound[column].reset_index(drop=True)
        try:
            pd.testing.assert_series_equal(
                left, right, check_names=False, check_dtype=False
            )
        except AssertionError as exc:
            raise ValueError(
                "L2_BOUND_MARKET_EVIDENCE_CHANGED:" + column
            ) from exc


def create_l2_bound_v4_bundle(
    root: Path,
    *,
    source_bundle_id: str,
    output_bundle_id: str,
) -> dict:
    """Materialize admitted L2 style inputs into a new V4 managed bundle."""
    if not _ID.fullmatch(str(source_bundle_id)):
        raise ValueError("Invalid source V4 bundle ID")
    if not _ID.fullmatch(str(output_bundle_id)):
        raise ValueError("Invalid output V4 bundle ID")
    if source_bundle_id == output_bundle_id:
        raise ValueError("L2_BOUND_BUNDLE_REQUIRES_NEW_ID")

    root = Path(root).resolve()
    frames, manifest = _checked_inputs(root, source_bundle_id)
    source_folder = root / "data/managed/v4_inputs" / source_bundle_id
    parent = root / "data/managed/v4_inputs"
    destination = parent / output_bundle_id
    if "market_style" not in frames:
        raise ValueError("L2_BOUND_MARKET_STYLE_INPUT_MISSING")

    bound_style = materialize_l2_style_history(root, frames["market_style"])
    _same_base_market_evidence(frames["market_style"], bound_style)
    receipt = validate_l2_style_binding_receipt(
        build_l2_style_history_binding(root, bound_style)
    )
    source_manifest_path = source_folder / "manifest.json"
    source_manifest_sha = _digest(source_manifest_path)

    if destination.exists():
        try:
            _existing_frames, existing_manifest = _checked_inputs(
                root, output_bundle_id
            )
            existing_receipt = validate_l2_style_binding_receipt(
                existing_manifest.get("l2_style_context_receipt")
            )
        except Exception as exc:
            raise FileExistsError(
                "L2_BOUND_V4_BUNDLE_EXISTS_BUT_IS_NOT_VERIFIABLE"
            ) from exc
        if (
            existing_manifest.get("derived_from_bundle_id") == source_bundle_id
            and existing_manifest.get("derived_from_manifest_sha256")
                == source_manifest_sha
            and existing_receipt.get("context_identity_sha256")
                == receipt.get("context_identity_sha256")
        ):
            return {
                "status": "L2_BOUND_V4_BUNDLE_ALREADY_EXISTS",
                "source_bundle_id": source_bundle_id,
                "output_bundle_id": output_bundle_id,
                "market_style_rows": int(len(_existing_frames["market_style"])),
                "l2_style_binding_context_sha256":
                    existing_receipt["context_identity_sha256"],
                "l2_style_historical_pit_attested":
                    existing_receipt["historical_pit_attested"],
                "artifacts_sha256": existing_manifest["artifacts_sha256"],
                "decision_eligible": False,
                "real_orders_enabled": False,
            }
        raise FileExistsError("L2_BOUND_V4_BUNDLE_IDENTITY_CONFLICT")

    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".l2-bound-", dir=parent))
    try:
        digests = dict(manifest["artifacts_sha256"])
        for filename in digests:
            if filename == "market_style.parquet":
                target = temp / filename
                bound_style.to_parquet(target, index=False)
                digests[filename] = _digest(target)
            else:
                source = source_folder / filename
                if not source.is_file():
                    raise ValueError("L2_BOUND_SOURCE_ARTIFACT_MISSING:" + filename)
                shutil.copy2(source, temp / filename)
                if _digest(temp / filename) != digests[filename]:
                    raise ValueError("L2_BOUND_SOURCE_ARTIFACT_CHANGED:" + filename)

        output_manifest = {
            **manifest,
            "artifacts_sha256": digests,
            "l2_style_context_receipt": receipt,
            "derived_from_bundle_id": source_bundle_id,
            "derived_from_manifest_sha256": source_manifest_sha,
            "l2_binding_materialized_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision_eligible": False,
            "real_orders_enabled": False,
        }
        (temp / "manifest.json").write_text(
            json.dumps(
                output_manifest, ensure_ascii=False, sort_keys=True,
                indent=2, allow_nan=False,
            ),
            encoding="utf-8",
        )
        temp.rename(destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    # Re-open through the normal V4 contract. This verifies every output byte
    # and structurally validates the embedded L2 receipt before returning.
    # A failed self-check removes only the bundle created by this invocation.
    try:
        checked_frames, checked_manifest = _checked_inputs(root, output_bundle_id)
        if len(checked_frames["market_style"]) != len(bound_style):
            raise ValueError("L2_BOUND_V4_BUNDLE_POSTWRITE_MISMATCH")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {
        "status": "L2_BOUND_V4_BUNDLE_CREATED_RESEARCH_ONLY",
        "source_bundle_id": source_bundle_id,
        "output_bundle_id": output_bundle_id,
        "market_style_rows": int(len(bound_style)),
        "l2_style_binding_context_sha256": receipt["context_identity_sha256"],
        "l2_style_historical_pit_attested": receipt["historical_pit_attested"],
        "artifacts_sha256": checked_manifest["artifacts_sha256"],
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create new immutable V4 bundle with admitted L2 style context"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--output-bundle", required=True)
    args = parser.parse_args(argv)
    result = create_l2_bound_v4_bundle(
        args.root,
        source_bundle_id=args.source_bundle,
        output_bundle_id=args.output_bundle,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
