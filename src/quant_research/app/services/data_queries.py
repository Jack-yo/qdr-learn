"""Verified read models and approved CLI command construction for the console."""

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from quant_research.data.bundle import load_real_bundle
from quant_research.policy import SYMBOLS, PolicyError

PRIVATE_OUTPUTS = {"pytest-tmp", "ops_backups", "ops_restore"}


def allowed_artifact(root: Path, target: Path) -> bool:
    """Allow only hashed, real-source artifacts below the public outputs directory."""
    try:
        target = target.resolve()
        outputs = (root / "outputs").resolve()
        if not target.is_relative_to(outputs) or not target.is_file():
            return False
        if PRIVATE_OUTPUTS.intersection(target.relative_to(outputs).parts):
            return False
        for parent in (target.parent, *target.parents):
            if not parent.is_relative_to(outputs):
                break
            manifest = parent / "manifest.json"
            if manifest.is_file():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if str(data.get("source", "")).upper() not in {"YAHOO", "ALPACA", "FRENCH", "SEC"}:
                    return False
                if any("SYNTH" in str(flag).upper() for flag in data.get("flags", [])):
                    return False
                expected = data.get("artifacts_sha256", {}).get(target.relative_to(parent).as_posix())
                return bool(expected) and hashlib.sha256(target.read_bytes()).hexdigest() == expected
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    return False


