"""V4 managed input bundles may carry a strict L2 style-binding receipt."""
from hashlib import sha256
import json

import pandas as pd
import pytest

from quant_research.workflow.v4_study_cli import _checked_inputs


def _receipt():
    return {
        "contract_version": "qdr-l2-l3-style-binding-v1",
        "scope": "HISTORICAL_AND_CURRENT",
        "start_session": "2026-01-30",
        "end_session": "2026-01-30",
        "rows": 1,
        "style_columns": ["style_l2_size_h3"],
        "context_identity_sha256": "1" * 64,
        "model_versions": ["ridge-v1"],
        "label_bundle_sha256s": ["2" * 64],
        "feature_bundle_sha256s": ["4" * 64],
        "source_snapshot_sha256s": ["3" * 64],
        "binding_verified": True,
        "historical_pit_attested": False,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def _bundle(root, receipt=None):
    folder = root / "data/managed/v4_inputs/bundle"
    folder.mkdir(parents=True)
    frames = {
        "factors.parquet": pd.DataFrame([{"x": 1}]),
        "labels.parquet": pd.DataFrame([{"x": 2}]),
        "market_style.parquet": pd.DataFrame([{"x": 3}]),
    }
    digests = {}
    for name, frame in frames.items():
        path = folder / name
        frame.to_parquet(path, index=False)
        digests[name] = sha256(path.read_bytes()).hexdigest()
    manifest = {
        "kind": "V4_STRICT_LABEL_STUDY_INPUT",
        "artifacts_sha256": digests,
        "source_snapshot_sha256": "a" * 64,
        "factor_names": ["alpha"],
        "source_symbols": ["AAA"],
    }
    if receipt is not None:
        manifest["l2_style_context_receipt"] = receipt
    (folder / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_checked_inputs_preserves_valid_l2_binding_receipt(tmp_path):
    receipt = _receipt()
    _bundle(tmp_path, receipt)
    frames, manifest = _checked_inputs(tmp_path, "bundle")
    assert set(frames) == {"factors", "labels", "market_style"}
    assert manifest["l2_style_context_receipt"] == receipt


def test_checked_inputs_rejects_execution_claim_in_l2_receipt(tmp_path):
    receipt = _receipt()
    receipt["decision_eligible"] = True
    _bundle(tmp_path, receipt)
    with pytest.raises(ValueError, match="CANNOT_ENABLE_EXECUTION"):
        _checked_inputs(tmp_path, "bundle")


def test_legacy_bundle_without_receipt_remains_loadable_but_unbound(tmp_path):
    _bundle(tmp_path)
    _, manifest = _checked_inputs(tmp_path, "bundle")
    assert "l2_style_context_receipt" not in manifest


def test_legacy_v1_receipt_without_later_feature_bundle_field_remains_readable(
    tmp_path,
):
    receipt = _receipt()
    receipt.pop("feature_bundle_sha256s")
    _bundle(tmp_path, receipt)
    _, manifest = _checked_inputs(tmp_path, "bundle")
    assert (
        manifest["l2_style_context_receipt"]["contract_version"]
        == "qdr-l2-l3-style-binding-v1"
    )
    assert "feature_bundle_sha256s" not in manifest["l2_style_context_receipt"]
