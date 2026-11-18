"""Immutable P5 validation report archive tests."""
import json

import pytest

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.research.l2_validation_archive import (
    freeze_validation_report_v1,
    load_latest_validation_v1,
    load_validation_on_or_before_v1,
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
        "feature_bundle_sha256": "c" * 64,
        "feature_bundle_id": "features-v1",
        "historical_feature_pit_attested": True,
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


def test_validation_archive_rejects_forged_admission_when_switch_disabled(tmp_path):
    report = _report()
    report["qualification"][0].update({
        "qualification_status": "MODEL_ADMITTED",
        "model_admitted": True,
        "oos_gate_passed": True,
        "forward_gate_passed": True,
    })
    report["summary"]["model_admitted_units"] = 1
    report["summary"]["model_admission_enabled"] = False
    with pytest.raises(ValueError, match="switch is disabled"):
        freeze_validation_report_v1(tmp_path, report)


def test_on_or_before_loader_never_reads_future_validation(tmp_path):
    first = freeze_validation_report_v1(tmp_path, _report("2026-01-10"))
    second = freeze_validation_report_v1(tmp_path, _report("2026-01-20"))
    third = freeze_validation_report_v1(tmp_path, _report("2026-02-02"))
    picked = load_validation_on_or_before_v1(tmp_path, "2026-01-25")
    assert picked["identity"] == second["identity"]
    assert picked["asof_session"] == "2026-01-20"
    assert picked["identity"] != third["identity"]
    picked_early = load_validation_on_or_before_v1(tmp_path, "2026-01-10")
    assert picked_early["identity"] == first["identity"]


def test_new_validation_report_requires_feature_bundle_evidence(tmp_path):
    report=_report()
    report.pop("feature_bundle_sha256")
    with pytest.raises(ValueError,match="feature_bundle_sha256"):
        freeze_validation_report_v1(tmp_path,report)


def test_legacy_report_without_feature_evidence_is_readable_but_not_attested(tmp_path):
    # Construct a legacy artifact directly to verify backward-compatible read.
    from quant_research.research import l2_validation_archive as archive
    report=_report()
    report.pop("feature_bundle_sha256")
    report.pop("feature_bundle_id")
    report.pop("historical_feature_pit_attested")
    payload={**report,"schema":archive.SCHEMA}
    identity=archive._identity(payload)
    folder=tmp_path/"outputs/l2_validation/2026-01-30"/identity
    folder.mkdir(parents=True)
    (folder/"manifest.json").write_text(json.dumps({
        **payload,"identity":identity,
        "frozen_at_utc":"2026-01-31T00:00:00+00:00",
    }),encoding="utf-8")
    loaded=load_latest_validation_v1(tmp_path,asof="2026-01-30")
    assert loaded["historical_feature_pit_attested"] is False
    assert loaded["legacy_feature_evidence_missing"] is True