def market_research(root: Path, horizon: int, asof: str | None = None) -> dict:
    """Read the latest complete retrospective study from verified artifacts."""
    import pandas as pd

    folder = root / "outputs/market_research"
    manifests = sorted(folder.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in manifests:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("workflow") != "train-market" or manifest.get("status") != "DESCRIPTIVE_CURRENT_VINTAGE_ONLY":
            continue
        if (
            manifest.get("source") != "yahoo"
            or manifest.get("mode") != "retrospective"
            or manifest.get("sealed_test_used") is not False
            or manifest.get("historical_decision_eligible") is not False
            or manifest.get("run_id") != path.parent.name
            or not date.fromisoformat(manifest["asof_date_et"]) < date(2025, 1, 1)
        ):
            raise PolicyError("MARKET_STUDY_SCOPE_REJECTED", "Market study scope failed verification")
        required = [
            "market_summary.json",
            "market_predictions.parquet",
            "market_style_states.parquet",
            "market_predictions.csv",
            "training_folds.csv",
            "report.html",
        ]
        if not all(allowed_artifact(root, path.parent / name) for name in required):
            raise PolicyError("MARKET_STUDY_ARTIFACT_CORRUPT", "Market study artifact SHA256 mismatch")
        if asof and not manifest["experiment"]["start"] <= asof <= manifest["asof_date_et"]:
            raise PolicyError("DATE_OUTSIDE_MARKET_STUDY", "Requested date is outside the completed study")
        summary = json.loads((path.parent / required[0]).read_text(encoding="utf-8"))
        predictions = pd.read_parquet(path.parent / required[1], filters=[("horizon", "==", horizon)])
        states = pd.read_parquet(path.parent / required[2])
        if asof:
            predictions = predictions.loc[predictions.date.eq(pd.Timestamp(asof))]
            states = states.loc[states.date.eq(pd.Timestamp(asof))]
        state_fields = ["date", "market_state", "state_available_at"]
        state_fields += [
            field
            for field in (
                "market_return_1",
                "market_return_5",
                "market_return_20",
                "market_vol_5",
                "market_vol_20",
                "market_vol_ratio",
                "market_concentration_5",
                "market_credit_5",
                "market_sector_dispersion",
                "market_sector_mean_correlation",
                "market_breadth_etf_proxy",
                "style_small_relative_return_5d",
                "style_small_relative_return_20d",
                "style_value_relative_return_5d",
                "style_value_relative_return_20d",
                "style_momentum_relative_return_5d",
                "style_momentum_relative_return_20d",
                "style_quality_relative_return_5d",
                "style_quality_relative_return_20d",
                "style_low_vol_relative_return_5d",
                "style_low_vol_relative_return_20d",
            )
            if field in states
        ]
        return {
            "status": manifest["status"],
            "horizon": horizon,
            "requested_date": asof,
            "manifest": {
                name: manifest[name]
                for name in (
                    "run_id",
                    "source",
                    "asof_date_et",
                    "source_snapshot_sha256",
                    "source_provenance",
                    "data_cutoff_utc",
                    "experiment",
                    "adjustment_basis",
                    "historical_decision_eligible",
                    "market_model_usage",
                    "prediction_rows",
                    "sealed_test_used",
                )
            },
            "predictions": json.loads(
                predictions.sort_values("date").tail(1).to_json(orient="records", date_format="iso")
            ),
            "states": json.loads(states[state_fields].tail(1).to_json(orient="records", date_format="iso")),
            "state_history": json.loads(states[state_fields].tail(126).to_json(orient="records", date_format="iso")),
            "state_history_scope": "RETROSPECTIVE_CURRENT_VINTAGE_NOT_PIT_NOT_FORWARD",
            "summary": {key: [row for row in rows if row["horizon"] == horizon] for key, rows in summary.items()},
            "artifacts": {name: (path.parent / name).relative_to(root).as_posix() for name in required[3:]},
        }
    raise PolicyError("NO_COMPLETED_MARKET_STUDY", "Run the Yahoo retrospective market study first")


def feature_evidence(root: Path, dataset: dict) -> dict:
    """Display matching hashed audit evidence without changing bundle capabilities."""
    if dataset.get("source") != "ALPACA":
        return {"status": "BLOCKED", "code": "FEATURE_EVIDENCE_SOURCE_UNSUPPORTED"}
    paths = sorted(
        (root / "outputs/feature_prices").glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                data.get("raw_snapshot_sha256") != dataset["snapshot_sha256"]
                or data.get("anchor_date_et") != dataset["asof_date_et"]
            ):
                continue
            if not data.get("generated_at_utc") or datetime.fromisoformat(
                data["generated_at_utc"]
            ) > datetime.fromisoformat(dataset["knowledge_cutoff_utc"]):
                continue
            required = {
                "comparison.json",
                "precision.json",
                "issuer_checks.json",
                "feature_prices.parquet",
                "vendor_split_reference.parquet",
            }
            if not required <= set(data.get("artifacts_sha256", {})):
                continue
            if not all(allowed_artifact(root, path.parent / name) for name in required):
                return {"status": "BLOCKED", "code": "FEATURE_EVIDENCE_ARTIFACT_HASH_MISMATCH"}
            comparison = json.loads((path.parent / "comparison.json").read_text(encoding="utf-8"))
            precision = json.loads((path.parent / "precision.json").read_text(encoding="utf-8"))
            issuer = json.loads((path.parent / "issuer_checks.json").read_text(encoding="utf-8"))
            return {
                "status": data["status"],
                "run_id": data["run_id"],
                "generated_at_utc": data["generated_at_utc"],
                "basis": data["adjustment_basis"],
                "strict_reference_status": comparison["status"],
                "rows_compared": comparison["rows_compared"],
                "issuer_matched": issuer["matched_splits"],
                "issuer_requested": issuer["requested_splits"],
                "issuer_unverified_symbols": [
                    check["symbol"] for check in issuer["checks"] if check["status"] != "CASE_FIELDS_MATCH"
                ],
                "empirical_quantizer_mismatches": {
                    key: value["binary64_floor_x100_plus_half_div100_mismatches"]
                    for key, value in precision["checks"].items()
                },
                "vendor_rounding_guaranteed": False,
                "execution_enabled": False,
                "comparison_path": (path.parent / "comparison.json").relative_to(root).as_posix(),
                "issuer_path": (path.parent / "issuer_checks.json").relative_to(root).as_posix(),
            }
        except (KeyError, ValueError, OSError):
            return {"status": "BLOCKED", "code": "FEATURE_EVIDENCE_INVALID"}
    return {
        "status": "BLOCKED",
        "code": "NO_MATCHING_FEATURE_EVIDENCE",
        "message": "No verified evidence matches this raw snapshot, anchor and cutoff",
    }


def snapshot(
    root: Path, source: str = "alpaca", database: Path | None = None, asof: str | None = None, cutoff=None
) -> dict:
    """Build the read-only observation snapshot used by status endpoints."""
    if (root / "data/catalog/.maintenance.lock").is_file():
        return {
            "busy": True,
            "status": "DATA_MAINTENANCE_RUNNING",
            "real_orders_enabled": False,
            "execution_enabled": False,
        }
    database = database or root / ("data/real_v21.duckdb" if source == "alpaca" else "data/research.duckdb")
    result = {
        "source": "YAHOO_REAL_CURRENT_VINTAGE",
        "real_orders_enabled": False,
        "execution_enabled": False,
        "prices": [],
        "reports": [],
        "limitations": [
            "当前显式ETF列表不是历史PIT股票池",
            "永久身份、退市和完整公司行为仍未验收",
            "raw价格的跨期收益需要公司行为调整，缺失时显示N/A",
            "SEC财务候选不具备PIT资格",
            "旧 baseline 的 2025+ 封存仅约束旧实验；V4 可使用最新合格数据",
        ],
    }
    if database.exists():
        try:
            bundle = load_real_bundle(database, source, asof, cutoff, raw_root=root / "data/raw")
            bundle.require("observation")
            frame = bundle.prices
            import pandas as pd

            day = pd.Timestamp(bundle.metadata["asof_date_et"])
            latest = frame.loc[pd.to_datetime(frame.date).eq(day)]
            result["source"] = bundle.metadata["source"]
            result["dataset"] = bundle.metadata
            result["capabilities"] = bundle.capabilities
            result["feature_evidence"] = feature_evidence(root, bundle.metadata)
            result.update(
                run_id=None,
                data_cutoff_utc=bundle.metadata["knowledge_cutoff_utc"],
                asof_date_et=bundle.metadata["asof_date_et"],
                model_version=None,
                source_provenance=bundle.metadata["source_provenance"],
                data_quality_flags=["CURRENT_VINTAGE_NOT_HISTORICAL_PIT", "EXPLICIT_CURRENT_PROXY_LIST"],
            )
            for row in latest.itertuples():
                result["prices"].append(
                    {
                        "symbol": row.symbol,
                        "date": str(pd.Timestamp(row.date).date()),
                        "close": row.close,
                        "volume": row.volume,
                        "return20": None,
                        "basis": row.adjustment_basis,
                        "available_at": row.available_at.isoformat(),
                        "sessions": int(frame.symbol.eq(row.symbol).sum()),
                    }
                )
        except PolicyError as exc:
            result["error"] = exc.payload()
    output_dirs = (
        folder for folder in (root / "outputs").glob("*") if folder.is_dir() and folder.name not in PRIVATE_OUTPUTS
    )
    reports = (path for folder in output_dirs for path in folder.rglob("report.html"))
    for report in sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)[:40]:
        if allowed_artifact(root, report):
            result["reports"].append({"path": report.relative_to(root).as_posix(), "run": report.parent.name})
    result["policy"] = "REAL_ONLY"
    result["status"] = "OBSERVATION_ONLY" if result["prices"] else "NOT_READY"
    if not result["prices"]:
        result["source"] = None
    return result


