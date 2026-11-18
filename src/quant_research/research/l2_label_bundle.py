"""Immutable small L2 style-label research bundles.

This is not a historical market warehouse. A bundle stores only derived style
labels plus hashes of the independently reviewed price/action evidence used to
construct them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from quant_research.research.l2_forecast import (
    HORIZONS, STYLE_IDS, validate_forward_labels_v1,
)
from quant_research.research.l2_labels import REQUIRED_PRICE_BASIS


BUNDLE_SCHEMA = "qdr.l2.style-label-bundle.v1"


def _canonical(value: dict) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _valid_bundle_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", value):
        raise ValueError("Invalid L2 label bundle ID")
    return value


def _digest(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze_label_bundle_v1(
    root: Path,
    bundle_id: str,
    labels: pd.DataFrame,
    trading_clock,
    *,
    source_evidence_sha256: str,
    action_evidence_version: str,
    price_basis: str = REQUIRED_PRICE_BASIS,
) -> dict:
    """Write one immutable, source-hashed derived-label bundle."""
    root = Path(root).resolve()
    bundle_id = _valid_bundle_id(bundle_id)
    if not re.fullmatch(r"[0-9a-f]{64}", str(source_evidence_sha256)):
        raise ValueError("source_evidence_sha256 must be lowercase SHA256")
    if price_basis != REQUIRED_PRICE_BASIS:
        raise ValueError("L2 label bundle price basis is not accepted")
    if not isinstance(action_evidence_version, str) or not action_evidence_version.strip():
        raise ValueError("action_evidence_version is required")

    validated = validate_forward_labels_v1(labels, trading_clock)
    observed = validated.forward_relative_return.notna()
    if observed.sum() == 0:
        raise ValueError("L2 label bundle contains no verified outcomes")
    if set(validated.loc[observed, "style_id"]) != set(STYLE_IDS):
        raise ValueError("L2 label bundle must include all seven styles")
    if set(validated.loc[observed, "horizon"]) != set(HORIZONS):
        raise ValueError("L2 label bundle must include H1/H3/H5")

    parent = root / "data/managed/l2_style_labels"
    destination = parent / bundle_id
    if destination.exists():
        raise FileExistsError("L2 label bundle is immutable and already exists")
    parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".l2-label-", dir=parent))
    try:
        parquet = temp / "labels.parquet"
        validated.to_parquet(parquet, index=False)
        label_sha = _digest(parquet)
        manifest = {
            "schema": BUNDLE_SCHEMA,
            "bundle_id": bundle_id,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "labels_path": "labels.parquet",
            "labels_sha256": label_sha,
            "source_evidence_sha256": source_evidence_sha256,
            "price_basis": price_basis,
            "action_evidence_version": action_evidence_version,
            "rows": int(len(validated)),
            "verified_rows": int(observed.sum()),
            "first_signal_session": validated.date.min().date().isoformat(),
            "last_signal_session": validated.date.max().date().isoformat(),
            "styles": list(STYLE_IDS),
            "horizons": list(HORIZONS),
            "historical_pit_attested": False,
            "model_admitted": False,
            "real_orders_enabled": False,
        }
        (temp / "manifest.json").write_text(
            _canonical(manifest), encoding="utf-8"
        )
        temp.rename(destination)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return manifest


def load_label_bundle_v1(root: Path, bundle_id: str, trading_clock) -> tuple[pd.DataFrame, dict]:
    """Read and re-validate one immutable label bundle."""
    root = Path(root).resolve()
    bundle_id = _valid_bundle_id(bundle_id)
    folder = root / "data/managed/l2_style_labels" / bundle_id
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("L2_LABEL_BUNDLE_NOT_FOUND")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema", "bundle_id", "labels_path", "labels_sha256",
        "source_evidence_sha256", "price_basis", "action_evidence_version",
        "rows", "verified_rows", "styles", "horizons",
    }
    if required - set(manifest):
        raise ValueError("L2_LABEL_BUNDLE_MANIFEST_INCOMPLETE")
    if manifest["schema"] != BUNDLE_SCHEMA or manifest["bundle_id"] != bundle_id:
        raise ValueError("L2_LABEL_BUNDLE_IDENTITY_MISMATCH")
    if manifest["price_basis"] != REQUIRED_PRICE_BASIS:
        raise ValueError("L2_LABEL_BUNDLE_PRICE_BASIS_REJECTED")
    if set(manifest["styles"]) != set(STYLE_IDS) or set(manifest["horizons"]) != set(HORIZONS):
        raise ValueError("L2_LABEL_BUNDLE_SCOPE_MISMATCH")
    label_path = folder / manifest["labels_path"]
    if not label_path.is_file() or label_path.parent != folder:
        raise ValueError("L2_LABEL_BUNDLE_PATH_INVALID")
    if _digest(label_path) != manifest["labels_sha256"]:
        raise ValueError("L2_LABEL_BUNDLE_HASH_MISMATCH")
    labels = validate_forward_labels_v1(pd.read_parquet(label_path), trading_clock)
    if len(labels) != int(manifest["rows"]):
        raise ValueError("L2_LABEL_BUNDLE_ROW_COUNT_MISMATCH")
    if int(labels.forward_relative_return.notna().sum()) != int(manifest["verified_rows"]):
        raise ValueError("L2_LABEL_BUNDLE_VERIFIED_COUNT_MISMATCH")
    return labels, manifest
