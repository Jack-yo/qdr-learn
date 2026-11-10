from argparse import Namespace
import json
from pathlib import Path
import socket

import numpy as np
import pandas as pd
import yaml
import hashlib
import pytest

from quant_research.cli import main
from quant_research.clock import TradingClock
from quant_research.data.providers.stream_fixture import stream_fixture_records
from quant_research.features.context import make_context
from quant_research.models.dataset import prepare
from quant_research.models.settings import load_settings
from quant_research.models.walk_forward import train_alpha
from quant_research.workflow.backtest import execute as backtest
from quant_research.workflow.daily import execute as daily


def config_path(tmp_path):
    values=yaml.safe_load(Path("configs/experiments/baseline.yaml").read_text())
    values.update(start="2021-01-01",train_end="2022-12-31",validation_end="2023-01-31",minimum_training_sessions=60,training_window_sessions=252)
    path=tmp_path/"baseline.yaml"
    path.write_text(yaml.safe_dump(values),encoding="utf-8")
    return path


def test_complete_offline_workflow_and_sql_ledger(tmp_path,monkeypatch):
    def no_network(*args,**kwargs): raise AssertionError("network forbidden")
    monkeypatch.setattr(socket.socket,"connect",no_network)
    monkeypatch.setattr(socket,"create_connection",no_network)
    experiment=config_path(tmp_path)
    assert main(["run-all","--source","fixture","--experiment",str(experiment),"--db",str(tmp_path/"research.duckdb"),
                 "--output",str(tmp_path/"out"),"--state-db",str(tmp_path/"paper.sqlite3")])==0
    manifests=[json.loads(p.read_text()) for p in (tmp_path/"out").glob("*/manifest.json")]
    assert {"P3","P4","P5","P6","P3-P6"} <= {m["stage"] for m in manifests}
    assert all(not m["research_grade"] for m in manifests)
    execution=next(m for m in manifests if m["stage"]=="P5")
    assert execution["experiments"]==108
    training=next(m for m in manifests if m["stage"]=="P4")
    predictions=pd.read_parquet(tmp_path/"out"/training["run_id"]/"predictions.parquet")
    assert set(predictions.variant)==set("ABCD")
    assert predictions.p_up.between(0,1).all() and predictions.uncertainty.isna().all()
    folds=pd.read_parquet(tmp_path/"out"/training["run_id"]/"alpha_training_folds.parquet")
    assert (folds.train_last_exit<folds.fit_time).all()
    assert (folds.train_last_available<folds.fit_time).all()
    from quant_research.data.store import Warehouse
    with Warehouse(tmp_path/"research.duckdb") as store:
        assert store.count("predictions")==len(predictions)
        assert store.count("fills")>0
        assert store.count("equity_curve")>0
    # Same date replay must not add fills or days.
    import sqlite3
    with sqlite3.connect(tmp_path/"paper.sqlite3") as db:
        before=db.execute("SELECT count(*) FROM events").fetchone()[0]
        assert db.execute("SELECT count(*) FROM days").fetchone()[0]==2
    assert main(["paper-replay","--source","fixture","--asof","2023-01-31","--experiment",str(experiment),"--db",str(tmp_path/"research.duckdb"),
                 "--output",str(tmp_path/"out"),"--state-db",str(tmp_path/"paper.sqlite3")])==0
    with sqlite3.connect(tmp_path/"paper.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM events").fetchone()[0]==before
        assert db.execute("SELECT count(*) FROM days").fetchone()[0]==2


def test_future_validation_labels_and_transforms_cannot_change_first_prediction(tmp_path):
    config=load_settings(config_path(tmp_path))
    clock=TradingClock()
    records,_=stream_fixture_records(clock,str(config.start),str(config.validation_end))
    context=make_context(pd.DataFrame([r.model_dump() for r in records]),clock)
    frame,observed,market,style=prepare(context,clock,"strict","raw")
    original,_=train_alpha(frame,observed,clock,config,"strict",market,style)
    changed=frame.copy()
    changed.loc[changed.date>"2023-01-10","reversal_5d"]*=100000
    changed.loc[changed.date>"2023-01-01",["target","excess_target"]]=0.9
    again,_=train_alpha(changed,observed,clock,config,"strict",market,style)
    first=original.date.min()
    np.testing.assert_allclose(original.loc[original.date.eq(first),["p_up","predicted_return"]],again.loc[again.date.eq(first),["p_up","predicted_return"]])


