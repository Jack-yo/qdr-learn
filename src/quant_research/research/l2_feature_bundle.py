"""Immutable verified historical L2 feature bundles.

The bundle stores only seven-style derived features and source evidence hashes.
It is intentionally not a duplicate OHLC warehouse.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

import pandas as pd

from quant_research.research.l2_features import (
    FEATURE_PROTOCOL_VERSION,
    REQUIRED_FEATURE_PRICE_BASIS,
)
from quant_research.research.l2_forecast import INPUT_FEATURES, STYLE_IDS


BUNDLE_SCHEMA = "qdr.l2.style-feature-bundle.v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _digest(path: Path) -> str:
    h=sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def _bundle_id(value: str) -> str:
    if not isinstance(value,str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}",value
    ):
        raise ValueError("Invalid L2 feature bundle ID")
    return value


def validate_verified_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required={
        "date","style_id","available_at","signal_time",
        "feature_pit_eligible","feature_status",
        "feature_protocol_version","feature_price_basis",
        "action_evidence_version","historical_pit_attested",
        "decision_eligible","real_orders_enabled",
        *INPUT_FEATURES,
    }
    missing=required-set(frame.columns)
    if missing:
        raise ValueError(
            "L2_FEATURE_BUNDLE_COLUMNS_MISSING:"+",".join(sorted(missing))
        )
    data=frame.loc[:,list(required)].copy()
    data["date"]=pd.to_datetime(data["date"],errors="raise").dt.tz_localize(None).dt.normalize()
    data["available_at"]=pd.to_datetime(data["available_at"],utc=True,errors="coerce")
    data["signal_time"]=pd.to_datetime(data["signal_time"],utc=True,errors="coerce")
    if data.duplicated(["date","style_id"]).any():
        raise ValueError("L2_FEATURE_BUNDLE_DUPLICATE_STYLE_SESSION")
    if set(data.style_id)-set(STYLE_IDS):
        raise ValueError("L2_FEATURE_BUNDLE_UNKNOWN_STYLE")
    if set(data.feature_protocol_version)!={FEATURE_PROTOCOL_VERSION}:
        raise ValueError("L2_FEATURE_BUNDLE_PROTOCOL_MISMATCH")
    if set(data.feature_price_basis)!={REQUIRED_FEATURE_PRICE_BASIS}:
        raise ValueError("L2_FEATURE_BUNDLE_PRICE_BASIS_MISMATCH")
    for column in INPUT_FEATURES:
        data[column]=pd.to_numeric(data[column],errors="coerce")
    eligible=data.feature_pit_eligible.eq(True)
    if (
        data.loc[eligible,"feature_status"].ne("VERIFIED_PIT_FEATURE").any()
        or data.loc[eligible,"historical_pit_attested"].ne(True).any()
        or data.loc[eligible,"available_at"].isna().any()
        or data.loc[eligible,"signal_time"].isna().any()
        or data.loc[eligible,"available_at"].gt(
            data.loc[eligible,"signal_time"]
        ).any()
        or data.loc[eligible,list(INPUT_FEATURES)].isna().any().any()
    ):
        raise ValueError("L2_FEATURE_BUNDLE_PIT_EVIDENCE_INVALID")
    if data.decision_eligible.ne(False).any() or data.real_orders_enabled.ne(False).any():
        raise ValueError("L2_FEATURE_BUNDLE_CANNOT_ENABLE_EXECUTION")
    return data.sort_values(["date","style_id"],kind="stable").reset_index(drop=True)


def freeze_feature_bundle_v1(
    root: Path,
    bundle_id: str,
    features: pd.DataFrame,
    *,
    source_evidence_sha256: str,
    action_evidence_version: str,
) -> dict:
    root=Path(root).resolve();bundle_id=_bundle_id(bundle_id)
    if not _SHA.fullmatch(str(source_evidence_sha256)):
        raise ValueError("source_evidence_sha256 must be lowercase SHA256")
    if not isinstance(action_evidence_version,str) or not action_evidence_version.strip():
        raise ValueError("action_evidence_version is required")
    data=validate_verified_feature_frame(features)
    eligible=data.loc[data.feature_pit_eligible.eq(True)]
    if eligible.empty or set(eligible.style_id)!=set(STYLE_IDS):
        raise ValueError("L2_FEATURE_BUNDLE_REQUIRES_ALL_SEVEN_STYLES")
    parent=root/"data/managed/l2_style_features"
    target=parent/bundle_id
    if target.exists():
        raise FileExistsError("L2 feature bundle is immutable and already exists")
    parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix=".l2-feature-",dir=parent))
    try:
        path=temp/"features.parquet"
        data.to_parquet(path,index=False)
        digest=_digest(path)
        per_style={
            style:int(eligible.loc[eligible.style_id.eq(style),"date"].nunique())
            for style in STYLE_IDS
        }
        manifest={
            "schema":BUNDLE_SCHEMA,
            "bundle_id":bundle_id,
            "created_at_utc":datetime.now(timezone.utc).isoformat(),
            "features_path":"features.parquet",
            "features_sha256":digest,
            "source_evidence_sha256":source_evidence_sha256,
            "feature_protocol_version":FEATURE_PROTOCOL_VERSION,
            "price_basis":REQUIRED_FEATURE_PRICE_BASIS,
            "action_evidence_version":action_evidence_version,
            "rows":int(len(data)),
            "eligible_rows":int(len(eligible)),
            "eligible_sessions_by_style":per_style,
            "first_eligible_session":eligible.date.min().date().isoformat(),
            "last_eligible_session":eligible.date.max().date().isoformat(),
            "styles":list(STYLE_IDS),
            "historical_pit_attested":True,
            "decision_eligible":False,
            "real_orders_enabled":False,
        }
        (temp/"manifest.json").write_text(_canonical(manifest),encoding="utf-8")
        temp.rename(target)
    except Exception:
        shutil.rmtree(temp,ignore_errors=True);raise
    return manifest


def load_feature_bundle_v1(
    root: Path,bundle_id: str
) -> tuple[pd.DataFrame,dict]:
    root=Path(root).resolve();bundle_id=_bundle_id(bundle_id)
    folder=root/"data/managed/l2_style_features"/bundle_id
    manifest_path=folder/"manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("L2_FEATURE_BUNDLE_NOT_FOUND")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    required={
        "schema","bundle_id","features_path","features_sha256",
        "source_evidence_sha256","feature_protocol_version","price_basis",
        "action_evidence_version","rows","eligible_rows",
        "eligible_sessions_by_style","styles","historical_pit_attested",
    }
    if required-set(manifest):
        raise ValueError("L2_FEATURE_BUNDLE_MANIFEST_INCOMPLETE")
    if (
        manifest["schema"]!=BUNDLE_SCHEMA
        or manifest["bundle_id"]!=bundle_id
        or manifest["feature_protocol_version"]!=FEATURE_PROTOCOL_VERSION
        or manifest["price_basis"]!=REQUIRED_FEATURE_PRICE_BASIS
        or set(manifest["styles"])!=set(STYLE_IDS)
        or manifest["historical_pit_attested"] is not True
    ):
        raise ValueError("L2_FEATURE_BUNDLE_IDENTITY_MISMATCH")
    path=(folder/manifest["features_path"]).resolve()
    if not path.is_relative_to(folder) or not path.is_file():
        raise ValueError("L2_FEATURE_BUNDLE_PATH_INVALID")
    if _digest(path)!=manifest["features_sha256"]:
        raise ValueError("L2_FEATURE_BUNDLE_HASH_MISMATCH")
    data=validate_verified_feature_frame(pd.read_parquet(path))
    if len(data)!=int(manifest["rows"]):
        raise ValueError("L2_FEATURE_BUNDLE_ROW_COUNT_MISMATCH")
    if int(data.feature_pit_eligible.sum())!=int(manifest["eligible_rows"]):
        raise ValueError("L2_FEATURE_BUNDLE_ELIGIBLE_COUNT_MISMATCH")
    actual={
        style:int(data.loc[
            data.style_id.eq(style)&data.feature_pit_eligible.eq(True),"date"
        ].nunique())
        for style in STYLE_IDS
    }
    if actual!={k:int(v) for k,v in manifest["eligible_sessions_by_style"].items()}:
        raise ValueError("L2_FEATURE_BUNDLE_STYLE_COVERAGE_MISMATCH")
    return data,manifest
