"""Four-layer daily progression stops at the first unsupported evidence boundary."""
from quant_research.workflow import four_layer_day


def _layers(ready=False):
    return {
        "status": (
            "FOUR_LAYER_RESEARCH_CONTEXT_READY" if ready else "RESEARCH_ONLY"
        ),
        "complete_four_layer_context": ready,
        "decision_eligible": False,
        "execution_eligible": False,
        "real_orders_enabled": False,
    }


def test_p4_blocker_prevents_any_l3_bundle_or_pipeline_write(tmp_path, monkeypatch):
    monkeypatch.setattr(
        four_layer_day, "freeze_current_forecast",
        lambda *args, **kwargs: {
            "status": "BLOCKED_NO_ARCHIVE_WRITE",
            "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
        },
    )
    called = []
    monkeypatch.setattr(
        four_layer_day, "create_l2_bound_v4_bundle",
        lambda *args, **kwargs: called.append("bundle"),
    )
    monkeypatch.setattr(
        four_layer_day, "run_v4_pipeline_day",
        lambda *args, **kwargs: called.append("pipeline"),
    )
    monkeypatch.setattr(
        four_layer_day, "four_layer_status",
        lambda *args, **kwargs: _layers(False),
    )
    result = four_layer_day.run_four_layer_research_day(
        tmp_path, "2026-01-30", source_bundle_id="source-v1"
    )
    assert result["status"] == "L2_FORWARD_FREEZE_BLOCKED_NO_L3_WRITE"
    assert result["code"] == "L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert called == []
    assert result["real_orders_enabled"] is False


def test_forward_l2_is_retained_while_model_admission_is_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(
        four_layer_day, "freeze_current_forecast",
        lambda *args, **kwargs: {
            "status": "FROZEN_L2_FORWARD_RESEARCH_ONLY",
            "identity": "a" * 64,
            "session_date_et": "2026-01-30",
        },
    )
    monkeypatch.setattr(
        four_layer_day, "build_downstream_context",
        lambda *args, **kwargs: {
            "status": "RESEARCH_ONLY",
            "code": "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
            "admitted_units": 0,
        },
    )
    called = []
    monkeypatch.setattr(
        four_layer_day, "create_l2_bound_v4_bundle",
        lambda *args, **kwargs: called.append("bundle"),
    )
    monkeypatch.setattr(
        four_layer_day, "run_v4_pipeline_day",
        lambda *args, **kwargs: called.append("pipeline"),
    )
    monkeypatch.setattr(
        four_layer_day, "four_layer_status",
        lambda *args, **kwargs: _layers(False),
    )
    result = four_layer_day.run_four_layer_research_day(
        tmp_path, "2026-01-30", source_bundle_id="source-v1"
    )
    assert result["status"] == "L2_FORWARD_EVIDENCE_CAPTURED_ADMISSION_PENDING"
    assert result["l2_forward"]["identity"] == "a" * 64
    assert result["l2_admitted_units"] == 0
    assert called == []
    assert result["decision_eligible"] is False


def test_admitted_l2_can_progress_through_bound_bundle_l3_and_l4(
    tmp_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        four_layer_day, "freeze_current_forecast",
        lambda *args, **kwargs: {
            "status": "FROZEN_L2_FORWARD_RESEARCH_ONLY",
            "identity": "a" * 64,
            "session_date_et": "2026-01-30",
        },
    )
    monkeypatch.setattr(
        four_layer_day, "build_downstream_context",
        lambda *args, **kwargs: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "admitted_units": 3,
        },
    )
    monkeypatch.setattr(
        four_layer_day, "create_l2_bound_v4_bundle",
        lambda root, source_bundle_id, output_bundle_id: (
            calls.append(("bundle", source_bundle_id, output_bundle_id))
            or {
                "status": "L2_BOUND_V4_BUNDLE_CREATED_RESEARCH_ONLY",
                "output_bundle_id": output_bundle_id,
                "real_orders_enabled": False,
            }
        ),
    )
    monkeypatch.setattr(
        four_layer_day, "run_v4_pipeline_day",
        lambda root, day, bundle_id, research_budget=None: (
            calls.append(("pipeline", bundle_id, research_budget))
            or {
                "status": "RESEARCH_PLAN_AND_DIARY_SAVED",
                "real_orders_enabled": False,
            }
        ),
    )
    monkeypatch.setattr(
        four_layer_day, "four_layer_status",
        lambda *args, **kwargs: _layers(True),
    )
    result = four_layer_day.run_four_layer_research_day(
        tmp_path,
        "2026-01-30",
        source_bundle_id="source-v1",
        bound_bundle_id="source-v1-l2-20260130",
        research_budget=100000.0,
    )
    assert result["status"] == "FOUR_LAYER_RESEARCH_DAY_SAVED"
    assert result["l2_admitted_units"] == 3
    assert calls == [
        ("bundle", "source-v1", "source-v1-l2-20260130"),
        ("pipeline", "source-v1-l2-20260130", 100000.0),
    ]
    assert result["four_layer"]["complete_four_layer_context"] is True
    assert result["execution_eligible"] is False
    assert result["real_orders_enabled"] is False
