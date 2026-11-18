"""Small immutable L2 label-bundle contract tests."""
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.research.l2_forecast import HORIZONS, STYLE_IDS
from quant_research.research.l2_label_bundle import (
    freeze_label_bundle_v1, load_label_bundle_v1,
)
from quant_research.research.l2_labels import REQUIRED_PRICE_BASIS


def _labels():
    clock = TradingClock()
    sessions = clock.calendar.sessions_in_range("2025-01-02", "2025-12-31")[:8]
    rows = []
    for day in sessions[:3]:
        for style_i, style in enumerate(STYLE_IDS):
            for horizon in HORIZONS:
                window = clock.window(day, horizon)
                rows.append({
                    "date": day,
                    "style_id": style,
                    "horizon": horizon,
                    "forward_relative_return": 0.001 * (style_i + 1) + horizon * 0.0001,
                    "label_available_at": pd.Timestamp(window.exit_time) + pd.Timedelta(minutes=20),
                    "label_kind": "VERIFIED_RAW_RELATIVE_RETURN",
                    "signal_time": pd.Timestamp(window.signal_time),
                    "entry_time": pd.Timestamp(window.entry_time),
                    "exit_time": pd.Timestamp(window.exit_time),
                })
    return clock, pd.DataFrame(rows)


def test_freeze_and_load_label_bundle_round_trip(tmp_path):
    clock, labels = _labels()
    manifest = freeze_label_bundle_v1(
        tmp_path, "accepted-v1", labels, clock,
        source_evidence_sha256="a" * 64,
        action_evidence_version="actions-v1",
    )
    assert manifest["rows"] == len(labels)
    assert manifest["verified_rows"] == len(labels)
    assert manifest["price_basis"] == REQUIRED_PRICE_BASIS
    assert manifest["historical_pit_attested"] is False
    loaded, stored = load_label_bundle_v1(tmp_path, "accepted-v1", clock)
    assert len(loaded) == len(labels)
    assert stored["labels_sha256"] == manifest["labels_sha256"]
    assert set(loaded.style_id) == set(STYLE_IDS)
    assert set(loaded.horizon) == set(HORIZONS)


def test_label_bundle_is_write_once_and_hash_checked(tmp_path):
    clock, labels = _labels()
    freeze_label_bundle_v1(
        tmp_path, "accepted-v1", labels, clock,
        source_evidence_sha256="b" * 64,
        action_evidence_version="actions-v1",
    )
    with pytest.raises(FileExistsError, match="immutable"):
        freeze_label_bundle_v1(
            tmp_path, "accepted-v1", labels, clock,
            source_evidence_sha256="b" * 64,
            action_evidence_version="actions-v1",
        )
    path = tmp_path / "data/managed/l2_style_labels/accepted-v1/labels.parquet"
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        load_label_bundle_v1(tmp_path, "accepted-v1", clock)


def test_manifest_scope_cannot_be_relabelled_after_freeze(tmp_path):
    clock, labels = _labels()
    freeze_label_bundle_v1(
        tmp_path, "accepted-v1", labels, clock,
        source_evidence_sha256="c" * 64,
        action_evidence_version="actions-v1",
    )
    path = tmp_path / "data/managed/l2_style_labels/accepted-v1/manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["horizons"] = [1, 3]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        load_label_bundle_v1(tmp_path, "accepted-v1", clock)


def test_bundle_rejects_partial_style_scope(tmp_path):
    clock, labels = _labels()
    partial = labels.loc[~labels.style_id.eq("cyc_def")]
    with pytest.raises(ValueError, match="all seven"):
        freeze_label_bundle_v1(
            tmp_path, "partial-v1", partial, clock,
            source_evidence_sha256="d" * 64,
            action_evidence_version="actions-v1",
        )