def action_commands(action: str, source: str = "yahoo", database: Path | None = None) -> list[list[str]]:
    """Construct the finite command vocabulary available through the loopback UI."""
    if action == "asset-universe":
        return [["assets-sync", "--endpoint", "paper", "--env-file", ".env"]]
    if action == "style-report":
        return [["style-report"]]
    if action == "close-snapshot":
        return [["close-snapshot"]]
    if action == "daily-observation" or (action == "daily" and source == "alpaca"):
        return [["daily-observation"]]
    if action == "market-research-yahoo":
        return [
            [
                "train-market",
                "--source",
                "yahoo",
                "--mode",
                "retrospective",
                "--db",
                "data/research.duckdb",
                "--output",
                "outputs/market_research",
            ]
        ]
    if action == "alpha-research-yahoo":
        return [
            [
                "train",
                "--source",
                "yahoo",
                "--mode",
                "retrospective",
                "--db",
                "data/research.duckdb",
                "--output",
                "outputs/alpha_research",
            ]
        ]
    if action == "maintain-daily":
        if source != "alpaca":
            raise ValueError("Daily maintenance uses the reviewed Alpaca profile")
        return [["maintain-data", "--cadence", "daily", "--env-file", ".env"]]
    database = database or ("data/real_v21.duckdb" if source == "alpaca" else "data/research.duckdb")
    common = ["--source", source, "--db", str(database), "--output", "outputs/real"]
    if action == "acceptance" and source == "alpaca":
        return [["bundle-audit", "--source", source, "--db", str(database)]]
    if action == "acceptance":
        return [["real-acceptance", "--db", "data/research.duckdb", "--output", "outputs/real_acceptance"]]
    if action in {"market-model", "alpha-model"}:
        return [["train-market" if action == "market-model" else "train", *common, "--mode", "retrospective"]]
    if action == "refresh":
        from quant_research.clock import TradingClock
        from quant_research.models.settings import load_settings
        from quant_research.workflow.daily import resolve_day

        end = resolve_day("auto", load_settings(Path("configs/experiments/baseline.yaml")), TradingClock())
        return [
            [
                "ingest",
                *common,
                "--symbols",
                ",".join(SYMBOLS),
                "--start",
                "2017-01-03",
                "--end",
                end,
                "--refresh",
                *(["--feed", "sip", "--env-file", ".env"] if source == "alpaca" else []),
            ]
        ]
    if action == "market":
        return [["market-report", *common, "--mode", "retrospective"]]
    if action == "factors":
        return [["factor-report", *common, "--mode", "retrospective"]]
    if action == "daily":
        return [["daily-report", *common, "--mode", "retrospective", "--asof", "auto"]]
    raise ValueError("Unknown action")
