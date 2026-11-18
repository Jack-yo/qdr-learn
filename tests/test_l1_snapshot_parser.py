"""Alpaca snapshot response-shape contracts; fixtures are not live acceptance."""
from datetime import datetime, timezone
import json

import pytest

from quant_research.data.l1_light_sources import LiveSources


@pytest.mark.parametrize(
    ("document", "expected_shape"),
    [
        (
            {
                "SPY": {"latestTrade": {"p": 500.0}},
                "QQQ": {"latestTrade": {"p": 600.0}},
                "next_page_token": "metadata-is-not-a-symbol",
            },
            "TOP_LEVEL_SYMBOL_MAP",
        ),
        (
            {
                "snapshots": {
                    "SPY": {"latestTrade": {"p": 500.0}},
                    "QQQ": {"latestTrade": {"p": 600.0}},
                },
                "next_page_token": None,
            },
            "SNAPSHOTS_ENVELOPE",
        ),
    ],
)
def test_snapshots_accepts_documented_symbol_map_shapes(tmp_path, document, expected_shape):
    payload = json.dumps(document).encode("utf-8")
    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        return payload

    stamp = datetime(2026, 11, 17, 23, tzinfo=timezone.utc)
    source = LiveSources(
        tmp_path,
        fetch=fetch,
        env={
            "ALPACA_API_KEY": "test-key",
            "ALPACA_SECRET_KEY": "test-secret",
            "QDR_L1_FEED": "iex",
        },
        now=lambda: stamp,
    )
    snapshots, receipt = source.snapshots(
        refresh=True, symbols=["spy", "qqq", "AAPL"])
    assert set(snapshots) == {"SPY", "QQQ"}
    assert receipt["response_shape"] == expected_shape
    assert receipt["requested_symbols"] == 3
    assert receipt["returned_symbols"] == 2
    assert receipt["scope"] == "LAST_TRADE_LEVEL1_QUOTE_NOT_FULL_DEPTH"
    assert len(calls) == 1
    assert "test-key" not in calls[0][0]
    assert "test-secret" not in calls[0][0]


def test_snapshots_rejects_metadata_only_response(tmp_path):
    source = LiveSources(
        tmp_path,
        fetch=lambda url, headers: b'{"next_page_token":null}',
        env={
            "ALPACA_API_KEY": "test-key",
            "ALPACA_SECRET_KEY": "test-secret",
            "QDR_L1_FEED": "iex",
        },
    )
    with pytest.raises(Exception, match="INVALID_ALPACA_SNAPSHOTS"):
        source.snapshots(refresh=True, symbols=["SPY"])
