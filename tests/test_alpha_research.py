"""P4 alpha workflow checks against the immutable real cache only."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.data.bundle import frame_hash, load_real_bundle
from quant_research.workflow.train import execute


ROOT = Path(__file__).resolve().parents[1]


def test_real_alpha_cache_has_stable_hash_and_ordered_observation_times():
    db = ROOT / "data/research.duckdb"
    if not db.is_file():
        pytest.skip("BLOCKED_REAL_YAHOO_STORE_MISSING")
    bundle = load_real_bundle(db, "yahoo", asof="2024-12-31")
    prices = bundle.prices
    assert frame_hash(prices) == bundle.metadata["snapshot_sha256"]
    for column in ("event_time", "available_at", "ingested_at"):
        values = pd.to_datetime(prices[column], utc=True)
        assert values.notna().all()
    assert (pd.to_datetime(prices.available_at, utc=True) >=
            pd.to_datetime(prices.event_time, utc=True)).all()
    assert (pd.to_datetime(prices.ingested_at, utc=True) >=
            pd.to_datetime(prices.available_at, utc=True)).all()
    assert bundle.metadata["asof_date_et"] == "2024-12-31"


def test_alpha_sealed_asof_rejected_before_output(tmp_path):
    args = SimpleNamespace(
        command="train", source="yahoo", mode="retrospective",
        db=ROOT / "data/research.duckdb",
        experiment=ROOT / "configs/experiments/baseline.yaml",
        output=tmp_path, asof="2025-01-02",
    )
    with pytest.raises(ValueError, match="sealed"):
        execute(args)
    assert not list(tmp_path.iterdir())


def test_real_alpha_variants_share_sample_and_respect_cutoff(tmp_path):
    db = ROOT / "data/research.duckdb"
    if not db.is_file():
        pytest.skip("BLOCKED_REAL_YAHOO_STORE_MISSING")
    args = SimpleNamespace(command="train", source="yahoo", mode="retrospective", db=db,
                           experiment=ROOT / "configs/experiments/baseline.yaml",
                           output=tmp_path, asof="2023-03-31")
    folder, manifest, predictions, *_ = execute(args, return_data=True)
    assert manifest["input_last_date"] == "2023-03-31"
    assert not manifest["historical_decision_eligible"] and not manifest["sealed_test_used"]
    assert set(predictions.variant) == set("ABCD") and set(predictions.horizon) == {1, 3, 5}
    keys = ["date", "security_id", "horizon"]
    groups = predictions.groupby(keys)
    assert groups.variant.nunique().eq(4).all()
    assert groups.actual_return.nunique().eq(1).all()
    assert predictions.actual_excess_return.notna().all()
    assert not predictions.decision_eligible.any()
    assert predictions.exit_time.dt.date.max().isoformat() == "2023-03-31"
    folds = pd.read_parquet(folder / "alpha_training_folds.parquet")
    assert (folds.train_last_exit < folds.fit_time).all()
    for name, digest in manifest["artifacts_sha256"].items():
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
