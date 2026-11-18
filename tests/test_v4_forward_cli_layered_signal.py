"""Forward CLI uses the same final staged L3 cutoff as preflight."""
from hashlib import sha256

import pandas as pd

from quant_research.workflow import v4_forward_cli


def _frames():
    day = pd.Timestamp("2026-11-10")
    return {
        "candidate_meta": pd.DataFrame([{
            "date": day,
            "security_id": "AAA",
            "symbol": "AAA",
            "sector": "Technology",
            "available_at": "2026-11-10T21:17:00Z",
            "source_snapshot_sha256": "a" * 64,
            "reference_close": 100.0,
            "atr20": 2.0,
            "adv20": 1_000_000.0,
        }]),
        "factors": pd.DataFrame([{
            "date": day,
            "security_id": "AAA",
            "feature_name": "alpha",
            "value": 0.2,
            "available_at": "2026-11-10T21:10:00Z",
            "decision_eligible": True,
        }]),
        "labels": pd.DataFrame([
            {
                "date": day,
                "security_id": "AAA",
                "horizon": horizon,
                "label_kind": "FUTURE_UNOBSERVED",
                "available_at": pd.NaT,
                "gross_return": None,
                "excess_return": None,
            }
            for horizon in (1, 3, 5)
        ]),
        "market_style": pd.DataFrame([{
            "date": day,
            "state_available_at": "2026-11-10T21:16:00Z",
            "market_return_5": 0.01,
            "style_l2_quality_h3": 0.003,
        }]),
    }


def _panel():
    day = pd.Timestamp("2026-11-10")
    return pd.DataFrame([
        {
            "date": day,
            "security_id": "AAA",
            "horizon": horizon,
            "signal_time": pd.Timestamp("2026-11-10T21:16:00Z"),
            "feature_available_at": pd.Timestamp("2026-11-10T21:16:00Z"),
            "entry_time": pd.Timestamp("2026-11-11T14:30:00Z"),
            "exit_time": pd.Timestamp("2026-11-11T21:00:00Z")
            + pd.Timedelta(days=horizon - 1),
            "label_available_at": pd.NaT,
            "gross_return": None,
            "excess_return": None,
            "alpha": 0.2,
            "market_return_5": 0.01,
            "style_l2_quality_h3": 0.003,
        }
        for horizon in (1, 3, 5)
    ])


def test_forward_cli_promotes_current_signal_to_latest_required_input(
    tmp_path, monkeypatch
):
    config = tmp_path / "configs/experiments"
    config.mkdir(parents=True)
    config_path = config / "v4_research.yaml"
    config_path.write_text(
        """
oos:
  min_training_sessions: 30
  training_window_sessions: 60
  calibration_sessions: 10
  gap_sessions: 5
  min_calibration_per_class: 2
  ridge_alpha: 1.0
  logistic_c: 1.0
  downside_threshold: -0.02
  seed: 42
""".strip(),
        encoding="utf-8",
    )
    frames = _frames()
    manifest = {
        "factor_names": ["alpha"],
        "source_symbols": ["AAA"],
        "source_snapshot_sha256": "a" * 64,
        "artifacts_sha256": {
            "factors.parquet": "b" * 64,
            "labels.parquet": "c" * 64,
            "market_style.parquet": "d" * 64,
            "candidate_meta.parquet": "e" * 64,
        },
    }
    monkeypatch.setattr(
        v4_forward_cli,
        "_checked_inputs",
        lambda root, bundle_id: (frames, manifest),
    )
    monkeypatch.setattr(
        v4_forward_cli,
        "read_research_forecast",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    monkeypatch.setattr(
        v4_forward_cli,
        "prepare_v4_alpha_panel",
        lambda *args, **kwargs: (
            _panel(),
            {
                "market_style_columns": [
                    "market_return_5", "style_l2_quality_h3"
                ]
            },
        ),
    )
    seen = {}
    def forecast(panel, variants, exchange_sessions, day, **kwargs):
        current = panel.loc[pd.to_datetime(panel.date).eq(pd.Timestamp(day))]
        seen["signal"] = pd.to_datetime(
            current.signal_time, utc=True
        ).unique()
        return {
            "status": "FORWARD_RESEARCH_PREDICTIONS_ONLY",
            "forecasts": pd.DataFrame([{
                "date": "2026-11-10",
                "security_id": "AAA",
                "horizon": 3,
                "decision_eligible": False,
                "research_only": True,
            }]),
            "model_cards": pd.DataFrame([{
                "model_version": "v4-test",
                "research_only": True,
            }]),
            "execution_eligible": False,
            "real_orders_enabled": False,
        }
    monkeypatch.setattr(v4_forward_cli, "forecast_asof", forecast)
    def freeze(root, report, *, protocol_sha256, input_contract):
        seen["protocol_sha256"] = protocol_sha256
        return {
            "manifest": {
                "prospective_before_next_open": True,
                "identity": "f" * 16,
                "forecast_rows": 1,
            }
        }
    monkeypatch.setattr(v4_forward_cli, "freeze_research_forecast", freeze)

    result = v4_forward_cli.run_managed_forward(
        tmp_path, bundle_id="bound-v1", asof_session="2026-11-10"
    )
    assert result["status"] == "FORWARD_RESEARCH_FROZEN_ONLY"
    assert list(seen["signal"]) == [
        pd.Timestamp("2026-11-10T21:17:00Z").to_datetime64()
    ]
    expected = sha256(
        config_path.read_bytes()
        + v4_forward_cli.FORWARD_PROTOCOL_VERSION.encode("utf-8")
    ).hexdigest()
    assert seen["protocol_sha256"] == expected
    assert result["execution_eligible"] is False
    assert result["real_orders_enabled"] is False
