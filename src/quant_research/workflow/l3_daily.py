"""Immutable daily L3 Alpha ranking snapshots.

Two admitted inputs are supported:
1) a strict V4 source-hashed model bundle; or
2) an audited current-session L3 factor snapshot.

Both produce the same write-once Alpha ranking contract. Neither path creates
future-return labels, orders, paper fills, or execution eligibility.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

import pandas as pd

from quant_research.policy import PolicyError
from quant_research.workflow.l3_strategy_activation import active_strategy
from quant_research.workflow.l3_overview import _daily_scores
from quant_research.workflow.v4_pipeline_preflight import preflight_v4_day
from quant_research.workflow.v4_study_cli import _checked_inputs


_ROOT = Path("outputs/l3_daily")
_ID = re.compile(r"[a-f0-9]{16}\Z")
_SCHEMA = "qdr.l3.daily-alpha.v1"


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(path):
    return sha256(path.read_bytes()).hexdigest()


def _location(root, day, identity):
    try:
        stamp = pd.Timestamp(day)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid L3 daily session") from exc
    if stamp.tzinfo is not None or stamp.date().isoformat() != str(day):
        raise ValueError("Invalid L3 daily session")
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError("Invalid L3 daily identity")
    base = Path(root).resolve() / _ROOT
    folder = (base / str(day) / identity).resolve()
    if not folder.is_relative_to(base.resolve()):
        raise ValueError("L3 daily path escaped archive")
    return base, folder


def _active(root):
    activation = active_strategy(root)
    strategy = activation.get("strategy")
    if strategy is None:
        raise PolicyError(
            "NO_ACTIVE_ALPHA_STRATEGY",
            "Activate a frozen multi-factor strategy before the daily L3 run",
        )
    if not strategy["config"].get("factor_mix"):
        raise PolicyError(
            "L3_MULTI_FACTOR_STRATEGY_REQUIRED",
            "Daily L3 requires a frozen 2–8 factor strategy",
        )
    return strategy


def _factor_names(strategy):
    allocations = strategy["config"]["factor_mix"].get("allocations") or []
    names = [(row.get("dependency") or {}).get("factor_name") for row in allocations]
    if not names or any(not name for name in names) or len(set(names)) != len(names):
        raise PolicyError("L3_ACTIVE_FACTOR_NAMES_INVALID",
                          "Active strategy factor names are incomplete or duplicated")
    return names, allocations


def _score_frames(strategy, frames, session_date):
    scores, factor_names = _daily_scores(strategy, frames, session_date)
    if scores.empty:
        raise PolicyError(
            "NO_COMPLETE_CURRENT_ALPHA_SCORES",
            "No security has the complete active factor set for the current session",
        )
    metadata = frames.get("candidate_meta")
    if metadata is not None and not metadata.empty:
        meta = metadata.copy()
        if "date" in meta:
            meta["date"] = pd.to_datetime(meta["date"], errors="raise")
            meta = meta.loc[meta.date.eq(pd.Timestamp(session_date))]
        if meta.duplicated("security_id").any():
            raise PolicyError(
                "L3_CANDIDATE_METADATA_DUPLICATED",
                "Current candidate metadata contains duplicate security identities",
            )
        keep = [
            name for name in (
                "security_id", "symbol", "sector", "reference_close",
                "atr20", "adv20", "available_at"
            ) if name in meta
        ]
        scores = scores.merge(
            meta[keep], on="security_id", how="left", validate="one_to_one"
        )
    return scores, factor_names


def _identity(day, strategy, manifest, input_kind, input_id):
    value = {
        "schema": _SCHEMA,
        "session_date_et": day,
        "strategy_version_id": strategy["id"],
        "strategy_config_sha256": strategy["config_sha256"],
        "source_snapshot_sha256": manifest["source_snapshot_sha256"],
        "input_artifacts_sha256": manifest["artifacts_sha256"],
        "input_kind": input_kind,
        "input_id": input_id,
    }
    return sha256(_canonical(value).encode()).hexdigest()[:16]


def _freeze(root, *, session_date, strategy, frames, input_manifest,
            input_kind, input_id):
    factor_names_expected, allocations = _factor_names(strategy)
    input_names = input_manifest.get("factor_names") or []
    if set(factor_names_expected) != set(input_names):
        raise PolicyError(
            "ACTIVE_STRATEGY_FORECAST_FACTOR_SET_MISMATCH",
            "The active factor strategy does not exactly match the current factor input",
        )
    artifacts = input_manifest.get("artifacts_sha256")
    source_sha = input_manifest.get("source_snapshot_sha256")
    if not isinstance(artifacts, dict) or not artifacts or not isinstance(source_sha, str):
        raise PolicyError("L3_DAILY_SOURCE_MISMATCH",
                          "Current Alpha input lacks source-hashed artifacts")

    scores, factor_names = _score_frames(strategy, frames, session_date)
    identity = _identity(
        session_date, strategy, input_manifest, input_kind, input_id
    )
    _, folder = _location(root, session_date, identity)
    if folder.is_dir():
        return {
            **read_l3_daily(root, session_date, identity, include_scores=False),
            "status": "L3_DAILY_ALPHA_ALREADY_FROZEN",
        }

    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".writing-", dir=folder.parent
    ) as temporary:
        work = Path(temporary)
        scores_path = work / "scores.parquet"
        scores.to_parquet(scores_path, index=False)
        manifest_out = {
            "schema": _SCHEMA,
            "identity": identity,
            "session_date_et": session_date,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "strategy_version_id": strategy["id"],
            "strategy_name": strategy["name"],
            "strategy_version": strategy["version"],
            "strategy_config_sha256": strategy["config_sha256"],
            "input_kind": input_kind,
            "input_id": input_id,
            "bundle_id": input_id if input_kind == "V4_STRICT_BUNDLE" else None,
            "factor_snapshot_identity": (
                input_id if input_kind == "CURRENT_FACTOR_SNAPSHOT" else None
            ),
            "source_snapshot_sha256": source_sha,
            "input_artifacts_sha256": artifacts,
            "factor_names": factor_names,
            "factor_weights": {
                (row.get("dependency") or {}).get("factor_name"): float(row["weight"])
                for row in allocations
            },
            "observed_security_count": int(
                frames["candidate_meta"].security_id.nunique()
                if "candidate_meta" in frames else scores.security_id.nunique()
            ),
            "complete_alpha_score_count": int(len(scores)),
            "score_artifact_sha256": _digest(scores_path),
            "ranking_rule": "WEIGHTED_DAILY_CROSS_SECTIONAL_PERCENTILE_RANK",
            "candidate_threshold_rank_pct": .80,
            "research_only": True,
            "historical_pit_attested": False,
            "decision_eligible": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
        }
        manifest_out["content_sha256"] = sha256(
            _canonical(manifest_out).encode()
        ).hexdigest()
        (work / "manifest.json").write_text(
            json.dumps(
                manifest_out, ensure_ascii=False, sort_keys=True,
                indent=2, allow_nan=False
            ),
            encoding="utf-8",
        )
        if folder.exists():
            raise FileExistsError("Concurrent L3 daily archive exists")
        work.rename(folder)
    return read_l3_daily(root, session_date, identity, include_scores=False)


def freeze_l3_daily(root, *, session_date, bundle_id, admitted=None):
    """Freeze from the strict V4 model bundle after its independent preflight."""
    root = Path(root).resolve()
    evidence = admitted or preflight_v4_day(root, session_date, bundle_id)
    if evidence.get("status") != "PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY":
        raise PolicyError(
            "L3_DAILY_PREFLIGHT_REQUIRED",
            "L3 daily Alpha may only freeze after current source/time/cohort preflight",
        )
    strategy = _active(root)
    frames, manifest = _checked_inputs(root, bundle_id)
    if manifest.get("source_snapshot_sha256") != evidence.get(
        "source_snapshot_sha256"
    ):
        raise PolicyError(
            "L3_DAILY_SOURCE_MISMATCH",
            "The Alpha bundle differs from the admitted source snapshot",
        )
    return _freeze(
        root, session_date=session_date, strategy=strategy, frames=frames,
        input_manifest=manifest, input_kind="V4_STRICT_BUNDLE",
        input_id=bundle_id,
    )


def freeze_l3_current(root, *, session_date, factor_snapshot_identity):
    """Freeze Alpha-only ranking from the audited prospective current factor path."""
    from quant_research.workflow.l3_current_factors import (
        read_current_factor_snapshot,
    )

    root = Path(root).resolve()
    strategy = _active(root)
    snapshot = read_current_factor_snapshot(
        root, session_date, factor_snapshot_identity, include_frames=True
    )
    manifest = snapshot["manifest"]
    if (manifest.get("strategy_version_id") != strategy["id"]
            or manifest.get("strategy_config_sha256") != strategy["config_sha256"]):
        raise PolicyError(
            "L3_FACTOR_SNAPSHOT_STRATEGY_MISMATCH",
            "Current factor snapshot belongs to a different Alpha strategy version",
        )
    frames = {
        "factors": snapshot["factors"],
        "candidate_meta": snapshot["candidate_meta"],
    }
    return _freeze(
        root, session_date=session_date, strategy=strategy, frames=frames,
        input_manifest=manifest, input_kind="CURRENT_FACTOR_SNAPSHOT",
        input_id=factor_snapshot_identity,
    )


def read_l3_daily(root, session_date, identity, *, include_scores=False):
    _, folder = _location(root, session_date, identity)
    path = folder / "manifest.json"
    scores_path = folder / "scores.parquet"
    if not path.is_file() or not scores_path.is_file():
        raise FileNotFoundError("L3 daily Alpha snapshot unavailable")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    digest = manifest.pop("content_sha256", None)
    if (manifest.get("schema") != _SCHEMA
            or manifest.get("identity") != identity
            or manifest.get("session_date_et") != session_date
            or manifest.get("research_only") is not True
            or manifest.get("decision_eligible") is not False
            or manifest.get("execution_eligible") is not False
            or manifest.get("real_orders_enabled") is not False
            or not isinstance(digest, str)
            or digest != sha256(_canonical(manifest).encode()).hexdigest()
            or manifest.get("score_artifact_sha256") != _digest(scores_path)):
        raise ValueError("L3 daily Alpha archive failed integrity validation")
    manifest["content_sha256"] = digest
    output = {
        "status": "FROZEN_L3_DAILY_ALPHA_RESEARCH_ONLY",
        "manifest": manifest,
        "real_orders_enabled": False,
    }
    if include_scores:
        scores = pd.read_parquet(scores_path)
        required = {"security_id", "alpha_score", "alpha_rank_pct"}
        if required - set(scores) or scores.security_id.duplicated().any():
            raise ValueError("L3 daily Alpha score artifact is invalid")
        output["scores"] = scores
    return output


def latest_l3_daily(root, *, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("L3 daily archive limit must be 1–50")
    base = Path(root).resolve() / _ROOT
    records = []
    if not base.is_dir():
        return records
    for day in sorted(base.iterdir(), reverse=True):
        if not day.is_dir():
            continue
        for folder in sorted(day.iterdir(), reverse=True):
            if not folder.is_dir() or not _ID.fullmatch(folder.name):
                continue
            try:
                item = read_l3_daily(
                    root, day.name, folder.name, include_scores=False
                )
                manifest = item["manifest"]
                records.append({
                    "session_date_et": day.name,
                    "identity": folder.name,
                    "status": item["status"],
                    "strategy_version_id": manifest["strategy_version_id"],
                    "strategy_config_sha256": manifest["strategy_config_sha256"],
                    "source_snapshot_sha256": manifest["source_snapshot_sha256"],
                    "input_kind": manifest.get("input_kind"),
                    "input_id": manifest.get("input_id"),
                    "bundle_id": manifest.get("bundle_id"),
                    "factor_snapshot_identity": manifest.get(
                        "factor_snapshot_identity"
                    ),
                    "complete_alpha_score_count": manifest[
                        "complete_alpha_score_count"
                    ],
                })
            except (OSError, ValueError, KeyError, TypeError, FileNotFoundError):
                records.append({
                    "session_date_et": day.name,
                    "identity": folder.name,
                    "status": "CORRUPT_L3_DAILY_ALPHA_ARCHIVE",
                })
            if len(records) >= limit:
                return records
    return records
