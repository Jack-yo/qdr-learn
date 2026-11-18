"""Read-only data warehouse inventory, provenance and sample inspection."""
from contextlib import closing
from datetime import date, datetime, timezone
import json
import re
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_research.data.catalog import build_catalog
from quant_research.data.l1_market_catalog import catalog_payload
from quant_research.data.l1_market_freshness import freshness
from quant_research.data.store import duckdb
from quant_research.policy import PolicyError


_ID = re.compile(r"^[a-z0-9_]{1,64}$")
_DATE_FIELDS = ("session_date", "observation_date", "date", "scheduled_at", "started_at")
_TIME_FIELDS = ("available_at", "fetched_at", "ingested_at", "checked_at", "known_at")
_BASE_PREVIEWS = {
    "market_prices": {
        "path": "data/real_v21.duckdb", "table": "prices_daily",
        "where": ["source='ALPACA'", "feed='sip'", "adjustment_basis='raw'"],
        "q_fields": ("symbol",), "date_fields": ("date",),
        "order": "date", "use_policy": "OBSERVATION_ONLY",
    },
    "yahoo_research_prices": {
        "path": "data/research.duckdb", "table": "prices_daily",
        "where": ["source='YAHOO'", "feed='yahoo'", "adjustment_basis='yahoo_split_adjusted'",
                  "date>='2017-01-01'", "date<='2024-12-31'"],
        "q_fields": ("symbol",), "date_fields": ("date",),
        "order": "date", "use_policy": "EXPLORATORY_ONLY_NOT_RAW_NOT_PIT",
    },
    "corporate_actions": {
        "path": "data/managed/corporate_actions/events.duckdb",
        "table": "corporate_event_versions", "where": [],
        "q_fields": ("event_id", "symbol", "source"), "date_fields": ("observed_at",),
        "order": "observed_at", "use_policy": "EVENT_EVIDENCE_NOT_ACCEPTED_LEDGER",
    },
    "sec_filings": {
        "path": "data/g3_evidence.duckdb", "table": "filing_index_versions",
        "where": [], "q_fields": ("cik", "accession_number", "form"),
        "date_fields": ("filed_at", "filing_date", "observed_at"),
        "order": "observed_at", "use_policy": "INDEX_EVIDENCE_ONLY",
    },
    "sec_candidates": {
        "path": "data/g3_evidence.duckdb", "table": "financial_candidates",
        "where": [], "q_fields": ("cik", "ticker", "tag", "concept"),
        "date_fields": ("filed_at", "period_end", "accepted_at"),
        "order": "accepted_at", "use_policy": "NOT_HISTORICAL_PIT",
    },
    "classic_factors": {
        "path": "data/managed/classic_factors/factors.duckdb",
        "table": "factor_returns", "where": ["source='KEN_FRENCH'", "use_policy='ATTRIBUTION_ONLY'"],
        "q_fields": ("factor_name",), "date_fields": ("date",),
        "order": "date", "use_policy": "ATTRIBUTION_ONLY",
    },
}

_L1_TABLES = (
    ("l1_market_bars", "L1 行情 Bars", "行情数据", "l1_market_bars", "session_date",
     ("symbol", "security_id"), "date", "OBSERVATION_ONLY"),
    ("l1_market_universe", "L1 证券池观察", "证券身份", "l1_market_universe", "session_date",
     ("symbol", "security_id", "universe_id"), "session_date", "CURRENT_UNIVERSE_OBSERVATION_NOT_PIT"),
    ("l1_market_observations", "L1 市场指标观察", "市场指标", "l1_market_observations", "session_date",
     ("feature_id", "dimension", "source"), "session_date", "OBSERVATION_ONLY"),
    ("l1_market_security_features", "L1 个股特征", "个股特征", "l1_market_security_features", "session_date",
     ("symbol", "security_id", "feature_id"), "session_date", "PIT_UNVERIFIED"),
    ("l1_market_reference_series", "L1 跨资产参考序列", "宏观与跨资产", "l1_market_reference_series", "observation_date",
     ("series_id", "feature_id", "source"), "observation_date", "OBSERVATION_ONLY"),
    ("l1_market_events", "L1 事件与预期", "事件催化", "l1_market_events", "scheduled_at",
     ("event_id", "event_type", "source"), "scheduled_at", "EVENT_VINTAGE_REVIEW_REQUIRED"),
    ("l1_market_source_receipts", "L1 原始来源回执", "来源与溯源", "l1_market_source_receipts", "observed_start",
     ("provider", "dataset", "receipt_sha256"), "fetched_at", "PROVENANCE_ONLY"),
    ("l1_market_source_health", "L1 数据源健康记录", "数据源监控", "l1_market_source_health", "asof_session",
     ("source_key", "status", "error_code"), "fetched_at", "OBSERVABILITY_ONLY"),
    ("l1_market_quality_checks", "L1 数据质量检查", "数据质量", "l1_market_quality_checks", "session_date",
     ("dimension", "status", "reason"), "checked_at", "QUALITY_EVIDENCE_ONLY"),
    ("l1_market_path_labels", "L1 未来路径标签", "结果验证", "l1_market_path_labels", "session_date",
     ("horizon", "forward_return", "mfe", "mae", "first_touch"), "available_at", "OUTCOME_VALIDATION_NOT_INPUT"),
    ("l1_market_run_log", "L1 采集任务日志", "任务运行", "l1_market_run_log", "started_at",
     ("run_id", "command", "status"), "started_at", "OPERATIONS_EVIDENCE_ONLY"),
)


