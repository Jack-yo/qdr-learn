"""P5 workflow tests: verified feature history, explicit compute/freeze, no future."""
import pandas as pd

from quant_research.research.l2_forecast import HORIZONS, INPUT_FEATURES, STYLE_IDS
from quant_research.workflow import l2_validation


def _settings(label="labels-v1",features="features-v1"):
    return {
        "label_bundle_id":label,
        "feature_bundle_id":features,
        "min_training_sessions":60,
        "embargo_sessions":5,
        "ridge_alpha":1.0,
    }


def _qualification():
    return pd.DataFrame([
        {
            "style_id":style,"horizon":horizon,
            "qualification_status":"OOS_VALIDATED",
            "oos_gate_passed":True,"forward_gate_passed":False,
            "model_admitted":False,
            "reasons":["MODEL_ADMISSION_SWITCH_DISABLED"],
            "decision_eligible":False,"real_orders_enabled":False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def _oos_validation():
    return pd.DataFrame([
        {
            "style_id":style,"horizon":horizon,
            "status":"OOS_VALIDATED","validation_passed":True,
            "oos_sessions":150,"decision_eligible":False,
            "real_orders_enabled":False,
        }
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def _model_features(dates):
    rows=[]
    for day in dates:
        for i,style in enumerate(STYLE_IDS):
            row={
                "date":day,"style_id":style,
                "available_at":pd.Timestamp(day,tz="UTC")+pd.Timedelta(hours=20),
                "model_feature_origin":"VERIFIED_PIT_BUNDLE",
            }
            for j,name in enumerate(INPUT_FEATURES):
                row[name]=0.001*(i+1)+0.0001*j
            rows.append(row)
    # One latest live row-set deliberately included; P5 must strip it.
    live=pd.DataFrame([
        {
            **{name:0.5 for name in INPUT_FEATURES},
            "date":dates[-1],"style_id":style,
            "available_at":pd.Timestamp(dates[-1],tz="UTC")+pd.Timedelta(hours=21),
            "model_feature_origin":"CURRENT_OBSERVATION_ONLY",
        }
        for style in STYLE_IDS
    ])
    historical=pd.DataFrame(rows)
    historical=historical.loc[~(
        historical.date.eq(dates[-1])
    )].copy()
    return pd.concat([historical,live],ignore_index=True)


def _labels(dates,cutoff):
    return pd.DataFrame([
        {
            "date":day,"style_id":style,"horizon":horizon,
            "forward_relative_return":0.001,
            "label_available_at":cutoff-pd.Timedelta(minutes=1),
        }
        for day in dates
        for style in STYLE_IDS for horizon in HORIZONS
    ])


def _wire_common(monkeypatch,dates,cutoff):
    labels=_labels(dates,cutoff)
    monkeypatch.setattr(
        l2_validation,"load_label_bundle_v1",
        lambda *args:(
            labels,{
                "labels_sha256":"a"*64,
                "source_evidence_sha256":"b"*64,
            }
        ),
    )
    metadata={
        "asof_date_et":str(dates[-1].date()),
        "snapshot_sha256":"c"*64,"source":"YAHOO",
    }
    feature_manifest={
        "features_sha256":"d"*64,
        "source_evidence_sha256":"e"*64,
        "price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
        "historical_pit_attested":True,
    }
    monkeypatch.setattr(
        l2_validation,"load_model_feature_frame",
        lambda root,settings,asof=None:(
            _model_features(dates),pd.DataFrame(),metadata,dates,cutoff,
            feature_manifest,
        ),
    )
    monkeypatch.setattr(
        l2_validation,"collect_frozen_forecasts_v1",
        lambda *args:pd.DataFrame(),
    )
    monkeypatch.setattr(
        l2_validation,"score_genuine_forward_v1",
        lambda frozen,labels:pd.DataFrame(),
    )
    monkeypatch.setattr(
        l2_validation,"qualify_models_v1",
        lambda oos,forward,config=None:_qualification(),
    )
    monkeypatch.setattr(
        l2_validation,"validate_oos_v1",
        lambda frame,config=None:_oos_validation(),
    )
    return feature_manifest


def test_missing_label_bundle_blocks_before_any_heavy_research(tmp_path,monkeypatch):
    monkeypatch.setattr(l2_validation,"forecast_settings",lambda root:_settings(label=None,features=None))
    called=[]
    monkeypatch.setattr(
        l2_validation,"load_label_bundle_v1",
        lambda *args:called.append("labels"),
    )
    result=l2_validation.build_validation_report(tmp_path)
    assert result["code"]=="L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
    assert result["historical_feature_pit_attested"] is False
    assert called==[]


def test_missing_feature_bundle_blocks_after_label_config_gate(tmp_path,monkeypatch):
    monkeypatch.setattr(l2_validation,"forecast_settings",lambda root:_settings(features=None))
    called=[]
    monkeypatch.setattr(
        l2_validation,"load_label_bundle_v1",
        lambda *args:called.append("labels"),
    )
    result=l2_validation.build_validation_report(tmp_path)
    assert result["code"]=="L2_VERIFIED_FEATURE_BUNDLE_REQUIRED"
    assert result["historical_feature_pit_attested"] is False
    assert called==[]


def test_p5_uses_fixed_oos_span_and_only_verified_pit_feature_rows(tmp_path,monkeypatch):
    monkeypatch.setattr(l2_validation,"forecast_settings",lambda root:_settings())
    dates=pd.bdate_range("2024-01-02",periods=320)
    cutoff=pd.Timestamp("2026-01-01T00:00:00Z")
    _wire_common(monkeypatch,dates,cutoff)
    monkeypatch.setattr(
        l2_validation,"validation_settings",
        lambda root:l2_validation.ValidationConfig(
            oos_evaluation_sessions=252,min_oos_sessions=126
        ),
    )
    captured={}
    def fake_ablation(observations,known_labels,sessions,evaluation_dates,clock,**kwargs):
        captured["observations"]=observations.copy()
        captured["labels"]=known_labels.copy()
        captured["dates"]=pd.DatetimeIndex(evaluation_dates)
        full=pd.DataFrame([
            {
                "date":captured["dates"][-1],"style_id":style,"horizon":horizon,
                "forward_relative_return":.001,"predicted_relative_return":.001,
                "zero_baseline":0.0,"mean_baseline":.0001,
                "momentum_baseline":.0002,"variant":"full",
            }
            for style in STYLE_IDS for horizon in HORIZONS
        ])
        return full,pd.DataFrame([{"variant":"full","style_id":"size","horizon":1}])
    monkeypatch.setattr(l2_validation,"run_ablation_oos_v1",fake_ablation)
    report=l2_validation.build_validation_report(tmp_path)
    assert report["status"]=="P5_RESEARCH_VALIDATION"
    assert report["evaluation"]["actual_sessions"]==252
    assert len(captured["dates"])==252
    # Latest live observation was intentionally appended by the helper fixture.
    # P5 must never pass it to historical OOS/ablation.
    assert captured["observations"].date.max()<dates[-1]
    assert report["feature_bundle_id"]=="features-v1"
    assert report["feature_bundle_sha256"]=="d"*64
    assert report["historical_feature_pit_attested"] is True
    assert len(report["qualification"])==21
    assert report["summary"]["oos_validated_units"]==21
    assert report["summary"]["model_admitted_units"]==0
    assert report["real_orders_enabled"] is False


def test_unattested_feature_manifest_blocks_p5(tmp_path,monkeypatch):
    monkeypatch.setattr(l2_validation,"forecast_settings",lambda root:_settings())
    dates=pd.bdate_range("2025-01-02",periods=140)
    cutoff=pd.Timestamp("2025-08-01T23:00:00Z")
    _wire_common(monkeypatch,dates,cutoff)
    original=l2_validation.load_model_feature_frame
    monkeypatch.setattr(
        l2_validation,"load_model_feature_frame",
        lambda *args,**kwargs:(
            _model_features(dates),pd.DataFrame(),
            {"asof_date_et":str(dates[-1].date()),"snapshot_sha256":"c"*64,"source":"YAHOO"},
            dates,cutoff,
            {"features_sha256":"d"*64,"source_evidence_sha256":"e"*64,
             "price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
             "historical_pit_attested":False},
        ),
    )
    result=l2_validation.build_validation_report(tmp_path)
    assert result["status"]=="BLOCKED"
    assert result["code"]=="L2_HISTORICAL_FEATURE_PIT_NOT_ATTESTED"


def test_p5_excludes_post_cutoff_labels_and_future_frozen_snapshots(tmp_path,monkeypatch):
    monkeypatch.setattr(l2_validation,"forecast_settings",lambda root:_settings())
    dates=pd.bdate_range("2025-01-02",periods=140)
    cutoff=pd.Timestamp("2025-07-01T23:00:00Z")
    labels=_labels(dates[:-10],cutoff)
    future=_labels(dates[-10:],cutoff+pd.Timedelta(days=10))
    labels=pd.concat([labels,future],ignore_index=True)
    monkeypatch.setattr(
        l2_validation,"load_label_bundle_v1",
        lambda *args:(labels,{"labels_sha256":"a"*64,"source_evidence_sha256":"b"*64}),
    )
    monkeypatch.setattr(
        l2_validation,"load_model_feature_frame",
        lambda *args,**kwargs:(
            _model_features(dates),pd.DataFrame(),
            {"asof_date_et":str(dates[-1].date()),"snapshot_sha256":"c"*64,"source":"YAHOO"},
            dates,cutoff,
            {"features_sha256":"d"*64,"source_evidence_sha256":"e"*64,
             "price_basis":"VERIFIED_ACTION_CONSISTENT_HISTORICAL_FEATURE_BASIS",
             "historical_pit_attested":True},
        ),
    )
    monkeypatch.setattr(
        l2_validation,"validation_settings",
        lambda root:l2_validation.ValidationConfig(
            oos_evaluation_sessions=126,min_oos_sessions=60
        ),
    )
    captured={}
    def fake_ablation(obs,known,sessions,evaluation,clock,**kwargs):
        captured["labels"]=known.copy();captured["dates"]=pd.DatetimeIndex(evaluation)
        full=pd.DataFrame([
            {"date":captured["dates"][-1],"style_id":s,"horizon":h,
             "forward_relative_return":.001,"predicted_relative_return":.001,
             "zero_baseline":0.0,"mean_baseline":0.0,"momentum_baseline":0.0,
             "variant":"full"}
            for s in STYLE_IDS for h in HORIZONS
        ])
        return full,pd.DataFrame()
    monkeypatch.setattr(l2_validation,"run_ablation_oos_v1",fake_ablation)
    monkeypatch.setattr(l2_validation,"validate_oos_v1",lambda *a,**k:_oos_validation())
    frozen=pd.DataFrame([
        {"date":dates[-20],"style_id":"size","horizon":1},
        {"date":dates[-1]+pd.Timedelta(days=10),"style_id":"size","horizon":1},
    ])
    monkeypatch.setattr(l2_validation,"collect_frozen_forecasts_v1",lambda *a:frozen.copy())
    seen={}
    monkeypatch.setattr(
        l2_validation,"score_genuine_forward_v1",
        lambda fr,lab:(seen.update({"frozen":fr.copy(),"labels":lab.copy()}) or pd.DataFrame()),
    )
    monkeypatch.setattr(l2_validation,"qualify_models_v1",lambda *a,**k:_qualification())
    report=l2_validation.build_validation_report(tmp_path)
    assert report["status"]=="P5_RESEARCH_VALIDATION"
    assert captured["labels"].label_available_at.le(cutoff).all()
    assert captured["dates"].max()<=dates[-11]
    assert pd.to_datetime(seen["frozen"].date).max()<=dates[-1]
    assert seen["labels"].label_available_at.le(cutoff).all()


def test_read_latest_validation_never_calls_heavy_builder(tmp_path,monkeypatch):
    called=[]
    monkeypatch.setattr(l2_validation,"build_validation_report",lambda *a,**k:called.append("build"))
    monkeypatch.setattr(
        l2_validation,"load_latest_validation_v1",
        lambda root,asof=None:{
            "schema":"qdr.l2.validation-report.v1",
            "status":"P5_RESEARCH_VALIDATION",
            "asof_session":asof or "2026-01-30",
            "qualification":[],"real_orders_enabled":False,
        },
    )
    result=l2_validation.read_latest_validation(tmp_path,asof="2026-01-30")
    assert result["status"]=="P5_RESEARCH_VALIDATION"
    assert called==[]


def test_freeze_validation_writes_only_completed_report(tmp_path,monkeypatch):
    called=[]
    monkeypatch.setattr(
        l2_validation,"build_validation_report",
        lambda root,asof=None:{
            "status":"BLOCKED","code":"L2_VERIFIED_FEATURE_BUNDLE_REQUIRED",
            "asof_session":asof,
        },
    )
    monkeypatch.setattr(
        l2_validation,"freeze_validation_report_v1",
        lambda *a,**k:called.append("freeze"),
    )
    blocked=l2_validation.freeze_validation(tmp_path,asof="2026-01-30")
    assert blocked["status"]=="BLOCKED_NO_VALIDATION_ARCHIVE_WRITE"
    assert called==[]

    monkeypatch.setattr(
        l2_validation,"build_validation_report",
        lambda root,asof=None:{
            "status":"P5_RESEARCH_VALIDATION","asof_session":"2026-01-30",
            "real_orders_enabled":False,
        },
    )
    monkeypatch.setattr(
        l2_validation,"freeze_validation_report_v1",
        lambda root,report:{
            **report,"identity":"f"*64,
            "frozen_at_utc":"2026-01-31T00:00:00+00:00",
            "summary":{"model_admitted_units":0},
        },
    )
    frozen=l2_validation.freeze_validation(tmp_path,asof="2026-01-30")
    assert frozen["status"]=="FROZEN_P5_RESEARCH_VALIDATION"
    assert frozen["identity"]=="f"*64
    assert frozen["real_orders_enabled"] is False
