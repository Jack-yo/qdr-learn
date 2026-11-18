"""P4 read-only forecast workflow tests with separate label/feature evidence."""
import pandas as pd

from quant_research.research.l2_forecast import (
    HORIZONS, INPUT_FEATURES, STYLE_IDS,
)
from quant_research.workflow import l2_forecast


def _config(root,label="accepted-labels",features="accepted-features"):
    folder=root/"configs";folder.mkdir(exist_ok=True)
    (folder/"l2_forecast.yaml").write_text(
        "label_bundle_id: "+("null" if label is None else label)+"\n"
        "feature_bundle_id: "+("null" if features is None else features)+"\n"
        "min_training_sessions: 60\n"
        "embargo_sessions: 5\n"
        "ridge_alpha: 1.0\n",encoding="utf-8",
    )


def _model_frame(sessions):
    rows=[]
    for day in sessions:
        for i,style in enumerate(STYLE_IDS):
            row={
                "date":day,"style_id":style,
                "available_at":pd.Timestamp(day,tz="UTC")+pd.Timedelta(hours=21),
                "model_feature_origin":"VERIFIED_PIT_BUNDLE",
            }
            for j,name in enumerate(INPUT_FEATURES):
                row[name]=0.001*(i+1)+0.0001*j
            rows.append(row)
    return pd.DataFrame(rows)


