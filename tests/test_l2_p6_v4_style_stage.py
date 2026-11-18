"""P6 integration: V4 daily style stage is gated only by L2 qualification."""
from quant_research.workflow import l2_downstream, styles
from quant_research.workflow.v4_ops import observed_v4_adapters


def _readiness():
    return {
        "stages": {
            "dataset": {
                "status": "OBSERVATION_ONLY",
                "evidence": {},
            }
        }
    }


def test_v4_style_stage_stays_research_only_without_model_admission(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        l2_downstream,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "RESEARCH_ONLY",
            "code": "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
            "asof_session": asof,
            "admitted_units": 0,
            "l3_style_context_available": False,
            "model_version": "ridge-v1",
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        styles,
        "calculate",
        lambda root, asof=None: (
            None,
            [1, 2, 3],
            None,
            {"asof_date_et": asof},
        ),
    )
    stage = observed_v4_adapters(tmp_path, _readiness())["styles"]
    result = stage("2026-01-30", ())
    assert result["status"] == "RESEARCH_ONLY"
    assert result["code"] == "NO_MODEL_ADMITTED_L2_STYLE_UNITS"
    assert result["detail"]["admitted_units"] == 0
    assert result["detail"]["l3_style_context_available"] is False
    assert result["detail"]["classic_french_observation"]["status"] == "OBSERVATION_ONLY"


def test_v4_style_stage_passes_only_model_admitted_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        l2_downstream,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "code": None,
            "asof_session": asof,
            "admitted_units": 2,
            "l3_style_context_available": True,
            "model_version": "ridge-v1",
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        styles,
        "calculate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("French source unavailable")
        ),
    )
    stage = observed_v4_adapters(tmp_path, _readiness())["styles"]
    result = stage("2026-01-30", ())
    assert result["status"] == "PASS"
    assert result["code"] == "L2_MODEL_ADMITTED_CONTEXT"
    assert result["detail"]["admitted_units"] == 2
    assert result["detail"]["l3_style_context_available"] is True
    assert result["detail"]["classic_french_observation"]["status"] == "UNAVAILABLE"


def test_v4_style_stage_blocks_integrity_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        l2_downstream,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "BLOCKED",
            "code": "L2_MODEL_VERSION_MISMATCH",
            "asof_session": asof,
            "admitted_units": 0,
            "l3_style_context_available": False,
        },
    )
    monkeypatch.setattr(
        styles,
        "calculate",
        lambda *args, **kwargs: (None, [], None, {"asof_date_et": "2026-01-30"}),
    )
    stage = observed_v4_adapters(tmp_path, _readiness())["styles"]
    result = stage("2026-01-30", ())
    assert result["status"] == "BLOCKED"
    assert result["code"] == "L2_MODEL_VERSION_MISMATCH"
