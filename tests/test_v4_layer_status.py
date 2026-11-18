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