def _rows(day,status="RESEARCH_ONLY"):
    return pd.DataFrame([
        {
            "date":str(pd.Timestamp(day).date()),
            "style_id":style,"horizon":horizon,
            "predicted_relative_return":0.001 if status=="RESEARCH_ONLY" else None,
            "zero_baseline":0.0,"mean_baseline":0.0002,
            "momentum_baseline":0.0003,
            "forecast_status":status,
            "block_reason":None if status=="RESEARCH_ONLY" else "INCOMPLETE_CURRENT_FEATURE_VECTOR",
            "decision_eligible":False,"real_orders_enabled":False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def test_missing_label_bundle_is_explicit_blocker(tmp_path):
    _config(tmp_path,label=None,features=None)
    result=l2_forecast.calculate_forecast(tmp_path)
    assert result["status"]=="BLOCKED"
    assert result["code"]=="L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert result["blocked_units"]==21
    assert result["forecasts"]==[]
    assert result["historical_feature_pit_attested"] is False
    assert result["real_orders_enabled"] is False


def test_missing_feature_bundle_blocks_after_label_gate(tmp_path,monkeypatch):
    _config(tmp_path,label="labels-v1",features=None)
    called=[]
    monkeypatch.setattr(
        l2_forecast,"load_label_bundle_v1",
        lambda *args:called.append("labels") or (pd.DataFrame(),{}),
    )
    result=l2_forecast.calculate_forecast(tmp_path)
    assert result["status"]=="BLOCKED"
    assert result["code"]=="L2_VERIFIED_FEATURE_BUNDLE_REQUIRED"
    assert result["historical_feature_pit_attested"] is False
    assert called==[]  # feature gate is checked before any bundle/model read


def test_configured_bundles_drive_21_research_units(tmp_path,monkeypatch):
    _config(tmp_path)
    sessions=pd.bdate_range("2025-01-02",periods=80)
    day=sessions[-1]
    labels=pd.DataFrame({"x":[1]})
    label_manifest={"labels_sha256":"a"*64,"source_evidence_sha256":"b"*64}
    feature_manifest={
        "features_sha256":"c"*64,"source_evidence_sha256":"d"*64,
        "price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
        "historical_pit_attested":True,
    }
    metadata={
        "asof_date_et":str(day.date()),
        "knowledge_cutoff_utc":"2025-04-23T22:00:00+00:00",
        "snapshot_sha256":"e"*64,"source":"YAHOO",
        "adjustment_basis":"yahoo_split_adjusted",
    }
    calls=[]
    monkeypatch.setattr(
        l2_forecast,"load_label_bundle_v1",
        lambda root,bundle_id,clock:(
            calls.append(("labels",bundle_id)) or (labels,label_manifest)
        ),
    )
    monkeypatch.setattr(
        l2_forecast,"load_model_feature_frame",
        lambda root,settings,asof=None,start="2017-01-03":(
            calls.append(("features",settings["feature_bundle_id"],asof)) or
            (_model_frame(sessions),pd.DataFrame(),metadata,sessions,
             pd.Timestamp("2025-04-23T22:00:00Z"),feature_manifest)
        ),
    )
    monkeypatch.setattr(
        l2_forecast,"forecast_asof_v1",
        lambda observations,labels,sessions,day,clock,config:(
            calls.append(("forecast",len(observations))) or _rows(day)
        ),
    )
    result=l2_forecast.calculate_forecast(tmp_path)
    assert result["status"]=="RESEARCH_ONLY"
    assert result["eligible_units"]==21
    assert len(result["forecasts"])==21
    assert result["label_bundle_id"]=="accepted-labels"
    assert result["feature_bundle_id"]=="accepted-features"
    assert result["label_bundle_sha256"]=="a"*64
    assert result["feature_bundle_sha256"]=="c"*64
    assert result["historical_feature_pit_attested"] is True
    assert result["source_snapshot_sha256"]=="e"*64
    assert calls[0]==("labels","accepted-labels")
    assert calls[1]==("features","accepted-features",None)
    assert calls[2][0]=="forecast"


def test_horizon_filter_keeps_seven_explicit_units(tmp_path,monkeypatch):
    _config(tmp_path)
    sessions=pd.bdate_range("2025-01-02",periods=80);day=sessions[-1]
    monkeypatch.setattr(
        l2_forecast,"load_label_bundle_v1",
        lambda *args:(pd.DataFrame(),{
            "labels_sha256":"a"*64,"source_evidence_sha256":"b"*64,
        }),
    )
    metadata={
        "asof_date_et":str(day.date()),"knowledge_cutoff_utc":"2025-04-23T22:00:00+00:00",
        "snapshot_sha256":"c"*64,"source":"YAHOO",
    }
    monkeypatch.setattr(
        l2_forecast,"load_model_feature_frame",
        lambda *args,**kwargs:(
            _model_frame(sessions),pd.DataFrame(),metadata,sessions,
            pd.Timestamp("2025-04-23T22:00:00Z"),
            {"features_sha256":"d"*64,"source_evidence_sha256":"e"*64,
             "price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
             "historical_pit_attested":True},
        ),
    )
    monkeypatch.setattr(
        l2_forecast,"forecast_asof_v1",
        lambda *args,**kwargs:_rows(day,status="BLOCKED"),
    )
    result=l2_forecast.calculate_forecast(tmp_path,horizon=3)
    assert len(result["forecasts"])==7
    assert result["blocked_units"]==7
    assert {row["horizon"] for row in result["forecasts"]}=={3}


def test_historical_replay_never_falls_back_to_current_vintage_observation(
    tmp_path,monkeypatch
):
    settings={"feature_bundle_id":"features-v1"}
    sessions=pd.bdate_range("2025-01-02",periods=80)
    day=sessions[-1]
    verified=_model_frame(sessions[:-1]).drop(columns=["model_feature_origin"])
    verified["feature_pit_eligible"]=True
    feature_manifest={"historical_pit_attested":True}
    current=_model_frame(sessions).drop(columns=["model_feature_origin"])
    metadata={"asof_date_et":str(day.date())}
    monkeypatch.setattr(
        l2_forecast,"load_feature_bundle_v1",
        lambda *args:(verified,feature_manifest),
    )
    monkeypatch.setattr(
        l2_forecast,"load_observation_frame",
        lambda *args,**kwargs:(
            current,pd.DataFrame(),metadata,sessions,
            pd.Timestamp("2025-04-23T22:00:00Z"),
        ),
    )
    replay,*_=l2_forecast.load_model_feature_frame(
        tmp_path,settings,asof=str(day.date()),start=str(sessions[0].date())
    )
    assert replay.date.max()==sessions[-2]
    assert not replay.date.eq(day).any()


def test_latest_inference_may_append_current_observation_only(tmp_path,monkeypatch):
    settings={"feature_bundle_id":"features-v1"}
    sessions=pd.bdate_range("2025-01-02",periods=80);day=sessions[-1]
    verified=_model_frame(sessions[:-1]).drop(columns=["model_feature_origin"])
    verified["feature_pit_eligible"]=True
    current=_model_frame(sessions).drop(columns=["model_feature_origin"])
    metadata={"asof_date_et":str(day.date())}
    monkeypatch.setattr(
        l2_forecast,"load_feature_bundle_v1",
        lambda *args:(verified,{"historical_pit_attested":True}),
    )
    monkeypatch.setattr(
        l2_forecast,"load_observation_frame",
        lambda *args,**kwargs:(
            current,pd.DataFrame(),metadata,sessions,
            pd.Timestamp("2025-04-23T22:00:00Z"),
        ),
    )
    frame,*_=l2_forecast.load_model_feature_frame(
        tmp_path,settings,asof=None,start=str(sessions[0].date())
    )
    latest=frame.loc[frame.date.eq(day)]
    assert len(latest)==7
    assert set(latest.model_feature_origin)=={"CURRENT_OBSERVATION_ONLY"}
    history=frame.loc[frame.date.lt(day)]
    assert set(history.model_feature_origin)=={"VERIFIED_PIT_BUNDLE"}
