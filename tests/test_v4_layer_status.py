"""P6 four-layer evidence status tests."""
from quant_research.workflow import v4_layer_status


def test_four_layer_status_is_fail_closed_and_never_execution_eligible(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status": "FROZEN_FORWARD_RESEARCH_ONLY",
            "asof_session": "2026-01-30",
            "model_version": "l1-v1",
            "model_admitted": False,
            "current_prediction_eligible": False,
            "forecast": {"expected_return": 0.001},
            "source_snapshot_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "RESEARCH_ONLY",
            "code": "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
            "asof_session": "2026-01-30",
            "model_version": "ridge-v1",
            "admitted_units": 0,
            "l3_style_context_available": False,
            "source_snapshot_sha256": "b" * 64,
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_forward_research",
        lambda root, limit=20: [],
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {"records": []},
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert result["status"] == "RESEARCH_ONLY"
    assert result["complete_four_layer_context"] is False
    assert "L1_NOT_MODEL_ADMITTED" in result["blockers"]
    assert "L2_NO_MODEL_ADMITTED_STYLE_CONTEXT" in result["blockers"]
    assert "L3_FORWARD_RESEARCH_MISSING" in result["blockers"]
    assert "L3_L2_STYLE_BINDING_NOT_VERIFIED" in result["blockers"]
    assert "L4_RISK_REVIEW_MISSING" in result["blockers"]
    assert result["decision_eligible"] is False
    assert result["execution_eligible"] is False
    assert result["real_orders_enabled"] is False


def test_alpha_only_daily_rank_is_visible_but_does_not_fake_forward_admission(
    tmp_path, monkeypatch
):
    from quant_research.workflow import l3_daily
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status":"MODEL_OOS_ADMITTED","asof_session":"2026-01-30",
            "model_version":"l1","model_admitted":True,
            "forecast":{"expected_return":0.001},
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status":"RESEARCH_ONLY","asof_session":"2026-01-30",
            "admitted_units":0,"l3_style_context_available":False,
        },
    )
    monkeypatch.setattr(v4_layer_status,"latest_forward_research",
                        lambda root,limit=20:[])
    monkeypatch.setattr(
        l3_daily,"latest_l3_daily",
        lambda root,limit=30:[{
            "session_date_et":"2026-01-30","identity":"alpha-only",
            "status":"FROZEN_L3_DAILY_ALPHA_RESEARCH_ONLY",
            "source_snapshot_sha256":"a"*64,
            "input_kind":"CURRENT_FACTOR_SNAPSHOT",
            "complete_alpha_score_count":37,
        }],
    )
    monkeypatch.setattr(v4_layer_status,"latest_indicative_reviews",
                        lambda root,limit=30:{"records":[]})
    result=v4_layer_status.four_layer_status(
        tmp_path,asof="2026-01-30",horizon=3)
    l3=result["layers"]["l3_alpha"]
    assert l3["status"]=="FROZEN_L3_DAILY_ALPHA_RESEARCH_ONLY"
    assert l3["alpha_rank_frozen"] is True
    assert l3["alpha_score_rows"]==37
    assert l3["forecast_identity"] is None
    assert "L3_FORWARD_RESEARCH_MISSING" in result["blockers"]
    assert result["complete_four_layer_context"] is False


def test_four_layer_status_never_uses_future_l3_or_l4_artifacts(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status": "MODEL_OOS_ADMITTED",
            "asof_session": "2026-01-20",
            "model_version": "l1-v1",
            "model_admitted": True,
            "forecast": {"expected_return": 0.001},
            "source_snapshot_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "asof_session": "2026-01-20",
            "model_version": "ridge-v1",
            "admitted_units": 2,
            "l3_style_context_available": True,
            "source_snapshot_sha256": "b" * 64,
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_forward_research",
        lambda root, limit=20: [
            {
                "session_date_et": "2026-01-25",
                "identity": "future-l3",
                "status": "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY",
                "forecast_rows": 20,
                "source_snapshot_sha256": "f" * 64,
            },
            {
                "session_date_et": "2026-01-18",
                "identity": "past-l3",
                "status": "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY",
                "forecast_rows": 20,
                "source_snapshot_sha256": "c" * 64,
            },
        ],
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {
            "records": [
                {
                    "session_date_et": "2026-01-24",
                    "identity": "future-l4",
                    "status": "RESEARCH_PLANS_ONLY",
                    "research_plan_count": 3,
                    "source_snapshot_sha256": "f" * 64,
                },
                {
                    "session_date_et": "2026-01-19",
                    "identity": "past-l4",
                    "status": "RESEARCH_PLANS_ONLY",
                    "research_plan_count": 2,
                    "source_snapshot_sha256": "d" * 64,
                },
            ]
        },
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-20", horizon=3
    )
    assert result["layers"]["l3_alpha"]["forecast_identity"] == "past-l3"
    assert result["layers"]["l3_alpha"]["asof_session"] == "2026-01-18"
    assert result["layers"]["l4_risk"]["plan_identity"] == "past-l4"
    assert result["layers"]["l4_risk"]["asof_session"] == "2026-01-19"
    assert "L3_L2_STYLE_BINDING_NOT_VERIFIED" in result["blockers"]
    assert result["complete_four_layer_context"] is False