_L1_CADENCE = {
    "l1_market_bars": "daily", "l1_market_universe": "daily",
    "l1_market_observations": "daily", "l1_market_security_features": "daily",
    "l1_market_reference_series": "daily", "l1_market_events": "event",
    "l1_market_source_receipts": "on_demand", "l1_market_source_health": "daily",
    "l1_market_quality_checks": "daily", "l1_market_path_labels": "per-session",
    "l1_market_run_log": "on_demand",
}

_CATEGORY = {
    "market_prices": "行情数据", "yahoo_research_prices": "行情数据",
    "close_snapshots": "行情数据", "l1_market_store": "行情数据",
    "l1_market_bars": "行情数据", "l1_market_universe": "证券身份",
    "historical_securities": "证券身份", "asset_observations": "证券身份",
    "l1_market_observations": "市场指标", "l1_market_security_features": "个股特征",
    "l1_market_reference_series": "宏观与跨资产", "classic_factors": "因子数据",
    "factor_lab": "因子数据", "corporate_actions": "公司行为",
    "sec_filings": "公司与财务", "sec_candidates": "公司与财务",
    "pit_fundamentals": "公司与财务", "l1_market_events": "事件催化",
    "l1_market_source_receipts": "来源与溯源",
    "l1_market_source_health": "数据源监控",
    "l1_market_quality_checks": "数据质量",
    "l1_market_path_labels": "结果验证", "l1_market_run_log": "任务运行",
    "eligible_models": "研究与归档", "paper_ledger": "研究与归档",
    "strategies": "研究与归档", "daily_observations": "研究与归档",
}



def _reference_date():
    """Market observation dates are XNYS-local session dates, not UTC calendar dates."""
    return datetime.now(ZoneInfo("America/New_York")).date().isoformat()


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return None if text.lower() in {"", "none", "nat", "nan", "<na>"} else text


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return None
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if hasattr(value, "item"):
        try:
            return _json_value(value.item())
        except (ValueError, TypeError):
            pass
    return str(value)


