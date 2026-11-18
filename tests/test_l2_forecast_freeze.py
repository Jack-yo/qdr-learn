"""Explicit P4 freeze workflow never writes blocked research."""
from quant_research.workflow import l2_forecast_freeze


def test_blocked_forecast_never_calls_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(
        l2_forecast_freeze, "calculate_forecast",
        lambda root, asof=None: {
            "status":"BLOCKED","code":"L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
            "asof_session":asof,"eligible_units":0,"blocked_units":21,
        },
    )
    called=[]
    monkeypatch.setattr(
        l2_forecast_freeze, "freeze_forecast_snapshot_v1",
        lambda *args, **kwargs: called.append(True),
    )
    result=l2_forecast_freeze.freeze_current_forecast(tmp_path,asof="2025-04-09")
    assert result["status"]=="BLOCKED_NO_ARCHIVE_WRITE"
    assert result["code"]=="L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert called==[]


def test_research_ready_forecast_is_explicitly_frozen(monkeypatch, tmp_path):
    forecast={"status":"RESEARCH_ONLY","asof_session":"2025-04-09"}
    monkeypatch.setattr(
        l2_forecast_freeze, "calculate_forecast",
        lambda root, asof=None: forecast,
    )
    monkeypatch.setattr(
        l2_forecast_freeze, "freeze_forecast_snapshot_v1",
        lambda root, payload, **kwargs: {
            "status":"FROZEN_L2_RESEARCH_ONLY",
            "session_date_et":"2025-04-09","identity":"a"*64,
            "model_version":"ridge-v1","eligible_units":7,"blocked_units":14,
            "source_snapshot_sha256":"b"*64,"label_bundle_sha256":"c"*64,
        },
    )
    result=l2_forecast_freeze.freeze_current_forecast(tmp_path,asof="2025-04-09")
    assert result["status"]=="FROZEN_L2_RESEARCH_ONLY"
    assert result["identity"]=="a"*64
    assert result["real_orders_enabled"] is False


def test_prospective_only_blocks_before_signal_without_archive_write(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        l2_forecast_freeze, "calculate_forecast",
        lambda root, asof=None: {
            "status": "RESEARCH_ONLY",
            "asof_session": "2025-04-09",
            "eligible_units": 21,
            "blocked_units": 0,
        },
    )
    called = []
    monkeypatch.setattr(
        l2_forecast_freeze, "freeze_forecast_snapshot_v1",
        lambda *args, **kwargs: called.append(True),
    )
    result = l2_forecast_freeze.freeze_current_forecast(
        tmp_path,
        asof="2025-04-09",
        prospective_only=True,
        now_utc="2025-04-09T19:00:00Z",
    )
    assert result["status"] == "BLOCKED_NO_ARCHIVE_WRITE"
    assert result["code"] == "L2_NOT_IN_PROSPECTIVE_FREEZE_WINDOW"
    assert called == []