def test_yahoo_backtest_and_stale_daily_never_write_paper(tmp_path,monkeypatch):
    path=config_path(tmp_path)
    args=Namespace(source="yahoo",mode="retrospective",experiment=path,db=tmp_path/"data.duckdb",output=tmp_path/"out",
        training_run=None,asof="2023-01-31",state_db=tmp_path/"paper.sqlite3",command="backtest")
    prices=pd.DataFrame({"date":[pd.Timestamp("2023-01-30")],"source":["YAHOO"],"adjustment_basis":["yahoo_split_adjusted"]})
    monkeypatch.setattr("quant_research.workflow.backtest.load_panel",lambda *_args,**_kwargs:(prices,None,None))
    assert backtest(args)==4
    clock=TradingClock()
    records,_=stream_fixture_records(clock,"2021-01-01","2023-01-30")
    data=pd.DataFrame([r.model_dump() for r in records])
    data["available_at"]=pd.Timestamp("2026-01-01",tz="UTC")
    data["adjustment_basis"]="yahoo_split_adjusted"
    context=make_context(data,clock,start="2021-01-01",end="2023-01-31")
    monkeypatch.setattr("quant_research.workflow.daily.load_panel",lambda *_args,**_kwargs:(data,context,clock))
    args.command,args.mode="paper-step","strict"
    assert daily(args)==4
    assert not args.state_db.exists()
    manifests=[json.loads(p.read_text()) for p in args.output.glob("*/manifest.json")]
    assert next(m for m in manifests if m["stage"]=="P6")["candidate_rows"]==0


def test_api_refresh_failure_writes_no_new_advice(tmp_path,monkeypatch):
    monkeypatch.setattr("quant_research.data.pipeline.execute",lambda _args:3)
    args=Namespace(source="yahoo",mode="strict",experiment=config_path(tmp_path),db=tmp_path/"data.duckdb",output=tmp_path/"out",
                   training_run=None,asof="2023-01-31",state_db=tmp_path/"paper.sqlite3",command="scheduled-run")
    assert daily(args)==4
    manifest=json.loads(next(args.output.glob("*/manifest.json")).read_text())
    assert manifest["status"]=="DATA_REFRESH_FAILED_NO_NEW_ADVICE" and manifest["candidate_rows"]==0
    assert not args.state_db.exists()


def test_execution_rejects_different_training_price_snapshot(tmp_path,monkeypatch):
    from quant_research.workflow.common import fingerprint
    path=config_path(tmp_path)
    config=load_settings(path)
    artifact=tmp_path/"training"
    artifact.mkdir()
    pd.DataFrame({"date":[pd.Timestamp("2023-01-03")]}).to_parquet(artifact/"predictions.parquet",index=False)
    metadata={"source":"fixture","mode":"strict","config_sha256":fingerprint(config.model_dump(mode="json")),
        "data_sha256":"0"*64,"artifacts_sha256":{"predictions.parquet":hashlib.sha256((artifact/"predictions.parquet").read_bytes()).hexdigest()}}
    (artifact/"manifest.json").write_text(json.dumps(metadata),encoding="utf-8")
    args=Namespace(source="fixture",mode="strict",experiment=path,db=tmp_path/"data.duckdb",output=tmp_path/"out",training_run=artifact,asof=None)
    prices=pd.DataFrame({"date":[pd.Timestamp("2023-01-03")]})
    monkeypatch.setattr("quant_research.workflow.backtest.load_panel",lambda *_args,**_kwargs:(prices,None,None))
    with pytest.raises(ValueError,match="frozen training input"):
        backtest(args)