def _quote(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise ValueError("WAREHOUSE_IDENTIFIER_REJECTED")
    return '"' + identifier + '"'



def _catalog_snapshot_time(root):
    path = Path(root) / "data" / "catalog" / "latest.json"
    if not path.is_file():
        return None
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        return pointer.get("created_at_utc") if isinstance(pointer, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _maintenance_locked(root):
    base = Path(root) / "data" / "catalog"
    return any((base / name).is_file() for name in (".maintenance.lock", ".daily_ops.lock"))


def _l1_table_assets(root):
    root = Path(root).resolve()
    path = root / "data" / "l1_market" / "market_data.duckdb"
    assets = []
    if not path.is_file():
        for key, name, category, table, day, fields, order, policy in _L1_TABLES:
            assets.append({
                "dataset_id": key, "name": name, "category": category, "path": "data/l1_market/market_data.duckdb",
                "table": table, "source": "L1 MARKET DATA STORE", "cadence": _L1_CADENCE.get(key, "daily"),
                "status": "NOT_CREATED", "physical_rows": None, "unique_rows": None,
                "first_observation": None, "last_observation": None, "use_policy": policy,
                "missing_reason": "L1_MARKET_DATABASE_NOT_CREATED", "preview_supported": False,
                "field_names": [], "systems": [],
            })
        return assets, {"status": "NOT_CREATED", "tables_present": 0, "rows": None}
    with closing(duckdb.connect(str(path), read_only=True)) as db:
        present = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        total_rows = 0
        for key, name, category, table, day, fields, order, policy in _L1_TABLES:
            item = {
                "dataset_id": key, "name": name, "category": category,
                "path": "data/l1_market/market_data.duckdb", "table": table,
                "source": "L1 MARKET DATA STORE", "cadence": _L1_CADENCE.get(key, "daily"),
                "use_policy": policy, "preview_supported": table in present,
                "physical_rows": None, "unique_rows": None,
                "first_observation": None, "last_observation": None,
                "latest_available_at_utc": None, "latest_fetched_at_utc": None,
                "latest_ingested_at_utc": None, "missing_reason": None,
                "field_names": [], "systems": [],
            }
            if table not in present:
                item.update(status="TABLE_NOT_CREATED", missing_reason="EXPECTED_TABLE_MISSING")
                assets.append(item)
                continue
            quoted = _quote(table)
            columns = {row[0] for row in db.execute(f"DESCRIBE {quoted}").fetchall()}
            item["field_names"] = sorted(columns)
            row = db.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
            count = int(row[0] or 0)
            total_rows += count
            item["physical_rows"] = count
            if count == 0:
                item.update(status="EMPTY_DATASET", missing_reason="EMPTY_DATASET")
                assets.append(item)
                continue
            if day in columns:
                bounds = db.execute(
                    f"SELECT MIN({_quote(day)}), MAX({_quote(day)}) FROM {quoted}"
                ).fetchone()
                item["first_observation"], item["last_observation"] = _iso(bounds[0]), _iso(bounds[1])
            unique_expr = {
                "l1_market_bars": "COUNT(DISTINCT (session_date, security_id))",
                "l1_market_universe": "COUNT(DISTINCT (session_date, universe_id, security_id))",
                "l1_market_observations": "COUNT(DISTINCT (session_date, feature_id))",
                "l1_market_security_features": "COUNT(DISTINCT (session_date, security_id, feature_id))",
                "l1_market_reference_series": "COUNT(DISTINCT (observation_date, series_id))",
                "l1_market_events": "COUNT(DISTINCT event_id)",
                "l1_market_source_receipts": "COUNT(DISTINCT receipt_sha256)",
                "l1_market_source_health": "COUNT(DISTINCT (source_key, asof_session))",
                "l1_market_quality_checks": "COUNT(DISTINCT (session_date, dimension, reason))",
                "l1_market_path_labels": "COUNT(DISTINCT (session_date, horizon))",
                "l1_market_run_log": "COUNT(DISTINCT run_id)",
            }[table]
            item["unique_rows"] = int(db.execute(f"SELECT {unique_expr} FROM {quoted}").fetchone()[0] or 0)
            for field, output in (("available_at", "latest_available_at_utc"),
                                  ("fetched_at", "latest_fetched_at_utc"),
                                  ("ingested_at", "latest_ingested_at_utc")):
                if field in columns:
                    item[output] = _iso(db.execute(
                        f"SELECT MAX({_quote(field)}) FROM {quoted}"
                    ).fetchone()[0])
            if "symbol" in columns:
                item["symbols"] = int(db.execute(
                    f"SELECT COUNT(DISTINCT symbol) FROM {quoted}"
                ).fetchone()[0] or 0)
            if "feature_id" in columns:
                item["features"] = int(db.execute(
                    f"SELECT COUNT(DISTINCT feature_id) FROM {quoted}"
                ).fetchone()[0] or 0)
            if "provider" in columns:
                item["providers"] = [row[0] for row in db.execute(
                    f"SELECT DISTINCT provider FROM {quoted} ORDER BY provider LIMIT 5"
                ).fetchall()]
            elif "source" in columns:
                item["providers"] = [row[0] for row in db.execute(
                    f"SELECT DISTINCT source FROM {quoted} ORDER BY source LIMIT 5"
                ).fetchall()]
            item["status"] = "COLLECTED_RESTRICTED_USE"
            assets.append(item)
    return assets, {"status": "AVAILABLE", "tables_present": sum(x["table"] in present for x in assets),
                    "rows": total_rows, "path": "data/l1_market/market_data.duckdb"}



def _registered_field_names(root, dataset_id):
    spec = _BASE_PREVIEWS.get(dataset_id)
    if spec is None:
        return []
    root = Path(root).resolve()
    path = (root / spec["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return []
    try:
        with closing(duckdb.connect(str(path), read_only=True)) as db:
            tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
            if spec["table"] not in tables:
                return []
            return sorted(row[0] for row in db.execute(
                f"DESCRIBE {_quote(spec['table'])}"
            ).fetchall())
    except Exception:
        return []


def _attach_systems(root, datasets, registry):
    for item in datasets:
        item.setdefault("systems", [])
    features = {row["key"]: row for row in registry.get("features", [])}
    dimensions = {row["key"]: row for row in registry.get("dimensions", [])}
    path = Path(root).resolve() / "data" / "l1_market" / "market_data.duckdb"
    if not path.is_file():
        return
    by_id = {item["dataset_id"]: item for item in datasets}
    wanted = {
        "l1_market_observations": ("feature_id", None),
        "l1_market_security_features": ("feature_id", None),
        "l1_market_reference_series": ("feature_id", None),
        "l1_market_quality_checks": ("dimension", None),
        "l1_market_events": (None, "events"),
    }
    try:
        with closing(duckdb.connect(str(path), read_only=True)) as db:
            present = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
            for dataset_id, (field, fixed_dimension) in wanted.items():
                item = by_id.get(dataset_id)
                if item is None or dataset_id not in present:
                    continue
                dimension_keys = set()
                if fixed_dimension:
                    dimension_keys.add(fixed_dimension)
                elif field:
                    values = [row[0] for row in db.execute(
                        f"SELECT DISTINCT {_quote(field)} FROM {_quote(dataset_id)} "
                        f"WHERE {_quote(field)} IS NOT NULL"
                    ).fetchall()]
                    if field == "feature_id":
                        dimension_keys.update(
                            features[value]["dimension"] for value in values
                            if value in features
                        )
                    else:
                        dimension_keys.update(value for value in values if value in dimensions)
                systems = set()
                for dimension in dimension_keys:
                    systems.update(dimensions.get(dimension, {}).get("system_keys", []))
                item["systems"] = sorted(systems)
    except Exception:
        return


def _maintenance_runs(root, limit=20):
    base = Path(root).resolve() / "outputs" / "maintenance"
    if not base.is_dir():
        return []
    rows = []
    for folder in base.iterdir():
        manifest_path = folder / "manifest.json"
        if not folder.is_dir() or not manifest_path.is_file():
            continue
        try:
            if not manifest_path.resolve().is_relative_to(base.resolve()):
                continue
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("tasks", []), list):
                continue
            tasks = []
            for task in data.get("tasks", []):
                if not isinstance(task, dict):
                    continue
                tasks.append({key: task.get(key) for key in (
                    "group", "source", "status", "code", "rows", "inserted_rows",
                    "missing_sessions", "start", "end", "database", "style_monitor_status",
                ) if key in task})
            rows.append({
                "run_id": str(data.get("run_id") or folder.name),
                "status": data.get("status") or "RUNNING",
                "created_at_utc": data.get("created_at_utc"),
                "finished_at_utc": data.get("finished_at_utc"),
                "end": data.get("end"), "offline": data.get("offline"),
                "tasks": tasks, "path": manifest_path.relative_to(Path(root).resolve()).as_posix(),
            })
        except (OSError, ValueError, TypeError):
            continue
    rows.sort(key=lambda item: str(item.get("created_at_utc") or ""), reverse=True)
    return rows[:limit]


def _source_health(root):
    path = Path(root) / "data" / "l1_market" / "market_data.duckdb"
    if not path.is_file():
        return {}
    with closing(duckdb.connect(str(path), read_only=True)) as db:
        tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        if "l1_market_source_health" not in tables:
            return {}
        rows = db.execute("""
            SELECT source_key, CAST(asof_session AS VARCHAR), CAST(fetched_at AS VARCHAR),
                   status, error_code, receipt_sha256, metadata_json
            FROM l1_market_source_health
            QUALIFY ROW_NUMBER() OVER (PARTITION BY source_key ORDER BY fetched_at DESC, asof_session DESC)=1
        """).fetchall()
    result = {}
    for key, asof, fetched, status, code, digest, metadata in rows:
        try:
            parsed = json.loads(metadata) if metadata else {}
        except (ValueError, TypeError):
            parsed = {}
        safe_metadata = {}
        if isinstance(parsed, dict):
            safe_metadata = {name: parsed[name] for name in (
                "scope", "coverage_n", "expected_n", "observation_mode",
                "feed_sources", "effective_date", "pit",
            ) if name in parsed}
        result[str(key)] = {
            "source_key": str(key), "asof_session": asof, "fetched_at_utc": fetched,
            "status": str(status), "error_code": code, "receipt_sha256": digest,
            "metadata": safe_metadata,
        }
    return result



def _quality_alerts(root, limit=50):
    """Expose only explicitly failed/partial persisted quality checks."""
    path = Path(root) / "data" / "l1_market" / "market_data.duckdb"
    if not path.is_file():
        return []
    with closing(duckdb.connect(str(path), read_only=True)) as db:
        present = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        if "l1_market_quality_checks" not in present:
            return []
        rows = db.execute("""
            SELECT CAST(session_date AS VARCHAR), dimension, status, reason,
                   coverage_n, expected_n, CAST(checked_at AS VARCHAR), metadata_json
            FROM l1_market_quality_checks
            WHERE UPPER(status) IN ('BLOCKED','FAILED','PARTIAL','MISSING','ERROR')
            ORDER BY checked_at DESC
            LIMIT ?
        """, [limit]).fetchall()
    result = []
    for session, dimension, status, reason, covered, expected, checked, metadata in rows:
        result.append({
            "severity": "high" if str(status).upper() in {"BLOCKED", "FAILED", "ERROR"} else "medium",
            "type": "QUALITY_CHECK", "id": f"{dimension}:{session}",
            "name": f"{dimension} 数据质量检查", "status": str(status),
            "reason": (str(reason or status) +
                       (f" · 覆盖 {covered}/{expected}" if covered is not None and expected is not None else "")),
            "coverage_n": covered, "expected_n": expected,
            "occurred_at": checked,
            "action": "查看质量检查覆盖与对应来源状态",
            "checked_at_utc": checked,
        })
    return result


def _maintenance_alerts(runs, limit=20):
    result = []
    for run in runs[:10]:
        for task in run.get("tasks", []):
            status = str(task.get("status") or "").upper()
            if status not in {"BLOCKED", "FAILED", "ERROR"}:
                continue
            result.append({
                "severity": "high" if status in {"FAILED", "ERROR"} else "medium",
                "type": "MAINTENANCE", "id": f"{run.get('run_id')}:{task.get('group') or task.get('source')}",
                "name": f"{task.get('group') or task.get('source') or '数据维护'} 任务",
                "status": status, "reason": task.get("code") or status,
                "occurred_at": run.get("created_at_utc"),
                "action": "打开数据维护查看该任务组的错误记录",
                "created_at_utc": run.get("created_at_utc"),
            })
            if len(result) >= limit:
                return result
    return result


def _sources(root):
    registry = catalog_payload()
    health = _source_health(root)
    rows = []
    reference_date = _reference_date()
    for source in registry["sources"]:
        latest = health.get(source["key"])
        if latest:
            status = latest["status"]
            freshness_info = freshness(latest.get("asof_session"), source["cadence"], reference_date)
            if status not in {"BLOCKED", "MISSING", "ERROR", "FAILED"} and freshness_info["status"] in {"STALE", "FUTURE_OBSERVATION"}:
                status = freshness_info["status"]
        elif source["code_status"] == "PLANNED":
            status = "PLANNED"
            freshness_info = {"status": "UNKNOWN_DATE", "age_days": None, "max_age_days": None}
        else:
            status = "NOT_OBSERVED"
            freshness_info = {"status": "UNKNOWN_DATE", "age_days": None, "max_age_days": None}
        rows.append({
            **source, "runtime_status": status,
            "latest_observation": latest, "freshness": freshness_info,
        })
    return rows, registry


def _attention(datasets, sources):
    items = []
    for item in datasets:
        status = str(item.get("status") or "")
        freshness_status = item.get("freshness_status")
        if freshness_status in {"STALE", "FUTURE_OBSERVATION"}:
            items.append({
                "severity": "high" if freshness_status == "FUTURE_OBSERVATION" else "medium",
                "type": "DATASET", "id": item["dataset_id"], "name": item["name"],
                "status": freshness_status, "reason": "数据观测日期超出允许新鲜度窗口",
                "occurred_at": item.get("last_observation"),
                "action": "检查该资产最近维护任务与来源运行记录",
                "path": item.get("path"),
            })
        if status in {"BLOCKED", "FAILED", "TABLE_NOT_CREATED"}:
            items.append({
                "severity": "high" if status in {"FAILED", "BLOCKED"} else "medium",
                "type": "DATASET", "id": item["dataset_id"], "name": item["name"],
                "status": status, "reason": item.get("missing_reason") or status,
                "occurred_at": item.get("latest_ingested_at_utc") or item.get("latest_fetched_at_utc") or item.get("last_observation"),
                "action": "检查资产缺失原因与对应维护任务",
                "path": item.get("path"),
            })
        elif status in {"EMPTY_DATASET", "STALE", "PARTIAL"}:
            items.append({
                "severity": "medium", "type": "DATASET", "id": item["dataset_id"],
                "name": item["name"], "status": status,
                "reason": item.get("missing_reason") or status,
                "occurred_at": item.get("latest_ingested_at_utc") or item.get("latest_fetched_at_utc") or item.get("last_observation"),
                "action": "检查资产状态与对应维护记录", "path": item.get("path"),
            })
    for source in sources:
        status = source["runtime_status"]
        if status in {"BLOCKED", "MISSING", "ERROR", "FAILED", "STALE", "FUTURE_OBSERVATION"}:
            latest = source.get("latest_observation") or {}
            items.append({
                "severity": "high" if status in {"BLOCKED", "MISSING", "ERROR", "FAILED", "FUTURE_OBSERVATION"} else "medium", "type": "SOURCE", "id": source["key"],
                "name": source["name"], "status": status,
                "reason": latest.get("error_code") or status,
                "occurred_at": latest.get("fetched_at_utc") or latest.get("asof_session"),
                "action": "查看数据源运行记录并按错误码或新鲜度状态处理",
                "fetched_at_utc": latest.get("fetched_at_utc"),
            })
    rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (rank.get(item["severity"], 3), item["type"], item["name"]))
    return items


def overview(project_root):
    """Build a real, read-only inventory. No provider calls, DDL, or cache hash replay."""
    root = Path(project_root).resolve()
    if _maintenance_locked(root):
        return {
            "schema": "qdr.warehouse.overview.v1", "status": "MAINTENANCE_RUNNING",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {"asset_count": None, "with_records": None, "attention_count": None},
            "datasets": [], "attention": [], "sources": [],
            "maintenance": {"latest": None, "recent_runs": _maintenance_runs(root)},
            "policy": {"read_only": True, "provider_requests": False, "cache_hash_replay": False},
            "message": "数据维护或日终任务正在持有操作锁；为避免与写入任务竞争，暂不读取数据库。",
        }
    catalog = build_catalog(root, verify_cache_hashes=False, include_cache_inventory=False)
    datasets = []
    for source in catalog.get("datasets", []):
        item = dict(source)
        item["category"] = _CATEGORY.get(item.get("dataset_id"), "研究与归档")
        item["physical_rows"] = item.get("rows")
        item["unique_rows"] = item.get("latest_rows")
        item["first_observation"] = item.get("first_date") or item.get("first_observed_utc")
        item["last_observation"] = item.get("last_date") or item.get("last_observed_utc") or item.get("observed_at_utc")
        freshness_info = freshness(item["last_observation"], item.get("cadence"),
                                   _reference_date())
        item["freshness_status"] = freshness_info["status"]
        item["age_days"] = freshness_info["age_days"]
        item["max_age_days"] = freshness_info["max_age_days"]
        item["preview_supported"] = item.get("dataset_id") in _BASE_PREVIEWS
        item["field_names"] = _registered_field_names(root, item.get("dataset_id"))
        item.setdefault("systems", [])
        item.setdefault("limitations", [])
        datasets.append(item)
    l1_assets, l1_status = _l1_table_assets(root)
    reference_date = _reference_date()
    for item in l1_assets:
        freshness_info = freshness(item.get("last_observation"), item.get("cadence"), reference_date)
        item["freshness_status"] = freshness_info["status"]
        item["age_days"] = freshness_info["age_days"]
        item["max_age_days"] = freshness_info["max_age_days"]
    datasets.extend(l1_assets)
    sources, registry = _sources(root)
    _attach_systems(root, datasets, registry)
    datasets.sort(key=lambda item: (item.get("category", ""), item.get("name", "")))
    attention = _attention(datasets, sources)
    runs = _maintenance_runs(root)
    attention.extend(_quality_alerts(root))
    attention.extend(_maintenance_alerts(runs))
    rank = {"high": 0, "medium": 1, "low": 2}
    attention.sort(key=lambda item: (rank.get(item["severity"], 3), item["type"], item["name"]))
    latest_success = next((run for run in runs if run["status"] == "MAINTAINED"), None)
    observed_features = 0
    l1_path = root / "data" / "l1_market" / "market_data.duckdb"
    if l1_path.is_file():
        with closing(duckdb.connect(str(l1_path), read_only=True)) as db:
            present = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
            ids = set()
            for table in ("l1_market_observations", "l1_market_security_features"):
                if table in present:
                    ids.update(row[0] for row in db.execute(
                        f"SELECT DISTINCT feature_id FROM {_quote(table)} WHERE feature_id IS NOT NULL"
                    ).fetchall())
            observed_features = len(ids)
    return {
        "schema": "qdr.warehouse.overview.v1", "status": "AVAILABLE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "catalog_generated_at_utc": _catalog_snapshot_time(root),
        "summary": {
            "asset_count": len(datasets),
            "with_records": sum(1 for item in datasets
                                if item.get("dataset_id") != "l1_market_store"
                                and isinstance(item.get("physical_rows"), int) and item["physical_rows"] > 0),
            "attention_count": len(attention),
            "last_success_at_utc": (latest_success or {}).get("finished_at_utc"),
            "l1_observed_features": observed_features,
        },
        "datasets": datasets, "attention": attention, "sources": sources,
        "registry": {
            "systems": registry["systems"], "dimensions": registry["dimensions"],
            "counts": {**registry["counts"], "features_observed": observed_features},
        },
        "l1_store": l1_status,
        "maintenance": {
            "latest": runs[0] if runs else None,
            "latest_success": latest_success,
            "recent_runs": runs,
        },
        "policy": {
            "read_only": True, "provider_requests": False, "cache_hash_replay": False,
            "historical_pit_verified": False, "forecast_eligible": False,
            "trade_eligible": False,
        },
    }


def _dataset(root, dataset_id):
    if not isinstance(dataset_id, str) or not _ID.fullmatch(dataset_id):
        raise ValueError("WAREHOUSE_DATASET_ID_INVALID")
    root = Path(root).resolve()
    if _maintenance_locked(root):
        raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance currently owns the warehouse")
    catalog = build_catalog(root, verify_cache_hashes=False, include_cache_inventory=False)
    datasets = []
    for source in catalog.get("datasets", []):
        item = dict(source)
        item["category"] = _CATEGORY.get(item.get("dataset_id"), "研究与归档")
        item["physical_rows"] = item.get("rows")
        item["unique_rows"] = item.get("latest_rows")
        item["first_observation"] = item.get("first_date")
        item["last_observation"] = item.get("last_date") or item.get("last_observed_utc") or item.get("observed_at_utc")
        freshness_info = freshness(item["last_observation"], item.get("cadence"),
                                   _reference_date())
        item["freshness_status"] = freshness_info["status"]
        item["age_days"] = freshness_info["age_days"]
        item["max_age_days"] = freshness_info["max_age_days"]
        item["preview_supported"] = item.get("dataset_id") in _BASE_PREVIEWS
        item["field_names"] = _registered_field_names(root, item.get("dataset_id"))
        item.setdefault("systems", [])
        datasets.append(item)
    l1_assets, _ = _l1_table_assets(root)
    reference_date = _reference_date()
    for asset in l1_assets:
        freshness_info = freshness(asset.get("last_observation"), asset.get("cadence"), reference_date)
        asset["freshness_status"] = freshness_info["status"]
        asset["age_days"] = freshness_info["age_days"]
        asset["max_age_days"] = freshness_info["max_age_days"]
    datasets.extend(l1_assets)
    _attach_systems(root, datasets, catalog_payload())
    item = next((row for row in datasets if row["dataset_id"] == dataset_id), None)
    if item is None:
        raise KeyError("WAREHOUSE_DATASET_NOT_FOUND")
    return item


def _preview_spec(dataset_id):
    if dataset_id in _BASE_PREVIEWS:
        return dict(_BASE_PREVIEWS[dataset_id], engine="duckdb")
    for key, name, category, table, day, fields, order, policy in _L1_TABLES:
        if dataset_id == key:
            return {
                "path": "data/l1_market/market_data.duckdb", "table": table,
                "where": [], "q_fields": tuple(
                    field for field in fields if field not in {"forward_return", "mfe", "mae", "status", "error_code", "receipt_sha256"}
                ), "date_fields": (day,), "order": order, "engine": "duckdb",
                "use_policy": policy,
            }
    return None


def _schema(db, table, engine):
    quoted = _quote(table)
    if engine == "duckdb":
        rows = db.execute(f"DESCRIBE {quoted}").fetchall()
        return [{"name": row[0], "type": row[1], "nullable": row[2] != "NO",
                 "key": row[3] or None} for row in rows]
    rows = db.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [{"name": row[1], "type": row[2], "nullable": not bool(row[3]),
             "key": "PRIMARY KEY" if row[5] else None} for row in rows]


def dataset_detail(project_root, dataset_id):
    root = Path(project_root).resolve()
    item = _dataset(root, dataset_id)
    spec = _preview_spec(dataset_id)
    if spec is None:
        return {
            "schema": "qdr.warehouse.dataset_detail.v1", "dataset": item,
            "fields": [], "preview_supported": False,
            "preview_reason": "该资产是版本、归档或报告类证据，V1 暂不提供表格样本预览。",
            "lineage": {"source": item.get("source"), "path": item.get("path"),
                        "table": item.get("table"), "use_policy": item.get("use_policy")},
        }
    path = (root / spec["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return {
            "schema": "qdr.warehouse.dataset_detail.v1", "dataset": item,
            "fields": [], "preview_supported": False,
            "preview_reason": "底层数据文件尚未创建。",
            "lineage": {"source": item.get("source"), "path": spec["path"],
                        "table": spec["table"], "use_policy": item.get("use_policy")},
        }
    if _maintenance_locked(root):
        raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance currently owns the warehouse")
    if spec["engine"] == "duckdb":
        with closing(duckdb.connect(str(path), read_only=True)) as db:
            tables = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
            fields = _schema(db, spec["table"], spec["engine"]) if spec["table"] in tables else []
    else:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            fields = _schema(db, spec["table"], spec["engine"]) if spec["table"] in tables else []
    return {
        "schema": "qdr.warehouse.dataset_detail.v1", "dataset": item,
        "fields": fields, "preview_supported": bool(fields),
        "preview_reason": None if fields else "权威数据表尚未创建或缺少结构。",
        "lineage": {"source": item.get("source"), "path": spec["path"],
                    "table": spec["table"], "use_policy": spec.get("use_policy") or item.get("use_policy"),
                    },
    }


def preview_dataset(project_root, dataset_id, *, q="", start=None, end=None,
                    symbol=None, dimension=None, limit=25, offset=0):
    root = Path(project_root).resolve()
    if not isinstance(q, str) or len(q) > 64:
        raise ValueError("WAREHOUSE_QUERY_INVALID")
    if symbol is not None and (not isinstance(symbol, str) or not re.fullmatch(r"[A-Za-z0-9.\-]{1,24}", symbol)):
        raise ValueError("WAREHOUSE_SYMBOL_INVALID")
    if dimension is not None and (not isinstance(dimension, str) or not _ID.fullmatch(dimension)):
        raise ValueError("WAREHOUSE_DIMENSION_INVALID")
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError("WAREHOUSE_PAGINATION_INVALID")
    for value in (start, end):
        if value is not None and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
            raise ValueError("WAREHOUSE_DATE_INVALID")
    if start and end and start > end:
        raise ValueError("WAREHOUSE_DATE_RANGE_INVALID")
    _dataset(root, dataset_id)
    spec = _preview_spec(dataset_id)
    if spec is None:
        raise PolicyError("WAREHOUSE_PREVIEW_UNSUPPORTED", "This asset does not have a tabular preview in V1")
    if _maintenance_locked(root):
        raise PolicyError("DATA_MAINTENANCE_RUNNING", "Data maintenance currently owns the warehouse")
    path = (root / spec["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise PolicyError("WAREHOUSE_DATA_FILE_MISSING", "The underlying data file has not been created")
    table = _quote(spec["table"])
    engine = spec["engine"]
    connection = (duckdb.connect(str(path), read_only=True) if engine == "duckdb"
                  else sqlite3.connect(path.as_uri() + "?mode=ro", uri=True))
    with closing(connection) as db:
        if engine == "duckdb":
            present = {row[0] for row in db.execute("SHOW TABLES").fetchall()}
        else:
            present = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if spec["table"] not in present:
            raise PolicyError("WAREHOUSE_TABLE_MISSING", "The authoritative data table does not exist")
        columns = {field["name"] for field in _schema(db, spec["table"], engine)}
        clauses = list(spec.get("where", []))
        params = []
        searchable = [field for field in spec.get("q_fields", ()) if field in columns]
        if q and not searchable:
            raise ValueError("WAREHOUSE_TEXT_FILTER_UNSUPPORTED")
        if q and searchable:
            clauses.append("(" + " OR ".join(f"CAST({_quote(field)} AS VARCHAR) ILIKE ?" for field in searchable) + ")")
            params.extend(["%" + q + "%"] * len(searchable))
        date_field = next((field for field in spec.get("date_fields", ()) if field in columns), None)
        if (start or end) and not date_field:
            raise ValueError("WAREHOUSE_DATE_FILTER_UNSUPPORTED")
        if symbol and "symbol" not in columns:
            raise ValueError("WAREHOUSE_SYMBOL_FILTER_UNSUPPORTED")
        if dimension and "dimension" not in columns:
            raise ValueError("WAREHOUSE_DIMENSION_FILTER_UNSUPPORTED")
        if start and date_field:
            clauses.append(f"CAST({_quote(date_field)} AS DATE) >= ?")
            params.append(start)
        if end and date_field:
            clauses.append(f"CAST({_quote(date_field)} AS DATE) <= ?")
            params.append(end)
        if symbol and "symbol" in columns:
            clauses.append('"symbol" = ?')
            params.append(symbol.upper())
        if dimension and "dimension" in columns:
            clauses.append('"dimension" = ?')
            params.append(dimension)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = int(db.execute(f"SELECT COUNT(*) FROM {table}{where}", params).fetchone()[0] or 0)
        order_field = spec.get("order")
        if order_field not in columns:
            order_field = next((field for field in _TIME_FIELDS if field in columns), None)
        order = f" ORDER BY {_quote(order_field)} DESC NULLS LAST" if order_field else ""
        rows = db.execute(
            f"SELECT * FROM {table}{where}{order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        names = [field["name"] for field in _schema(db, spec["table"], engine)]
        records = [{name: _json_value(value) for name, value in zip(names, row)} for row in rows]
    return {
        "schema": "qdr.warehouse.preview.v1", "status": "OBSERVED",
        "dataset_id": dataset_id, "total": total, "limit": limit, "offset": offset,
        "rows": records, "filters": {
            "q": q or None, "start": start, "end": end,
            "symbol": symbol.upper() if symbol else None, "dimension": dimension,
        },
        "read_only": True,
    }


def maintenance_runs(project_root, *, limit=20):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("WAREHOUSE_RUN_LIMIT_INVALID")
    rows = _maintenance_runs(project_root, limit=100000)
    return {"schema": "qdr.warehouse.maintenance_runs.v1",
            "total": len(rows), "runs": rows[:limit], "read_only": True}
