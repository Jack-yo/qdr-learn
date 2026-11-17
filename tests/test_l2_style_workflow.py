"""L2 read-only workflow tests; no live data or warehouse writes."""
from pathlib import Path

import pandas as pd
import pytest

from quant_research.data.bundle import DatasetBundle
from quant_research.workflow import l2_styles


def _bundle():
    sessions = pd.bdate_range("2025-01-02", periods=70)
    symbols = list(l2_styles.REQUIRED_SYMBOLS)
    rows = []
    for i, symbol in enumerate(symbols):
        for j, day in enumerate(sessions):
            rows.append({
                "date": day, "symbol": symbol, "close": 80 + i + j * (0.1 + i * 0.001),
                "available_at": pd.Timestamp(day, tz="UTC") + pd.Timedelta(hours=22),
                "adjustment_basis": "yahoo_split_adjusted",
            })
    prices = pd.DataFrame(rows)
    metadata = {
        "source": "YAHOO", "feed": "yahoo",
        "asof_date_et": str(sessions[-1].date()),
        "knowledge_cutoff_utc": "2025-04-15T22:00:00+00:00",
        "snapshot_sha256": "a" * 64,
    }
    return DatasetBundle(prices, metadata, {})


def test_workflow_uses_existing_bundle_read_only_and_returns_seven_styles(monkeypatch):
    bundle = _bundle()
    calls = []

    def load(*args, **kwargs):
        calls.append((args, kwargs))
        return bundle

    monkeypatch.setattr(l2_styles, "load_real_bundle", load)
    payload = l2_styles.calculate(Path("."), asof="2025-04-09")
    assert len(calls) == 1
    assert calls[0][0][0] == Path(".") / "data/research.duckdb"
    assert calls[0][1]["symbols"] == list(l2_styles.REQUIRED_SYMBOLS)
    assert payload["status"] == "OBSERVATION_ONLY"
    assert len(payload["latest"]) == 7
    assert payload["historical_decision_eligible"] is False
    assert payload["real_orders_enabled"] is False
    assert payload["coverage"]["symbols_with_asof_price"] == 14
    assert all(x["observation_status"] == "OBSERVATION_ONLY" for x in payload["latest"])


def test_workflow_rejects_non_yahoo_source_without_provider_fallback():
    with pytest.raises(ValueError, match="SPLIT_ADJUSTED_YAHOO"):
        l2_styles.calculate(Path("."), source="alpaca")


def test_workflow_rejects_unexpected_price_basis(monkeypatch):
    bundle = _bundle()
    prices = bundle.prices
    prices["adjustment_basis"] = "raw"
    bad = DatasetBundle(prices, bundle.metadata, {})
    monkeypatch.setattr(l2_styles, "load_real_bundle", lambda *a, **k: bad)
    with pytest.raises(ValueError, match="PRICE_BASIS"):
        l2_styles.calculate(Path("."))


def test_workflow_reports_missing_asof_symbol_without_fabricating_price(monkeypatch):
    bundle = _bundle()
    prices = bundle.prices
    end = pd.Timestamp(bundle.metadata["asof_date_et"])
    prices = prices.loc[~(prices.symbol.eq("XLY") & pd.to_datetime(prices.date).eq(end))]
    partial = DatasetBundle(prices, bundle.metadata, {})
    monkeypatch.setattr(l2_styles, "load_real_bundle", lambda *a, **k: partial)
    payload = l2_styles.calculate(Path("."))
    assert payload["coverage"]["symbols_with_asof_price"] == 13
    cyc = next(x for x in payload["latest"] if x["style_id"] == "cyc_def")
    assert cyc["observation_status"] == "BLOCKED_INCOMPLETE_5D_WINDOW"
    assert cyc["relative_return_5d"] is None
