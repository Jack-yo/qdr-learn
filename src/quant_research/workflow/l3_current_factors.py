"""Build an immutable current-session L3 factor snapshot from audited feature prices.

This workflow is deliberately Alpha-only. It can support a genuine forward
cross-sectional ranking before a separately admitted historical Alpha model
exists, but it never fabricates H1/H3/H5 returns or execution eligibility.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import tempfile

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.features.context import make_context
from quant_research.features.engine import compute_features
from quant_research.policy import PolicyError
from quant_research.research.factor_lab import (
    FactorSpec, Registry, template_factor,
)
from quant_research.workflow.l3_strategy_activation import active_strategy


_ROOT = Path("outputs/l3_factor_snapshots")
_FEATURE_ROOT = Path("outputs/feature_prices")
_SCHEMA = "qdr.l3.current-factor-snapshot.v1"
_ID = re.compile(r"[a-f0-9]{16}\Z")
_RUN = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def _feature_run(root, session_date, run_id=None):
    base = Path(root).resolve() / _FEATURE_ROOT
    candidates = []
    if run_id is not None:
        if not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
            raise ValueError("Invalid feature-price run ID")
        candidates = [base / run_id]
    elif base.is_dir():
        candidates = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    for folder in candidates:
        manifest_path = folder / "manifest.json"
        prices_path = folder / "feature_prices.parquet"
        if not manifest_path.is_file() or not prices_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            artifacts = manifest.get("artifacts_sha256") or {}
            strict_normalization = (
                manifest.get("status") == "NORMALIZATION_VERIFIED_CURRENT_VINTAGE"
                and manifest.get("adjustment_basis") == "split_adjusted_price_proxy"
                and (manifest.get("reference_comparison") or {}).get("status") == "PASS"
            )
            vendor_forward = (
                manifest.get("status")
                == "FORWARD_VENDOR_SPLIT_FEATURES_VERIFIED_CURRENT_VINTAGE"
                and manifest.get("purpose") == "l3-forward"
                and manifest.get("adjustment_basis")
                    == "vendor_split_adjusted_price_proxy"
                and (manifest.get("reference_comparison") or {}).get("status")
                    == "NOT_APPLICABLE_DIRECT_VENDOR_SOURCE"
                and manifest.get("research_only") is True
                and manifest.get("execution_ready") is False
                and manifest.get("real_orders_enabled") is False
                and isinstance(manifest.get("vendor_source_provenance"), dict)
                and int((manifest.get("vendor_source_provenance") or {}).get(
                    "verified_pages", 0)) > 0
            )
            if ((not strict_normalization and not vendor_forward)
                    or manifest.get("source") != "ALPACA"
                    or manifest.get("feed") != "sip"
                    or manifest.get("anchor_date_et") != session_date
                    or artifacts.get("feature_prices.parquet") != _file_hash(prices_path)):
                continue
            return folder.name, manifest, prices_path
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue
    raise PolicyError(
        "L3_AUDITED_FEATURE_PRICE_RUN_MISSING",
        "No verified split-adjusted feature-price run matches the requested L3 session",
        [session_date],
    )


class _SnapshotClock:
    """Use the audited current knowledge cutoff as the T-day research signal."""

    def __init__(self, base, session, cutoff):
        self.base = base
        self.calendar = base.calendar
        self.session_date = base.session(session)
        self.cutoff = pd.Timestamp(cutoff)
        if self.cutoff.tzinfo is None:
            raise ValueError("L3 feature cutoff must be timezone-aware")
        self.cutoff = self.cutoff.tz_convert("UTC")

    def signal(self, day, now=None):
        session = self.base.session(day)
        if session == self.session_date:
            return self.cutoff.to_pydatetime()
        return self.base.signal(day, now=self.cutoff.to_pydatetime())


def _active_factors(root, strategy):
    mix = strategy["config"].get("factor_mix") or {}
    allocations = mix.get("allocations") or []
    if not 2 <= len(allocations) <= 8:
        raise PolicyError(
            "L3_MULTI_FACTOR_STRATEGY_REQUIRED",
            "Current L3 factor snapshot requires an active 2–8 factor strategy",
        )
    registry = Registry(root)
    factors = []
    names = []
    for allocation in allocations:
        dependency = allocation.get("dependency") or {}
        version_id = dependency.get("factor_version_id")
        version = registry.factor(version_id)
        if (version["config_sha256"] != dependency.get("factor_sha256")
                or version["name"] != dependency.get("factor_name")):
            raise PolicyError(
                "L3_FACTOR_DEFINITION_CHANGED",
                "The active strategy no longer matches its immutable factor definition",
            )
        spec = FactorSpec.model_validate(version["config"])
        factor = template_factor(spec, version["config_sha256"])
        if factor.name in names:
            raise PolicyError("L3_DUPLICATE_FACTOR_NAME",
                              "Active factors must have unique names")
        names.append(factor.name)
        factors.append(factor)
    return factors, names


def _current_liquidity(context, session):
    day = pd.Timestamp(session)
    close = context.close
    volume = context.panels["volume"]
    adv = (close * volume).rolling(20, min_periods=20).mean()
    prev = close.shift(1)
    high, low = context.panels["high"], context.panels["low"]
    tr = pd.DataFrame(
        np.maximum.reduce([
            (high - low).to_numpy(dtype=float),
            (high - prev).abs().to_numpy(dtype=float),
            (low - prev).abs().to_numpy(dtype=float),
        ]),
        index=close.index, columns=close.columns,
    )
    atr = tr.rolling(20, min_periods=20).mean()
    if day not in close.index:
        raise PolicyError("L3_FEATURE_SESSION_MISSING",
                          "Audited feature prices do not contain the requested session")
    return close.loc[day], adv.loc[day], atr.loc[day]



def _feature_source_snapshot(manifest):
    digest = manifest.get("feature_source_snapshot_sha256") or manifest.get(
        "raw_snapshot_sha256"
    )
    if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise PolicyError(
            "L3_FEATURE_SOURCE_SNAPSHOT_INVALID",
            "Feature-price evidence has no valid source snapshot digest",
        )
    return digest


def _snapshot_identity(session_date, strategy, feature_manifest):
    payload = {
        "schema": _SCHEMA,
        "session_date_et": session_date,
        "strategy_version_id": strategy["id"],
        "strategy_config_sha256": strategy["config_sha256"],
        "source_snapshot_sha256": _feature_source_snapshot(feature_manifest),
        "raw_snapshot_sha256": feature_manifest["raw_snapshot_sha256"],
        "feature_snapshot_sha256": feature_manifest["feature_snapshot_sha256"],
        "knowledge_cutoff_utc": feature_manifest["knowledge_cutoff_utc"],
    }
    return sha256(_canonical(payload).encode()).hexdigest()[:16]


def build_current_factor_snapshot(root, *, session_date, feature_run_id=None):
    root = Path(root).resolve()
    activation = active_strategy(root)
    strategy = activation.get("strategy")
    if strategy is None:
        raise PolicyError("NO_ACTIVE_ALPHA_STRATEGY",
                          "Activate a frozen Alpha strategy before calculating current factors")

    run_id, feature_manifest, prices_path = _feature_run(
        root, session_date, feature_run_id
    )
    clock = TradingClock()
    cutoff = pd.Timestamp(feature_manifest["knowledge_cutoff_utc"])
    if cutoff.tzinfo is None:
        raise PolicyError("L3_FEATURE_CUTOFF_INVALID",
                          "Feature-price audit has no timezone-aware knowledge cutoff")
    cutoff = cutoff.tz_convert("UTC")
    base_signal = pd.Timestamp(clock.signal(session_date, now=cutoff.to_pydatetime()))
    entry = pd.Timestamp(clock.window(session_date, 1, now=cutoff.to_pydatetime()).entry_time)
    if not base_signal <= cutoff < entry:
        raise PolicyError(
            "L3_FEATURE_SNAPSHOT_NOT_PROSPECTIVE",
            "Current Alpha factors must be frozen after the close signal and before next-session entry",
        )

    prices = pd.read_parquet(prices_path)
    required = {
        "date", "security_id", "symbol", "open", "high", "low", "close",
        "volume", "available_at", "source", "feed", "adjustment_basis", "raw_sha256",
    }
    if required - set(prices):
        raise PolicyError("L3_FEATURE_PRICE_SCHEMA_INVALID",
                          "Audited feature-price artifact is missing required columns")
    prices["date"] = pd.to_datetime(prices["date"])
    if prices.duplicated(["date", "security_id"]).any():
        raise PolicyError("L3_FEATURE_PRICE_KEYS_DUPLICATED",
                          "Audited feature prices contain duplicate security/date rows")
    if "SPY" not in set(prices.symbol):
        raise PolicyError("L3_BENCHMARK_MISSING",
                          "The current L3 factor universe must include SPY")

    initial_context = make_context(
        prices, clock, "SPY", prices.date.min(), pd.Timestamp(session_date)
    )
    current_close, current_adv, current_atr = _current_liquidity(
        initial_context, session_date
    )
    protocol = strategy["config"]["protocol"]
    minimum_price = float(protocol["minimum_price"])
    minimum_adv = float(protocol["minimum_adv20"])
    symbols = initial_context.symbols
    eligible_ids = []
    for security_id in current_close.index:
        symbol = symbols.get(security_id)
        price = current_close.get(security_id)
        adv = current_adv.get(security_id)
        if symbol in {"SPY", "HYG", "LQD"}:
            continue
        if (price is None or adv is None or not math.isfinite(float(price))
                or not math.isfinite(float(adv))
                or float(price) < minimum_price or float(adv) < minimum_adv):
            continue
        eligible_ids.append(security_id)
    if len(eligible_ids) < 5:
        raise PolicyError(
            "L3_CURRENT_UNIVERSE_TOO_SMALL",
            "Fewer than five securities pass the current price/liquidity gate",
            [f"eligible={len(eligible_ids)}"],
        )

    benchmark_id = initial_context.benchmark_id
    selected_ids = set(eligible_ids) | {benchmark_id}
    selected_prices = prices.loc[prices.security_id.isin(selected_ids)].copy()
    snapshot_clock = _SnapshotClock(clock, session_date, cutoff)
    context = make_context(
        selected_prices, snapshot_clock, "SPY",
        selected_prices.date.min(), pd.Timestamp(session_date)
    )
    factor_objects, factor_names = _active_factors(root, strategy)
    features = compute_features(
        context, snapshot_clock, factor_objects, "strict", ["SPY"]
    )
    current = features.loc[pd.to_datetime(features.date).eq(
        pd.Timestamp(session_date))].copy()
    if current.empty:
        raise PolicyError("L3_CURRENT_FACTOR_ROWS_MISSING",
                          "No active factor values exist for the requested session")
    current = current.loc[current.security_id.isin(eligible_ids)]
    if current.empty or not current.decision_eligible.any():
        raise PolicyError(
            "L3_CURRENT_FACTORS_NOT_KNOWN_BY_CUTOFF",
            "Current factor inputs were not fully observed by the frozen L3 cutoff",
        )

    pivot = current.loc[current.decision_eligible].pivot(
        index="security_id", columns="feature_name", values="value"
    )
    complete_ids = pivot.dropna(subset=factor_names).index
    current = current.loc[
        current.security_id.isin(complete_ids)
        & current.feature_name.isin(factor_names)
    ].copy()
    if len(complete_ids) < 5:
        raise PolicyError(
            "L3_COMPLETE_FACTOR_COHORT_TOO_SMALL",
            "Fewer than five securities have the complete active factor set",
            [f"complete={len(complete_ids)}"],
        )

    current_day = selected_prices.loc[
        selected_prices.date.eq(pd.Timestamp(session_date))
        & selected_prices.security_id.isin(complete_ids)
    ].copy()
    availability = current.groupby("security_id").available_at.max()
    metadata = []
    for row in current_day.itertuples(index=False):
        sid = row.security_id
        metadata.append({
            "date": pd.Timestamp(session_date),
            "security_id": sid,
            "symbol": row.symbol,
            "sector": None,
            "reference_close": float(row.close),
            "atr20": (
                float(current_atr.get(sid))
                if pd.notna(current_atr.get(sid)) else None
            ),
            "adv20": (
                float(current_adv.get(sid))
                if pd.notna(current_adv.get(sid)) else None
            ),
            "available_at": pd.Timestamp(availability.loc[sid]),
            "source_snapshot_sha256": _feature_source_snapshot(feature_manifest),
        })
    candidate_meta = pd.DataFrame(metadata)

    identity = _snapshot_identity(session_date, strategy, feature_manifest)
    folder = root / _ROOT / session_date / identity
    if folder.is_dir():
        return read_current_factor_snapshot(
            root, session_date, identity, include_frames=False
        )
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".writing-", dir=folder.parent) as temp:
        work = Path(temp)
        current.to_parquet(work / "factors.parquet", index=False)
        candidate_meta.to_parquet(work / "candidate_meta.parquet", index=False)
        artifacts = {
            name: _file_hash(work / name)
            for name in ("factors.parquet", "candidate_meta.parquet")
        }
        manifest = {
            "schema": _SCHEMA,
            "identity": identity,
            "session_date_et": session_date,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "knowledge_cutoff_utc": cutoff.isoformat(),
            "base_signal_time_utc": base_signal.isoformat(),
            "next_entry_time_utc": entry.isoformat(),
            "strategy_version_id": strategy["id"],
            "strategy_config_sha256": strategy["config_sha256"],
            "feature_price_run_id": run_id,
            "feature_price_status": feature_manifest["status"],
            "feature_adjustment_basis": feature_manifest["adjustment_basis"],
            "raw_snapshot_sha256": feature_manifest["raw_snapshot_sha256"],
            "feature_snapshot_sha256": feature_manifest["feature_snapshot_sha256"],
            "source_snapshot_sha256": _feature_source_snapshot(feature_manifest),
            "factor_names": factor_names,
            "source_symbols": sorted(set(selected_prices.symbol)),
            "liquidity_eligible_count": len(eligible_ids),
            "complete_factor_security_count": len(complete_ids),
            "security_type_independently_verified": False,
            "historical_pit_attested": False,
            "artifacts_sha256": artifacts,
            "research_only": True,
            "decision_eligible": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
            "limitations": [
                "CURRENT_FORWARD_COHORT_NOT_HISTORICAL_PIT_UNIVERSE",
                "SECURITY_TYPE_NOT_INDEPENDENTLY_VERIFIED_IN_FEATURE_PRICE_AUDIT",
                "VENDOR_SPLIT_ADJUSTED_FEATURES_ARE_NOT_EXECUTION_PRICES",
                "NO_H1_H3_H5_RETURN_FORECAST_IN_THIS_SNAPSHOT",
            ],
        }
        manifest["content_sha256"] = sha256(_canonical(manifest).encode()).hexdigest()
        (work / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                       indent=2, allow_nan=False),
            encoding="utf-8",
        )
        if folder.exists():
            raise FileExistsError("Concurrent L3 factor snapshot exists")
        work.rename(folder)
    return read_current_factor_snapshot(root, session_date, identity, include_frames=False)


def _location(root, session_date, identity):
    if not isinstance(identity, str) or not _ID.fullmatch(identity):
        raise ValueError("Invalid L3 factor snapshot identity")
    base = Path(root).resolve() / _ROOT
    folder = (base / session_date / identity).resolve()
    if not folder.is_relative_to(base.resolve()):
        raise ValueError("L3 factor snapshot path escaped archive")
    return folder


def read_current_factor_snapshot(root, session_date, identity, *, include_frames=False):
    folder = _location(root, session_date, identity)
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError("L3 current factor snapshot unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = manifest.pop("content_sha256", None)
    artifacts = manifest.get("artifacts_sha256") or {}
    if (manifest.get("schema") != _SCHEMA
            or manifest.get("session_date_et") != session_date
            or manifest.get("identity") != identity
            or manifest.get("research_only") is not True
            or manifest.get("decision_eligible") is not False
            or manifest.get("real_orders_enabled") is not False
            or not isinstance(digest, str)
            or digest != sha256(_canonical(manifest).encode()).hexdigest()):
        raise ValueError("L3 current factor snapshot failed integrity validation")
    for name, expected in artifacts.items():
        path = (folder / name).resolve()
        if (not path.is_relative_to(folder) or not path.is_file()
                or _file_hash(path) != expected):
            raise ValueError("L3 current factor artifact failed SHA256 validation")
    manifest["content_sha256"] = digest
    output = {
        "status": "FROZEN_CURRENT_L3_FACTOR_SNAPSHOT_RESEARCH_ONLY",
        "manifest": manifest,
        "real_orders_enabled": False,
    }
    if include_frames:
        output["factors"] = pd.read_parquet(folder / "factors.parquet")
        output["candidate_meta"] = pd.read_parquet(folder / "candidate_meta.parquet")
    return output


def latest_current_factor_snapshots(root, *, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("L3 factor snapshot limit must be 1–50")
    base = Path(root).resolve() / _ROOT
    rows = []
    if not base.is_dir():
        return rows
    for day in sorted(base.iterdir(), reverse=True):
        if not day.is_dir():
            continue
        for folder in sorted(day.iterdir(), reverse=True):
            if not folder.is_dir() or not _ID.fullmatch(folder.name):
                continue
            try:
                item = read_current_factor_snapshot(
                    root, day.name, folder.name, include_frames=False
                )
                manifest = item["manifest"]
                rows.append({
                    "session_date_et": day.name,
                    "identity": folder.name,
                    "status": item["status"],
                    "strategy_version_id": manifest["strategy_version_id"],
                    "strategy_config_sha256": manifest["strategy_config_sha256"],
                    "source_snapshot_sha256": manifest["source_snapshot_sha256"],
                    "complete_factor_security_count": manifest[
                        "complete_factor_security_count"
                    ],
                })
            except (OSError, ValueError, KeyError, TypeError, FileNotFoundError):
                rows.append({
                    "session_date_et": day.name,
                    "identity": folder.name,
                    "status": "CORRUPT_CURRENT_L3_FACTOR_SNAPSHOT",
                })
            if len(rows) >= limit:
                return rows
    return rows


def run_current_l3_day(root, *, session_date, feature_run_id=None):
    """One-command Alpha-only current-session path: factor snapshot then ranking freeze."""
    snapshot = build_current_factor_snapshot(
        root, session_date=session_date, feature_run_id=feature_run_id
    )
    from quant_research.workflow.l3_daily import freeze_l3_current
    daily = freeze_l3_current(
        root, session_date=session_date,
        factor_snapshot_identity=snapshot["manifest"]["identity"],
    )
    return {
        "status": "L3_CURRENT_ALPHA_DAY_FROZEN",
        "session_date_et": session_date,
        "factor_snapshot": snapshot,
        "daily_alpha": daily,
        "research_only": True,
        "execution_ready": False,
        "real_orders_enabled": False,
    }
