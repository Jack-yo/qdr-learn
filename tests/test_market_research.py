import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.policy import PolicyError
from quant_research.web import market_research
from quant_research.workflow.market import execute


ROOT = Path(__file__).resolve().parents[1]


def run_study(output, asof=None, mode="retrospective"):
    args = SimpleNamespace(
        command="train-market", source="yahoo", db=ROOT / "data/research.duckdb",
        experiment=ROOT / "configs/experiments/baseline.yaml", output=output,
        asof=asof, mode=mode,
    )
    assert execute(args) == 0
    return next(output.glob("*/manifest.json")).parent


def test_real_market_study_cutoff_fold_isolation_and_artifacts(tmp_path):
    if not (ROOT / "data/research.duckdb").is_file():
        pytest.skip("BLOCKED_REAL_YAHOO_STORE_MISSING")
    output = tmp_path / "outputs/market_research"
    full = run_study(output)
    partial = run_study(tmp_path / "partial", "2023-06-30")
    manifest = json.loads((full / "manifest.json").read_text(encoding="utf-8"))
    partial_manifest = json.loads((partial / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_provenance"]["verified_rows"] == 40240
    assert manifest["source"] == "yahoo"
    assert not manifest["research_grade"] and not manifest["execution_ready"]
    assert not manifest["sealed_test_used"] and not manifest["historical_decision_eligible"]
    assert partial_manifest["input_last_date"] == "2023-06-30"
    assert partial_manifest["input_rows"] < manifest["input_rows"]

    preds = pd.read_parquet(full / "market_predictions.parquet")
    prefix = pd.read_parquet(partial / "market_predictions.parquet")
    assert not preds.decision_eligible.any()
    assert not preds.duplicated(["date", "horizon"]).any()
    assert (preds.signal_time < preds.entry_time).all()
    assert (preds.entry_time < preds.exit_time).all()
    assert (preds.feature_available_at > preds.signal_time).all()
    assert (prefix.exit_time.dt.date <= pd.Timestamp("2023-06-30").date()).all()
    assert preds.groupby("horizon").size().to_dict() == {1: 501, 3: 499, 5: 497}
    shared = prefix.merge(preds, on=["date", "horizon"], suffixes=("_short", "_full"), validate="one_to_one")
    assert len(shared) == len(prefix)
    for column in ("p_up", "p_downside", "predicted_return", "actual_return"):
        assert shared[column + "_short"].to_numpy() == pytest.approx(shared[column + "_full"].to_numpy())

    folds = pd.read_parquet(full / "training_folds.parquet")
    assert len(folds) == 24
    assert (folds.train_last_exit < folds.fit_time).all()
    assert folds.train_sessions.between(252, 1260).all()
    clock = TradingClock()
    for fold in folds.itertuples():
        sessions = clock.calendar.sessions_in_range(fold.train_last_signal, fold.first_prediction)
        assert len(sessions) - 2 >= 5

    latest = market_research(tmp_path, 5)
    assert latest["predictions"][0]["horizon"] == 5
    assert latest["states"][0]["date"][:10] == "2024-12-31"
    assert latest["summary"]["increment"][0]["matched_dates"] == 497
    end = market_research(tmp_path, 5, "2024-12-31")
    assert end["predictions"] == [] and end["states"]
    with pytest.raises(PolicyError, match="outside the completed study"):
        market_research(tmp_path, 1, "2025-01-02")
    (full / "market_summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PolicyError, match="SHA256"):
        market_research(tmp_path, 1)


def test_sealed_cutoff_rejected_before_any_data_read(tmp_path):
    with pytest.raises(ValueError, match="sealed"):
        run_study(tmp_path, "2025-01-02")
    assert not list(tmp_path.iterdir())
