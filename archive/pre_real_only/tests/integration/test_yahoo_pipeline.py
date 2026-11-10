from datetime import datetime, timezone
import hashlib
import json

import pyarrow.parquet as pq
import pytest

from quant_research.cli import main
from quant_research.clock import TradingClock
from quant_research.data.http import RawResponse
from quant_research.data.providers.yahoo import parse_chart
from quant_research.data.quality import audit
from quant_research.data.store import Warehouse


def test_yahoo_pipeline_replay_and_separate_basis(tmp_path, monkeypatch):
    # Use a self-contained synthetic Yahoo-format chart, never a mocked real-data claim.
    chart = {"chart":{"error":None,"result":[{
        "meta":{"symbol":"SPY","currency":"USD","exchangeTimezoneName":"America/New_York","dataGranularity":"1d"},
        "timestamp":[1732717800],
        "indicators":{"quote":[{"open":[100],"high":[102],"low":[99],"close":[101],"volume":[1000]}],"adjclose":[{"adjclose":[99]}]},
        "events":{"dividends":{"test":{"date":1732717800,"amount":0.25}}}
    }]}}
    body = json.dumps(chart).encode()
    from quant_research.data.providers.yahoo import YFinanceDownloader
    monkeypatch.setattr(YFinanceDownloader,"__call__",lambda *_:body)
    monkeypatch.setattr("quant_research.data.providers.yahoo.time.sleep",lambda _:None)
    common = ["--source","yahoo","--symbols","SPY","--start","2024-11-27","--end","2024-11-27",
              "--db",str(tmp_path/"research.duckdb"),"--data-dir",str(tmp_path/"data"),"--output",str(tmp_path/"out")]
    assert main(["ingest",*common]) == 0
    assert main(["ingest",*common,"--offline"]) == 0
    manifests = [json.loads(p.read_text()) for p in (tmp_path/"out").glob("*/manifest.json")]
    assert sorted(m["inserted_rows"] for m in manifests) == [0,1]
    assert sorted(m["inserted_actions"] for m in manifests) == [0,1]
    assert all(not m["raw_execution_prices_available"] for m in manifests)
    assert all("NOT_RAW_EXECUTION_PRICE" in m["flags"] for m in manifests)
    with Warehouse(tmp_path/"research.duckdb") as store:
        assert store.count("corporate_actions") == 1
        assert store.prices("YAHOO","yahoo",cutoff=TradingClock().signal("2024-11-27")).num_rows == 0
        path = store.export_prices(tmp_path/"silver","YAHOO","yahoo")
        rows = pq.read_table(path).to_pylist()
        assert rows[0]["adj_close"] == 99
        assert rows[0]["adjustment_basis"] == "yahoo_split_adjusted"
