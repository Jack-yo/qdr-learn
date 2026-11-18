"""Immutable V4 bundle derivation from admitted L2 style context."""
from hashlib import sha256
import json

import pandas as pd
import pytest

from quant_research.workflow import v4_l2_bind_bundle


def _sha(path):
    return sha256(path.read_bytes()).hexdigest()


def _source_bundle(root):
    folder = root / "data/managed/v4_inputs/source-v1"
    folder.mkdir(parents=True)
    frames = {
        "factors.parquet": pd.DataFrame([{
            "date": pd.Timestamp("2026-01-30"),
            "security_id": "AAA", "feature_name": "alpha", "value": 0.2,
        }]),
        "labels.parquet": pd.DataFrame([{
            "date": pd.Timestamp("2026-01-30"),
            "security_id": "AAA", "horizon": 1,
        }]),
        "market_style.parquet": pd.DataFrame([{
            "date": pd.Timestamp("2026-01-30"),
            "state_available_at": "2026-01-30T21:10:00Z",
            "market_return_5": 0.01,
        }]),
        "candidate_meta.parquet": pd.DataFrame([{
            "date": pd.Timestamp("2026-01-30"),
            "security_id": "AAA", "symbol": "AAA",
        }]),
    }
    digests = {}
    for name, frame in frames.items():
        path = folder / name
        frame.to_parquet(path, index=False)
        digests[name] = _sha(path)
    manifest = {
        "kind": "V4_STRICT_LABEL_STUDY_INPUT",
        "source_snapshot_sha256": "a" * 64,
        "source_symbols": ["AAA"],
        "factor_names": ["alpha"],
        "artifacts_sha256": digests,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return folder, manifest


def _receipt():
    return {
        "contract_version": "qdr-l2-l3-style-binding-v1",
        "scope": "HISTORICAL_AND_CURRENT",
        "start_session": "2026-01-30",
        "end_session": "2026-01-30",
        "rows": 1,
        "style_columns": ["style_l2_quality_h3"],
        "context_identity_sha256": "1" * 64,
        "model_versions": ["ridge-v1"],
        "label_bundle_sha256s": ["2" * 64],
        "feature_bundle_sha256s": ["3" * 64],
        "source_snapshot_sha256s": ["4" * 64],
        "binding_verified": True,
        "historical_pit_attested": True,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def test_bound_bundle_is_new_immutable_identity_and_preserves_source_bytes(
    tmp_path, monkeypatch
):
    source, manifest = _source_bundle(tmp_path)
    original_manifest = (source / "manifest.json").read_bytes()
    original_hashes = {
        name: _sha(source / name) for name in manifest["artifacts_sha256"]
    }

    def materialize(root, frame):
        result = frame.copy()
        result["state_available_at"] = "2026-01-30T21:16:00Z"
        result["style_l2_quality_h3"] = 0.003
        return result

    monkeypatch.setattr(
        v4_l2_bind_bundle, "materialize_l2_style_history", materialize
    )
    monkeypatch.setattr(
        v4_l2_bind_bundle, "build_l2_style_history_binding",
        lambda root, frame: _receipt(),
    )

    result = v4_l2_bind_bundle.create_l2_bound_v4_bundle(
        tmp_path,
        source_bundle_id="source-v1",
        output_bundle_id="source-v1-l2",
    )
    assert result["status"] == "L2_BOUND_V4_BUNDLE_CREATED_RESEARCH_ONLY"
    assert result["decision_eligible"] is False
    assert result["real_orders_enabled"] is False

    target = tmp_path / "data/managed/v4_inputs/source-v1-l2"
    output = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert output["derived_from_bundle_id"] == "source-v1"
    assert output["l2_style_context_receipt"]["binding_verified"] is True
    assert output["l2_style_context_receipt"]["historical_pit_attested"] is True
    assert output["artifacts_sha256"]["market_style.parquet"] != original_hashes[
        "market_style.parquet"
    ]
    for name in ("factors.parquet", "labels.parquet", "candidate_meta.parquet"):
        assert _sha(target / name) == original_hashes[name]
        assert output["artifacts_sha256"][name] == original_hashes[name]

    bound = pd.read_parquet(target / "market_style.parquet")
    assert bound.loc[0, "style_l2_quality_h3"] == pytest.approx(0.003)
    assert pd.Timestamp(bound.loc[0, "state_available_at"]) == pd.Timestamp(
        "2026-01-30T21:16:00Z"
    )
    assert (source / "manifest.json").read_bytes() == original_manifest
    assert {
        name: _sha(source / name) for name in manifest["artifacts_sha256"]
    } == original_hashes


def test_bound_bundle_never_overwrites_existing_output(tmp_path, monkeypatch):
    _source_bundle(tmp_path)
    destination = tmp_path / "data/managed/v4_inputs/existing"
    destination.mkdir(parents=True)
    with pytest.raises(FileExistsError, match="ALREADY_EXISTS"):
        v4_l2_bind_bundle.create_l2_bound_v4_bundle(
            tmp_path,
            source_bundle_id="source-v1",
            output_bundle_id="existing",
        )
