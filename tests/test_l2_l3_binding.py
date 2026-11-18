"""P6 L2->L3 style binding tests use admitted-context fixtures only."""
import pandas as pd
import pytest

from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.workflow.l2_l3_binding import (
    build_l2_style_history_binding,
    style_column,
    validate_l2_style_binding_receipt,
    verify_l2_style_history_binding,
)


DATES = pd.DatetimeIndex(["2026-01-29", "2026-01-30"])


class Clock:
    def signal(self, day):
        return pd.Timestamp(str(day)[:10] + "T21:15:00Z")


def _context(day):
    date = str(pd.Timestamp(day).date())
    admitted = [
        {
            "style_id": "size",
            "horizon": 3,
            "admitted_relative_return": 0.003 if date.endswith("29") else 0.004,
            "downstream_context_eligible": True,
        },
        {
            "style_id": "quality",
            "horizon": 3,
            "admitted_relative_return": 0.002 if date.endswith("29") else 0.0025,
            "downstream_context_eligible": True,
        },
    ]
    return {
        "status": "MODEL_ADMITTED_CONTEXT",
        "asof_session": date,
        "forecast_identity": ("a" if date.endswith("29") else "b") * 64,
        "validation_identity": "c" * 64,
        "model_version": "ridge-v1",
        "label_bundle_sha256": "d" * 64,
        "feature_bundle_sha256": "9" * 64,
        "source_snapshot_sha256": ("e" if date.endswith("29") else "f") * 64,
        "historical_feature_pit_attested": True,
        "historical_decision_eligible": False,
        "contexts": admitted,
    }


def _market_style():
    return pd.DataFrame([
        {
            "date": DATES[0],
            "state_available_at": "2026-01-29T21:10:00Z",
            style_column("size", 3): 0.003,
            style_column("quality", 3): 0.002,
            "market_return_5": 0.01,
        },
        {
            "date": DATES[1],
            "state_available_at": "2026-01-30T21:10:00Z",
            style_column("size", 3): 0.004,
            style_column("quality", 3): 0.0025,
            "market_return_5": 0.02,
        },
    ])


def test_binding_receipt_binds_exact_admitted_style_values():
    receipt = build_l2_style_history_binding(
        ".",
        _market_style(),
        downstream_builder=lambda root, asof=None: _context(asof),
        clock=Clock(),
    )
    assert receipt["binding_verified"] is True
    assert receipt["historical_pit_attested"] is True
    assert receipt["rows"] == 2
    assert receipt["start_session"] == "2026-01-29"
    assert receipt["end_session"] == "2026-01-30"
    assert receipt["style_columns"] == sorted([
        style_column("quality", 3),
        style_column("size", 3),
    ])
    assert len(receipt["context_identity_sha256"]) == 64
    assert receipt["decision_eligible"] is False
    assert receipt["real_orders_enabled"] is False


def test_extra_unbound_numeric_style_column_is_rejected():
    frame = _market_style()
    frame["style_exploratory_unbound"] = [0.1, 0.2]
    with pytest.raises(ValueError, match="STYLE_COLUMNS_NOT_EXACTLY_ADMITTED"):
        build_l2_style_history_binding(
            ".", frame,
            downstream_builder=lambda root, asof=None: _context(asof),
            clock=Clock(),
        )


def test_changed_style_value_is_rejected():
    frame = _market_style()
    frame.loc[1, style_column("size", 3)] = 0.99
    with pytest.raises(ValueError, match="STYLE_VALUE_MISMATCH"):
        build_l2_style_history_binding(
            ".", frame,
            downstream_builder=lambda root, asof=None: _context(asof),
            clock=Clock(),
        )


def test_nonadmitted_history_row_blocks_entire_binding():
    def builder(root, asof=None):
        if asof == "2026-01-29":
            return {
                "status": "RESEARCH_ONLY",
                "code": "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
            }
        return _context(asof)
    with pytest.raises(ValueError, match="CONTEXT_NOT_MODEL_ADMITTED"):
        build_l2_style_history_binding(
            ".", _market_style(), downstream_builder=builder, clock=Clock()
        )


def test_receipt_reverification_detects_context_change():
    receipt = build_l2_style_history_binding(
        ".", _market_style(),
        downstream_builder=lambda root, asof=None: _context(asof),
        clock=Clock(),
    )

    def changed(root, asof=None):
        context = _context(asof)
        context["contexts"] = [dict(row) for row in context["contexts"]]
        context["contexts"][0]["admitted_relative_return"] += 0.0001
        return context

    with pytest.raises(ValueError, match="STYLE_VALUE_MISMATCH|RECEIPT_MISMATCH"):
        verify_l2_style_history_binding(
            ".", _market_style(), receipt,
            downstream_builder=changed, clock=Clock(),
        )


def test_structural_receipt_cannot_claim_execution():
    receipt = build_l2_style_history_binding(
        ".", _market_style(),
        downstream_builder=lambda root, asof=None: _context(asof),
        clock=Clock(),
    )
    receipt["real_orders_enabled"] = True
    with pytest.raises(ValueError, match="CANNOT_ENABLE_EXECUTION"):
        validate_l2_style_binding_receipt(receipt)
