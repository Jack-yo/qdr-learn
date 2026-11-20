"""L3 product-facing Alpha overview assembled from verified existing research evidence.

This module never manufactures a candidate, upgrades research eligibility, or treats
retrospective factor rankings as current forecasts. Daily Alpha scores are calculated
only when the active frozen strategy's exact factor names exist in the exact managed
V4 bundle that produced the frozen forward archive.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.policy import PolicyError
from quant_research.research.composite import compute_composite
from quant_research.research.factor_lab import Registry
from quant_research.research.v4_artifacts import list_research_runs, read_research_run
from quant_research.research.v4_forecast_archive import (
    latest_forward_research, read_research_forecast,
)
from quant_research.workflow.factor_lab import result as factor_result
from quant_research.workflow.l3_strategy_activation import active_strategy
from quant_research.workflow.v4_plan_outcomes import latest_research_outcomes
from quant_research.workflow.v4_study_cli import _checked_inputs


_SCHEMA = "qdr.l3.overview.v1"


def _finite(value):
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def _strategy_summary(record):
    config = record["config"]
    mix = config.get("factor_mix")
    allocations = []
    if mix:
        for item in mix.get("allocations", []):
            dep = item.get("dependency") or {}
            allocations.append({
                "experiment_id": item.get("factor_experiment_id"),
                "factor_name": dep.get("factor_name"),
                "factor_version": dep.get("factor_version"),
                "weight": _finite(item.get("weight")),
            })
    return {
        "id": record["id"], "name": record["name"], "version": record["version"],
        "status": record["status"], "horizon": config["strategy"]["horizon"],
        "config_sha256": record["config_sha256"], "factors": allocations,
        "research_only": True,
    }


def _factor_library(root, horizon):
    registry = Registry(root)
    if not registry.path.is_file():
        return []
    versions = {row["id"]: row for row in registry.factors()}
    rows = []
    for experiment in registry.experiments():
        if experiment.get("status") != "COMPLETED":
            continue
        if (experiment.get("config") or {}).get("source") != "yahoo":
            continue
        try:
            detail = factor_result(root, experiment["id"])
            result = detail["result"]
            summaries = pd.DataFrame(result.get("summary") or [])
            matched = summaries.loc[
                summaries.partition.eq("validation")
                & summaries.horizon.eq(horizon)
            ] if not summaries.empty and {"partition", "horizon"} <= set(summaries) else pd.DataFrame()
            row = matched.iloc[0].to_dict() if len(matched) else {}
            version = versions.get(experiment["factor_version_id"], {})
            rows.append({
                "experiment_id": experiment["id"],
                "factor_version_id": experiment["factor_version_id"],
                "factor_name": version.get("name") or (result.get("factor_version") or {}).get("name"),
                "factor_version": version.get("version") or (result.get("factor_version") or {}).get("version"),
                "horizon": horizon,
                "rank_ic_mean": _finite(row.get("rank_ic_mean")),
                "excess_rank_ic_mean": _finite(row.get("excess_rank_ic_mean")),
                "icir_unannualized": _finite(row.get("icir_unannualized")),
                "label_pair_coverage": _finite(row.get("label_pair_coverage")),
                "daily_ic_count": int(row.get("daily_ic_count") or 0),
                "top_bottom_price_spread": _finite(row.get("q5_minus_q1_price_return_spread")),
                "evidence_status": (
                    "RESEARCH_EVIDENCE_AVAILABLE"
                    if row.get("rank_ic_mean") is not None else "INSUFFICIENT_VALIDATION_EVIDENCE"
                ),
                "historical_pit_verified": False,
                "research_only": True,
            })
        except (PolicyError, ValueError, KeyError, OSError, TypeError):
            continue
    rows.sort(key=lambda item: (
        -(abs(item["rank_ic_mean"]) if item["rank_ic_mean"] is not None else -1),
        str(item["factor_name"] or ""),
    ))
    return rows[:60]


def _matching_bundle(root, input_contract):
    if not isinstance(input_contract, dict):
        return None, None, None
    expected = input_contract.get("artifacts_sha256")
    if not isinstance(expected, dict) or not expected:
        return None, None, None
    base = Path(root).resolve() / "data/managed/v4_inputs"
    if not base.is_dir():
        return None, None, None
    for folder in sorted(base.iterdir(), reverse=True):
        manifest_path = folder / "manifest.json"
        if not folder.is_dir() or not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("artifacts_sha256") != expected:
                continue
            frames, checked = _checked_inputs(Path(root), folder.name)
            return folder.name, frames, checked
        except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError):
            continue
    return None, None, None


def _research_model_evidence(root, factor_names, source_snapshot_sha256, horizon):
    wanted = set(factor_names)
    for row in list_research_runs(root, limit=30):
        if row.get("status") == "CORRUPT_RESEARCH_RUN":
            continue
        try:
            run = read_research_run(root, row["run_id"], include_rows=False)
        except (ValueError, OSError, KeyError, TypeError, FileNotFoundError):
            continue
        manifest = run["manifest"]
        variants = manifest.get("model_variants") or {}
        if (set(variants.get("A") or []) != wanted
                or manifest.get("input_snapshot_sha256") != source_snapshot_sha256):
            continue
        increments = run["increment_vs_alpha_only"]
        selected = "A"
        selection_reason = "ALPHA_ONLY_DEFAULT_NO_PROVEN_CONDITIONAL_INCREMENT"
        increment_row = None
        if not increments.empty and {"horizon", "status"} <= set(increments):
            matched = increments.loc[pd.to_numeric(
                increments.horizon, errors="coerce").eq(horizon)]
            if len(matched):
                increment_row = matched.iloc[0].to_dict()
                if (increment_row.get("status") == "PAIRED_OOS_ESTIMATED"
                        and bool(increment_row.get("probability_gain_ci_excludes_zero"))
                        and bool(increment_row.get("gross_mse_gain_ci_excludes_zero"))
                        and "D" in variants):
                    selected = "D"
                    selection_reason = "FULL_MODEL_PAIRED_OOS_INCREMENT_CONFIRMED"
        ranks = run["alpha_ranking"]
        rank_rows = []
        if not ranks.empty:
            for item in ranks.loc[pd.to_numeric(
                    ranks.horizon, errors="coerce").eq(horizon)].to_dict("records"):
                rank_rows.append({
                    "variant": item.get("variant"),
                    "rank_ic_mean": _finite(item.get("rank_ic_mean")),
                    "rank_icir_unannualized": _finite(item.get("rank_icir_unannualized")),
                    "sessions": int(item.get("sessions") or 0),
                    "status": item.get("status"),
                })
        return {
            "run_id": row["run_id"], "selected_variant": selected,
            "selection_reason": selection_reason,
            "increment_vs_alpha_only": increment_row,
            "alpha_ranking": rank_rows,
            "research_only": True,
        }
    return {
        "run_id": None, "selected_variant": "A",
        "selection_reason": "NO_MATCHED_OOS_INCREMENT_EVIDENCE",
        "increment_vs_alpha_only": None, "alpha_ranking": [],
        "research_only": True,
    }


def _latest_forward(root):
    records = latest_forward_research(root, limit=10)
    prospective = next(
        (row for row in records if row.get("status") == "VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY"),
        None,
    )
    if prospective is None:
        return None, None
    detail = read_research_forecast(
        root, prospective["session_date_et"], prospective["identity"], include_rows=True
    )
    return prospective, detail


def _daily_scores(strategy_record, frames, session_date):
    mix = strategy_record["config"].get("factor_mix")
    if not mix:
        raise PolicyError("L3_MULTI_FACTOR_STRATEGY_REQUIRED",
                          "Daily L3 selection requires a frozen multi-factor Alpha strategy")
    allocations = mix.get("allocations") or []
    names = [(item.get("dependency") or {}).get("factor_name") for item in allocations]
    if not names or any(not name for name in names) or len(set(names)) != len(names):
        raise PolicyError("L3_ACTIVE_FACTOR_NAMES_INVALID",
                          "The active strategy factor names are incomplete or duplicated")
    factors = frames.get("factors")
    required = {"date", "security_id", "feature_name", "value", "decision_eligible"}
    if factors is None or required - set(factors):
        raise PolicyError("L3_CURRENT_FACTOR_FRAME_INVALID",
                          "The exact forward bundle does not contain usable Alpha factor rows")
    current = factors.copy()
    current["date"] = pd.to_datetime(current["date"], errors="raise")
    current = current.loc[
        current.date.eq(pd.Timestamp(session_date))
        & current.feature_name.isin(names)
    ].copy()
    if current.empty:
        raise PolicyError("L3_CURRENT_FACTOR_ROWS_MISSING",
                          "The active Alpha factors are absent from the frozen forward session")
    if not current.decision_eligible.map(
            lambda value: type(value) is bool or type(value).__name__ == "bool").all():
        raise PolicyError("L3_FACTOR_ELIGIBILITY_INVALID",
                          "Current Alpha feature eligibility is malformed")
    if current.decision_eligible.ne(True).any():
        raise PolicyError("L3_CURRENT_FACTORS_NOT_DECISION_ELIGIBLE",
                          "Retrospective Alpha rows cannot be used as today's selection")
    if current.duplicated(["security_id", "feature_name"]).any():
        raise PolicyError("L3_CURRENT_FACTOR_KEYS_DUPLICATED",
                          "Current Alpha factors contain duplicate security/feature rows")
    current["value"] = pd.to_numeric(current["value"], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    wide = current.pivot(index="security_id", columns="feature_name", values="value")
    missing = set(names) - set(wide.columns)
    if missing:
        raise PolicyError("L3_ACTIVE_FACTORS_NOT_IN_FORWARD_BUNDLE",
                          "The active strategy is not represented by the current forward feature bundle",
                          sorted(missing))
    wide = wide.dropna(subset=names)
    if wide.empty:
        return pd.DataFrame(), names
    ranked = wide[names].rank(method="average", pct=True)
    weights = {((item.get("dependency") or {}).get("factor_name")): float(item["weight"])
               for item in allocations}
    score = sum(ranked[name] * weights[name] for name in names)
    output = ranked.copy()
    output["alpha_score"] = score
    output["alpha_rank_pct"] = score.rank(method="average", pct=True)
    output = output.reset_index()
    for name in names:
        output["contribution__" + name] = output[name] * weights[name]
    return output, names


def _candidate_metadata(frames, session_date):
    meta = frames.get("candidate_meta")
    if meta is None or meta.empty or "security_id" not in meta:
        return pd.DataFrame(columns=["security_id"])
    current = meta.copy()
    if "date" in current:
        current["date"] = pd.to_datetime(current["date"], errors="raise")
        current = current.loc[current.date.eq(pd.Timestamp(session_date))]
    if current.duplicated(["security_id"]).any():
        raise PolicyError("L3_CANDIDATE_METADATA_DUPLICATED",
                          "Candidate metadata contains duplicate security identities")
    return current


def _build_candidates(scores, factor_names, meta, forecasts, variant, horizon, limit):
    if scores.empty:
        return []
    ranked = scores.loc[scores.alpha_rank_pct.ge(.80)].sort_values(
        ["alpha_score", "security_id"], ascending=[False, True]
    )
    if not meta.empty:
        columns = [name for name in (
            "security_id", "symbol", "sector", "reference_close", "atr20", "adv20"
        ) if name in meta]
        ranked = ranked.merge(meta[columns], on="security_id", how="left",
                              validate="one_to_one")
    forecast = forecasts.loc[
        forecasts.horizon.eq(horizon)
        & forecasts.model_variant.eq(variant)
    ].copy() if not forecasts.empty else pd.DataFrame()
    if not forecast.empty:
        if forecast.duplicated(["security_id", "horizon"]).any():
            raise PolicyError("L3_FORWARD_FORECAST_KEYS_DUPLICATED",
                              "Frozen forecast has duplicate security/horizon rows")
        keep = [name for name in (
            "security_id", "expected_gross_trade_return", "expected_excess_return",
            "p_up", "p_downside", "probability_status_up",
            "probability_status_downside", "model_version",
        ) if name in forecast]
        ranked = ranked.merge(forecast[keep], on="security_id", how="left",
                              validate="one_to_one")
    output = []
    for row in ranked.head(limit).to_dict("records"):
        contributions = {
            name: _finite(row.get("contribution__" + name)) for name in factor_names
        }
        primary = sorted(
            ({"factor_name": name, "contribution": value}
             for name, value in contributions.items() if value is not None),
            key=lambda item: (-item["contribution"], item["factor_name"]),
        )[:3]
        output.append({
            "security_id": str(row["security_id"]),
            "symbol": row.get("symbol") or str(row["security_id"]),
            "sector": row.get("sector"),
            "alpha_score": _finite(row.get("alpha_score")),
            "alpha_rank_pct": _finite(row.get("alpha_rank_pct")),
            "factor_percentiles": {
                name: _finite(row.get(name)) for name in factor_names
            },
            "factor_contributions": contributions,
            "primary_factors": primary,
            "expected_gross_return": _finite(row.get("expected_gross_trade_return")),
            "expected_excess_return": _finite(row.get("expected_excess_return")),
            "p_up": _finite(row.get("p_up")),
            "p_downside": _finite(row.get("p_downside")),
            "probability_status_up": row.get("probability_status_up"),
            "probability_status_downside": row.get("probability_status_downside"),
            "model_variant": variant if row.get("model_version") else None,
            "model_version": row.get("model_version"),
            "reference_close": _finite(row.get("reference_close")),
            "atr20": _finite(row.get("atr20")),
            "adv20": _finite(row.get("adv20")),
            "research_only": True,
        })
    return output


def l3_overview(root, *, horizon=3, limit=20):
    if horizon not in (1, 3, 5) or type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("L3 overview supports H1/H3/H5 and limit 1–50")
    root = Path(root).resolve()
    blockers = []
    factor_library = _factor_library(root, horizon)
    activation = active_strategy(root)
    active = activation.get("strategy")
    strategy = _strategy_summary(active) if active else None

    strategies = []
    try:
        from quant_research.research.strategy import StrategyRegistry
        strategies = [_strategy_summary(item) for item in StrategyRegistry(root).versions()]
    except (PolicyError, ValueError, OSError):
        blockers.append("STRATEGY_REGISTRY_UNAVAILABLE")

    forward_index, forward = _latest_forward(root)
    if forward is None:
        blockers.append("NO_PROSPECTIVE_FORWARD_FORECAST")
        return {
            "schema": _SCHEMA, "status": "WATCH_ONLY",
            "horizon": horizon, "active_strategy": strategy,
            "strategies": strategies, "factor_library": factor_library,
            "daily": None, "candidates": [], "model_evidence": None,
            "validation": None,
            "outcomes": latest_research_outcomes(root, limit=10).get("records", []),
            "blockers": blockers + (
                ["NO_ACTIVE_ALPHA_STRATEGY"] if active is None else []
            ),
            "research_only": True, "execution_ready": False,
            "real_orders_enabled": False,
        }

    manifest = forward["manifest"]
    contract = manifest.get("input_contract") or {}
    session = manifest["session_date_et"]
    bundle_id, frames, bundle_manifest = _matching_bundle(root, contract)
    if frames is None:
        blockers.append("FROZEN_FORWARD_INPUT_BUNDLE_NOT_FOUND")

    active_names = [item["factor_name"] for item in strategy["factors"]] if strategy else []
    forecast_names = contract.get("factor_names") or []
    if active is None:
        blockers.append("NO_ACTIVE_ALPHA_STRATEGY")

    # Product pages read a write-once T-day Alpha ranking. GET never recalculates
    # current selection from mutable files merely to make the page look populated.
    scores = pd.DataFrame()
    factor_names = active_names
    daily_manifest = None
    if active is not None:
        from quant_research.workflow.l3_daily import latest_l3_daily, read_l3_daily
        records = latest_l3_daily(root, limit=30)
        match = next((row for row in records
                      if row.get("status") != "CORRUPT_L3_DAILY_ALPHA_ARCHIVE"
                      and row.get("session_date_et") == session
                      and row.get("strategy_version_id") == active["id"]
                      and row.get("strategy_config_sha256") == active["config_sha256"]
                      and row.get("source_snapshot_sha256") == manifest["source_snapshot_sha256"]), None)
        if match is None:
            blockers.append("NO_FROZEN_L3_DAILY_SELECTION")
        else:
            try:
                daily_snapshot = read_l3_daily(
                    root, match["session_date_et"], match["identity"], include_scores=True)
                daily_manifest = daily_snapshot["manifest"]
                scores = daily_snapshot["scores"]
                factor_names = list(daily_manifest.get("factor_names") or [])
                bundle_id = daily_manifest.get("bundle_id") or bundle_id
            except (OSError, ValueError, KeyError, TypeError, FileNotFoundError):
                blockers.append("FROZEN_L3_DAILY_SELECTION_INVALID")

    same_factor_set = (bool(active_names) and bool(factor_names)
                       and set(active_names) == set(factor_names)
                       and set(active_names) == set(forecast_names))
    if active is not None and not same_factor_set:
        blockers.append("ACTIVE_STRATEGY_FORECAST_FACTOR_SET_MISMATCH")

    evidence = _research_model_evidence(
        root, active_names if same_factor_set else forecast_names,
        manifest["source_snapshot_sha256"], horizon,
    )
    variant = evidence["selected_variant"] if same_factor_set else "A"
    forecasts = forward["forecasts"].copy()
    forecasts["horizon"] = pd.to_numeric(forecasts["horizon"], errors="coerce")
    if not same_factor_set:
        forecasts = forecasts.iloc[:0]
    candidates = _build_candidates(
        scores, factor_names, pd.DataFrame(columns=["security_id"]),
        forecasts, variant, horizon, limit
    )

    validation = None
    if active is not None and active["config"].get("factor_mix"):
        try:
            composite = compute_composite(root, active["id"])
            validation = {
                "status": composite["status"],
                "validation_rank_ic_mean": _finite(composite.get("validation_rank_ic_mean")),
                "validation_daily_ic_count": int(composite.get("validation_daily_ic_count") or 0),
                "redundancy_warning_count": int(composite.get("redundancy_warning_count") or 0),
                "factor_correlations": composite.get("factor_correlations") or [],
                "retrospective_only": True,
            }
        except (PolicyError, ValueError, KeyError, OSError, TypeError):
            blockers.append("ACTIVE_STRATEGY_RETROSPECTIVE_VALIDATION_UNAVAILABLE")

    status = (
        "ALPHA_CANDIDATES_RESEARCH_ONLY" if candidates
        else "NO_QUALIFIED_ALPHA_CANDIDATES"
        if scores is not None and not scores.empty
        else "WATCH_ONLY"
    )
    return {
        "schema": _SCHEMA, "status": status, "horizon": horizon,
        "active_strategy": strategy, "strategies": strategies,
        "factor_library": factor_library,
        "daily": {
            "session_date_et": session,
            "forecast_identity": forward_index["identity"],
            "forecast_status": forward_index["status"],
            "bundle_id": bundle_id,
            "source_snapshot_sha256": manifest["source_snapshot_sha256"],
            "observed_security_count": int(
                daily_manifest.get("observed_security_count") or 0
            ) if daily_manifest else 0,
            "complete_alpha_score_count": int(len(scores)),
            "candidate_count": len(candidates),
            "active_factor_names": factor_names,
            "forecast_factor_names": list(forecast_names),
            "selected_model_variant": variant if same_factor_set else None,
            "model_selection_reason": evidence["selection_reason"] if same_factor_set else None,
            "input_bundle_verified": bundle_manifest is not None,
            "daily_alpha_frozen": daily_manifest is not None,
        },
        "candidates": candidates,
        "model_evidence": evidence if same_factor_set else None,
        "validation": validation,
        "outcomes": latest_research_outcomes(root, limit=10).get("records", []),
        "blockers": list(dict.fromkeys(blockers)),
        "research_only": True, "execution_ready": False,
        "real_orders_enabled": False,
    }
