"""Read-only QDR L2 P4 forecast workflow.

Training history is admitted only from an immutable verified feature bundle and
an immutable verified forward-label bundle. The latest live inference row may
come from the current observation source; explicit historical replay never
falls back to today's revised Yahoo history.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from quant_research.clock import TradingClock
from quant_research.research.l2_feature_bundle import load_feature_bundle_v1
from quant_research.research.l2_forecast import (
    FORECAST_PROTOCOL_VERSION,
    INPUT_FEATURES,
    MODEL_VERSION,
    STYLE_IDS,
    ForecastConfig,
    forecast_asof_v1,
)
from quant_research.research.l2_label_bundle import load_label_bundle_v1
from quant_research.workflow.l2_styles import load_observation_frame


def _settings(root: Path) -> dict:
    path=Path(root)/"configs/l2_forecast.yaml"
    defaults={
        "label_bundle_id":None,
        "feature_bundle_id":None,
        "min_training_sessions":252,
        "embargo_sessions":5,
        "ridge_alpha":1.0,
    }
    if not path.is_file():
        return defaults
    data=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if set(data)-set(defaults):
        raise ValueError("Unexpected L2 forecast config keys")
    return {
        "label_bundle_id":data.get("label_bundle_id"),
        "feature_bundle_id":data.get("feature_bundle_id"),
        "min_training_sessions":int(data.get("min_training_sessions",252)),
        "embargo_sessions":int(data.get("embargo_sessions",5)),
        "ridge_alpha":float(data.get("ridge_alpha",1.0)),
    }


def _blocked(asof,code,horizon,missing):
    return {
        "schema":"qdr.l2.forecast.v1",
        "status":"BLOCKED",
        "code":code,
        "asof_session":asof,
        "forecast_protocol_version":FORECAST_PROTOCOL_VERSION,
        "model_version":MODEL_VERSION,
        "forecasts":[],
        "eligible_units":0,
        "blocked_units":21 if horizon is None else 7,
        "historical_decision_eligible":False,
        "historical_feature_pit_attested":False,
        "real_orders_enabled":False,
        "missing_evidence":missing,
    }


def load_model_feature_frame(
    root: Path,settings: dict,*,asof: str|None=None,start: str="2017-01-03"
):
    """Return PIT training rows plus, only for live inference, current observations."""
    root=Path(root).resolve()
    feature_id=settings.get("feature_bundle_id")
    if not feature_id:
        raise FileNotFoundError("L2_VERIFIED_FEATURE_BUNDLE_REQUIRED")
    verified,feature_manifest=load_feature_bundle_v1(root,feature_id)
    current,_,metadata,sessions,cutoff=load_observation_frame(
        root,asof=asof,start=start
    )
    day=pd.Timestamp(metadata["asof_date_et"]).tz_localize(None).normalize()
    columns=["date","style_id","available_at",*INPUT_FEATURES]
    history=verified.loc[
        verified.feature_pit_eligible.eq(True)
        & verified.date.le(day)
        & verified.date.ge(pd.Timestamp(start)),
        columns,
    ].copy()
    history["model_feature_origin"]="VERIFIED_PIT_BUNDLE"

    present=set(
        history.loc[history.date.eq(day),"style_id"].astype(str)
    )
    # Historical replay must use the historical evidence bundle for the signal
    # date itself. Only the live/latest call may append today's observation.
    if asof is None:
        missing_styles=set(STYLE_IDS)-present
        if missing_styles:
            latest=current.loc[
                current.date.eq(day)&current.style_id.isin(missing_styles),
                columns,
            ].copy()
            latest["model_feature_origin"]="CURRENT_OBSERVATION_ONLY"
            history=pd.concat([history,latest],ignore_index=True)
    if history.duplicated(["date","style_id"]).any():
        raise ValueError("L2_MODEL_FEATURE_DUPLICATE_STYLE_SESSION")
    return (
        history.sort_values(["date","style_id"],kind="stable").reset_index(drop=True),
        current,
        metadata,
        sessions,
        cutoff,
        feature_manifest,
    )


def calculate_forecast(root: Path,*,asof: str|None=None,
                       horizon: int|None=None,
                       start: str="2017-01-03")->dict:
    """Return P4 research predictions or an explicit source-evidence blocker."""
    root=Path(root).resolve();settings=_settings(root)
    if horizon is not None and horizon not in (1,3,5):
        raise ValueError("L2 forecast horizon must be 1, 3 or 5")
    label_id=settings["label_bundle_id"]
    if not label_id:
        return _blocked(
            asof,"L2_VERIFIED_LABEL_BUNDLE_REQUIRED",horizon,
            [
                "independently verified action-consistent T+1-open to T+H-close labels",
                "immutable source-hashed L2 label bundle",
            ],
        )
    feature_id=settings["feature_bundle_id"]
    if not feature_id:
        return _blocked(
            asof,"L2_VERIFIED_FEATURE_BUNDLE_REQUIRED",horizon,
            [
                "historical action-consistent style features known by each T signal",
                "immutable source-hashed L2 feature bundle",
            ],
        )

    clock=TradingClock()
    labels,label_manifest=load_label_bundle_v1(root,label_id,clock)
    observations,current,metadata,sessions,_,feature_manifest=load_model_feature_frame(
        root,settings,asof=asof,start=start
    )
    day=pd.Timestamp(metadata["asof_date_et"]).tz_localize(None).normalize()
    config=ForecastConfig(
        min_training_sessions=settings["min_training_sessions"],
        embargo_sessions=settings["embargo_sessions"],
        ridge_alpha=settings["ridge_alpha"],
    )
    forecasts=forecast_asof_v1(
        observations,labels,sessions,day,clock,config=config
    )
    if horizon is not None:
        forecasts=forecasts.loc[forecasts.horizon.eq(horizon)].copy()
    eligible=int(forecasts.forecast_status.eq("RESEARCH_ONLY").sum())
    blocked=int(forecasts.forecast_status.eq("BLOCKED").sum())
    records=json.loads(forecasts.to_json(orient="records",date_format="iso"))
    return {
        "schema":"qdr.l2.forecast.v1",
        "status":"RESEARCH_ONLY" if eligible else "BLOCKED",
        "code":None if eligible else "NO_ELIGIBLE_STYLE_HORIZON_FORECASTS",
        "asof_session":metadata["asof_date_et"],
        "signal_cutoff_utc":metadata["knowledge_cutoff_utc"],
        "source_snapshot_sha256":metadata["snapshot_sha256"],
        "source":metadata["source"],
        "price_basis":metadata.get("adjustment_basis","yahoo_split_adjusted"),
        "label_bundle_id":label_id,
        "label_bundle_sha256":label_manifest["labels_sha256"],
        "label_source_evidence_sha256":label_manifest["source_evidence_sha256"],
        "feature_bundle_id":feature_id,
        "feature_bundle_sha256":feature_manifest["features_sha256"],
        "feature_source_evidence_sha256":feature_manifest["source_evidence_sha256"],
        "feature_price_basis":feature_manifest["price_basis"],
        "historical_feature_pit_attested":(
            feature_manifest["historical_pit_attested"] is True
        ),
        "forecast_protocol_version":FORECAST_PROTOCOL_VERSION,
        "model_version":MODEL_VERSION,
        "config":{
            "min_training_sessions":config.min_training_sessions,
            "embargo_sessions":config.embargo_sessions,
            "ridge_alpha":config.ridge_alpha,
        },
        "eligible_units":eligible,
        "blocked_units":blocked,
        "forecasts":records,
        "historical_decision_eligible":False,
        "real_orders_enabled":False,
        "limitations":[
            "STYLE_FORECAST_RESEARCH_ONLY",
            "CURRENT_INFERENCE_OBSERVATION_SEPARATE_FROM_PIT_TRAINING_HISTORY",
            "NO_PROBABILITY_CALIBRATION_OR_MODEL_ADMISSION",
            "NO_BROKER_OR_PAPER_ORDER_EXECUTION",
        ],
    }