def test_even_admitted_l1_l2_cannot_claim_complete_context_without_l3_binding(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status": "MODEL_OOS_ADMITTED",
            "asof_session": "2026-01-30",
            "model_version": "l1-v1",
            "model_admitted": True,
            "forecast": {"expected_return": 0.001},
            "source_snapshot_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "asof_session": "2026-01-30",
            "model_version": "ridge-v1",
            "admitted_units": 21,
            "l3_style_context_available": True,
            "source_snapshot_sha256": "b" * 64,
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_forward_research",
        lambda root, limit=20: [{
            "session_date_et": "2026-01-30",
            "identity": "l3",
            "status": "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY",
            "forecast_rows": 50,
            "source_snapshot_sha256": "c" * 64,
        }],
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {"records": [{
            "session_date_et": "2026-01-30",
            "identity": "l4",
            "status": "RESEARCH_PLANS_ONLY",
            "research_plan_count": 2,
            "source_snapshot_sha256": "c" * 64,
        }]},
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert result["layers"]["l1_market"]["downstream_context_eligible"] is True
    assert result["layers"]["l2_style"]["l3_style_context_available"] is True
    assert result["layers"]["l3_alpha"]["style_input_binding_verified"] is False
    assert result["blockers"] == ["L3_L2_STYLE_BINDING_NOT_VERIFIED"]
    assert result["complete_four_layer_context"] is False


def test_verified_l2_l3_identity_binding_is_separate_from_historical_pit(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status": "MODEL_OOS_ADMITTED",
            "asof_session": "2026-01-30",
            "model_version": "l1-v1",
            "model_admitted": True,
            "forecast": {"expected_return": 0.001},
            "source_snapshot_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "asof_session": "2026-01-30",
            "model_version": "ridge-v1",
            "admitted_units": 2,
            "l3_style_context_available": True,
            "source_snapshot_sha256": "b" * 64,
            "label_bundle_id": "accepted-v1",
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_forward_research",
        lambda root, limit=20: [{
            "session_date_et": "2026-01-30",
            "identity": "l3",
            "status": "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY",
            "forecast_rows": 50,
            "source_snapshot_sha256": "c" * 64,
            "l2_style_binding_verified": True,
            "l2_style_historical_pit_attested": False,
            "l2_style_binding_context_sha256": "9" * 64,
        }],
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {"records": [{
            "session_date_et": "2026-01-30",
            "identity": "l4",
            "status": "RESEARCH_PLANS_ONLY",
            "research_plan_count": 2,
            "source_snapshot_sha256": "c" * 64,
        }]},
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    l3 = result["layers"]["l3_alpha"]
    assert l3["style_input_binding_verified"] is True
    assert l3["style_historical_pit_attested"] is False
    assert l3["style_binding_context_sha256"] == "9" * 64
    assert l3["downstream_context_eligible"] is False
    assert result["blockers"] == ["L3_L2_STYLE_HISTORY_NOT_PIT_ATTESTED"]
    assert result["complete_four_layer_context"] is False


def _wire_ready_four_layers(monkeypatch, *, l3_overrides=None):
    monkeypatch.setattr(
        v4_layer_status,
        "market_overview_for_api",
        lambda root, horizon, asof=None: {
            "status": "MODEL_OOS_ADMITTED",
            "asof_session": "2026-01-30",
            "model_version": "l1-v1",
            "model_admitted": True,
            "current_prediction_eligible": True,
            "forecast": {"expected_return": 0.001},
            "source_snapshot_sha256": "1" * 64,
        },
    )
    monkeypatch.setattr(
        v4_layer_status,
        "build_downstream_context",
        lambda root, asof=None: {
            "status": "MODEL_ADMITTED_CONTEXT",
            "asof_session": "2026-01-30",
            "model_version": "ridge-v1",
            "admitted_units": 3,
            "l3_style_context_available": True,
            "source_snapshot_sha256": "4" * 64,
            "label_bundle_id": "labels-v1",
            "label_bundle_sha256": "2" * 64,
            "feature_bundle_id": "features-v1",
            "feature_bundle_sha256": "5" * 64,
            "historical_feature_pit_attested": True,
            "forecast_identity": "6" * 64,
            "validation_identity": "7" * 64,
        },
    )
    l3 = {
        "session_date_et": "2026-01-30",
        "identity": "l3-current",
        "status": "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY",
        "forecast_rows": 50,
        "source_snapshot_sha256": "8" * 64,
        "l2_style_binding_verified": True,
        "l2_style_historical_pit_attested": True,
        "l2_style_binding_context_sha256": "9" * 64,
        "l2_style_admission_validation_identity": "7" * 64,
        "l2_style_admission_asof_session": "2026-01-30",
        "l2_style_context_modes": [
            "CURRENT_FROZEN_FORWARD", "HISTORICAL_PIT_REPLAY"
        ],
        "l2_style_current_forward_session": "2026-01-30",
        "l2_style_binding_start_session": "2025-01-02",
        "l2_style_binding_end_session": "2026-01-30",
        "l2_style_model_versions": ["ridge-v1"],
        "l2_style_label_bundle_sha256s": ["2" * 64],
        "l2_style_feature_bundle_sha256s": ["5" * 64],
        "l2_style_source_snapshot_sha256s": ["4" * 64],
    }
    if l3_overrides:
        l3.update(l3_overrides)
    monkeypatch.setattr(
        v4_layer_status,
        "latest_forward_research",
        lambda root, limit=20: [l3],
    )
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {"records": [{
            "session_date_et": "2026-01-30",
            "identity": "l4-current",
            "status": "RESEARCH_PLANS_ONLY",
            "research_plan_count": 2,
            "source_snapshot_sha256": "8" * 64,
            "source_forecast_identity": "l3-current",
        }]},
    )


def test_four_layer_context_can_be_ready_only_with_matching_l2_l3_provenance(
    tmp_path, monkeypatch
):
    _wire_ready_four_layers(monkeypatch)
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert result["status"] == "FOUR_LAYER_RESEARCH_CONTEXT_READY"
    assert result["blockers"] == []
    assert result["complete_four_layer_context"] is True
    assert result["layers"]["l3_alpha"]["downstream_context_eligible"] is True
    assert result["decision_eligible"] is False
    assert result["execution_eligible"] is False
    assert result["real_orders_enabled"] is False


def test_stale_l3_receipt_cannot_bind_to_new_l2_model_or_bundles(
    tmp_path, monkeypatch
):
    _wire_ready_four_layers(
        monkeypatch,
        l3_overrides={
            "l2_style_model_versions": ["old-ridge"],
            "l2_style_label_bundle_sha256s": ["a" * 64],
            "l2_style_feature_bundle_sha256s": ["b" * 64],
            "l2_style_source_snapshot_sha256s": ["c" * 64],
        },
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert result["complete_four_layer_context"] is False
    assert "L3_L2_MODEL_VERSION_BINDING_MISMATCH" in result["blockers"]
    assert "L3_L2_LABEL_BUNDLE_BINDING_MISMATCH" in result["blockers"]
    assert "L3_L2_FEATURE_BUNDLE_BINDING_MISMATCH" in result["blockers"]
    assert "L3_L2_SOURCE_BINDING_MISMATCH" in result["blockers"]
    assert result["layers"]["l3_alpha"]["downstream_context_eligible"] is False


def test_l3_receipt_must_cover_current_signal_session(tmp_path, monkeypatch):
    _wire_ready_four_layers(
        monkeypatch,
        l3_overrides={"l2_style_binding_end_session": "2026-01-29"},
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert "L3_L2_BINDING_SESSION_MISMATCH" in result["blockers"]
    assert result["complete_four_layer_context"] is False


def test_l4_review_must_point_to_exact_current_l3_forecast_identity(
    tmp_path, monkeypatch
):
    _wire_ready_four_layers(monkeypatch)
    monkeypatch.setattr(
        v4_layer_status,
        "latest_indicative_reviews",
        lambda root, limit=30: {"records": [{
            "session_date_et": "2026-01-30",
            "identity": "l4-wrong",
            "status": "RESEARCH_PLANS_ONLY",
            "research_plan_count": 2,
            "source_snapshot_sha256": "8" * 64,
            "source_forecast_identity": "different-l3-archive",
        }]},
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert "L4_L3_FORECAST_IDENTITY_MISMATCH" in result["blockers"]
    assert result["complete_four_layer_context"] is False


def test_l3_receipt_must_bind_exact_current_l2_admission_identity(
    tmp_path, monkeypatch
):
    _wire_ready_four_layers(
        monkeypatch,
        l3_overrides={
            "l2_style_admission_validation_identity": "0" * 64,
        },
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert (
        "L3_L2_VALIDATION_IDENTITY_BINDING_MISMATCH"
        in result["blockers"]
    )
    assert result["complete_four_layer_context"] is False


def test_l3_receipt_requires_current_forward_row_for_target_session(
    tmp_path, monkeypatch
):
    _wire_ready_four_layers(
        monkeypatch,
        l3_overrides={
            "l2_style_current_forward_session": None,
            "l2_style_context_modes": ["HISTORICAL_PIT_REPLAY"],
        },
    )
    result = v4_layer_status.four_layer_status(
        tmp_path, asof="2026-01-30", horizon=3
    )
    assert "L3_L2_CURRENT_FORWARD_BINDING_MISMATCH" in result["blockers"]
    assert result["complete_four_layer_context"] is False
