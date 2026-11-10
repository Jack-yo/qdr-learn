import json
from pathlib import Path
import socket

import pandas as pd
import pytest
import yaml

from quant_research.cli import main
from quant_research.clock import TradingClock
from quant_research.data.pipeline import fixture_records
from quant_research.data.schema import PriceRecord
from quant_research.data.store import Warehouse
from quant_research.features.factors import FunctionalFactor
from quant_research.research.experiment import load_experiment
from quant_research.research.pipeline import execute


def experiment(tmp_path):
    config = yaml.safe_load(Path("configs/experiments/p2_factors.yaml").read_text())
    config.update(start="2024-11-01",train_end="2024-11-20",validation_end="2024-12-06",bootstrap_block_sessions=5,bootstrap_replicates=100)
    path = tmp_path/"experiment.yaml"
    path.write_text(yaml.safe_dump(config),encoding="utf-8")
    return path


def test_new_factor_report_without_engine_changes_offline(tmp_path, monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket,"connect",forbidden)
    monkeypatch.setattr(socket,"create_connection",forbidden)
    from argparse import Namespace
    args = Namespace(command="factor-report",source="fixture",mode="strict",experiment=experiment(tmp_path),
        horizons="1,3,5",start=None,end=None,asof=None,db=tmp_path/"research.duckdb",output=tmp_path/"out")
    plugin = FunctionalFactor("external_plugin",0,lambda c:c.close,"custom plugin test")
    for _ in range(2):
        assert execute(args,[plugin]) == 0
    manifests = [json.loads(p.read_text()) for p in args.output.glob("*/manifest.json")]
    assert len(manifests)==2
    assert manifests[0]["statistics_sha256"]==manifests[1]["statistics_sha256"]
    assert manifests[0]["data_sha256"]==manifests[1]["data_sha256"]
    assert manifests[0]["config_sha256"]==manifests[1]["config_sha256"]
    for directory in args.output.iterdir():
        summary = pd.read_csv(directory/"summary.csv")
        assert set(summary.factor)=={"external_plugin"}
        assert set(summary.partition)=={"train","validation"}
        assert (directory/"report.html").exists()
        labels = pd.read_parquet(directory/"labels.parquet")
        assert labels.net_return.isna().all()
        # Labels whose exit crosses the train boundary cannot enter training IC counts.
        daily = pd.read_parquet(directory/"daily_ic.parquet")
        train_h5 = daily.loc[daily.partition.eq("train")&daily.horizon.eq(5)]
        assert train_h5.date.max() <= pd.Timestamp("2024-11-13")


def test_sealed_period_rejected_before_read(tmp_path,monkeypatch):
    def no_read(*args,**kwargs):
        pytest.fail("sealed test must be rejected before reading prices")
    monkeypatch.setattr(Warehouse,"prices",no_read)
    with pytest.raises(SystemExit) as exc:
        main(["factor-report","--source","yahoo","--mode","retrospective","--end","2025-01-02","--db",str(tmp_path/"research.duckdb")])
    assert exc.value.code==2


def test_yahoo_strict_vs_retrospective_no_backdating(tmp_path):
    path = experiment(tmp_path)
    records,_ = fixture_records(TradingClock(),"2024-11-01","2024-12-06")
    timestamp = pd.Timestamp("2026-01-01",tz="UTC").to_pydatetime()
    yahoo = [PriceRecord.model_validate({**r.model_dump(),"security_id":"YAHOO:"+r.symbol,"source":"YAHOO","feed":"yahoo",
        "adjustment_basis":"yahoo_split_adjusted","available_at":timestamp,"ingested_at":timestamp,"availability_basis":"first_observed"}) for r in records]
    db = tmp_path/"research.duckdb"
    with Warehouse(db) as store:
        store.put_prices(yahoo,TradingClock())
    common = ["--source","yahoo","--experiment",str(path),"--db",str(db),"--output",str(tmp_path/"out")]
    assert main(["features",*common,"--asof","2024-12-06"]) == 4
    assert main(["factor-report",*common,"--mode","retrospective"]) == 0
    manifests = [json.loads(p.read_text()) for p in (tmp_path/"out").glob("*/manifest.json")]
    report = next(m for m in manifests if m["mode"]=="retrospective")
    assert report["formal_raw_label_count"]==0 and report["proxy_label_count"]>0
    assert report["decision_eligible_features"]==0
    assert report["input_last_date"]=="2024-12-06" and not report["sealed_test_used"]
    with Warehouse(db) as store:
        count = store.db.execute("SELECT count(*) FROM features_daily WHERE decision_eligible").fetchone()[0]
        assert count==0
