"""Immutable P5 validation report archive tests."""
import json

import pytest

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.research.l2_validation_archive import (
    freeze_validation_report_v1,
    load_latest_validation_v1,
)


def _report(asof="2026-01-30"):
    qualification = [
        {
            "style_id": style,
            "horizon": horizon,
            "qualification_status": "OOS_VALIDATED",
            "oos_gate_passed": True,
            "forward_gate_passed": False,
            "model_admitted": False,
            "reasons": ["MODEL_ADMISSION_SWITCH_DISABLED"],
            "decision_eligible": False,
            "real_orders_enabled": False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ]
    return {
        "status": "P5_RESEARCH_VALIDATION",
        "asof_session": asof,
        "source_snapshot_sha256": "a" * 64,
        "label_bundle_sha256": "b" * 64,
        "label_bundle_id": "accepted-v1",
        "model_version": "ridge-v1",
        "summary": {
            "oos_validated_units": 21,
            "genuine_forward_units": 0,
            "model_admitted_units": 0,
            "total_units": 21,
            "model_admission_enabled": False,
        },
        "qualification": qualification,
        "oos_validation": [],
        "ablation_scores": [],
        "forward_validation": [],
        "historical_decision_eligible": False,
        "decision_eligible": False,
        "real_orders_enabled": False,
    }


def test_validation_report_round_trip_is_identity_checked(tmp_path):
    first = freeze_validation_report_v1(tmp_path, _report())
    second = freeze_validation_report_v1(tmp_path, _report())
    assert first["identity"] == second["identity"]
    loaded = load_latest_validation_v1(tmp_path)
    assert loaded["identity"] == first["identity"]
    assert loaded["summary"]["total_units"] == 21
    assert loaded["real_orders_enabled"] is False


def test_validation_archive_preserves_multiple_evidence_identities(tmp_path):
    first = freeze_validation_report_v1(tmp_path, _report())
    changed = _report()
    changed["summary"]["oos_validated_units"] = 20
    second = freeze_validation_report_v1(tmp_path, changed)
    assert second["identity"] != first["identity"]
    latest = load_latest_validation_v1(tmp_path, asof="2026-01-30")
    assert latest["identity"] in {first["identity"], second["identity"]}


def test_validation_report_detects_tampering(tmp_path):
    frozen = freeze_validation_report_v1(tmp_path, _report())
    path = (
        tmp_path / "outputs/l2_validation/2026-01-30"
        / frozen["identity"] / "manifest.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["summary"]["oos_validated_units"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        load_latest_validation_v1(tmp_path, asof="2026-01-30")


def test_validation_archive_rejects_non_21_unit_report(tmp_path):
    report = _report()
    report["qualification"] = report["qualification"][:-1]
    with pytest.raises(ValueError, match="7x3"):
        freeze_validation_report_v1(tmp_path, report)
