"""Read-only observability for the QDR data warehouse.

This module never creates a database, runs DDL, contacts providers, or changes
research eligibility. Dataset and preview resources are fixed code allowlists.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

from .l1_market_catalog import SOURCES
from .catalog import DATASETS, MISSING, inspect_database


_L1_DB = Path("data/l1_market/market_data.duckdb")
_MAINTENANCE_LOCK = Path("data/catalog/.maintenance.lock")
_SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,16}$")

# resource_id -> (table, date_column, display fields, policy)
_CATALOG_PREVIEWS = {
    "market_prices": {
        "path": Path("data/real_v21.duckdb"), "table": "prices_daily",
        "date": "date", "symbol": True,
        "fields": ("security_id","symbol","date","open","high","low","close",
                   "volume","source","feed","adjustment_basis","event_time",
                   "available_at","ingested_at","raw_sha256","quality_flag"),
        "where": "source='ALPACA' AND feed='sip' AND adjustment_basis='raw'",
        "policy": "ALPACA_SIP_RAW_OBSERVATION_ONLY",
    },
    "classic_factors": {
        "path": Path("data/managed/classic_factors/factors.duckdb"),
        "table": "factor_returns", "date": "date", "symbol": False,
        "fields": ("date","factor_name","value_decimal","source","available_at",
                   "version","use_policy"),
        "where": "source='KEN_FRENCH' AND use_policy='ATTRIBUTION_ONLY'",
        "policy": "KEN_FRENCH_ATTRIBUTION_ONLY",
    },
}


_L1_RESOURCES = {
    "market_bars": {
        "table": "l1_market_bars", "date": "session_date",
        "fields": ("session_date","symbol","security_id","open","high","low","close",
                   "volume","provider","price_basis","identity_status","available_at",
                   "receipt_sha256","ingested_at"),
        "category": "行情数据", "policy": "OBSERVATION_ONLY_NOT_HISTORICAL_PIT",
        "description": "核心 ETF 与已采集证券的日线行情，保留来源版本。",
    },
    "market_universe": {
        "table": "l1_market_universe", "date": "session_date",
        "fields": ("session_date","universe_id","security_id","symbol","is_member",
                   "provider","membership_basis","snapshot_complete","pit_status",
                   "known_at","receipt_sha256","ingested_at"),
        "category": "证券目录", "policy": "CURRENT_OBSERVATION_NOT_HISTORICAL_PIT",
        "description": "当前或历史证券池观察；只有独立 PIT 证明才可用于历史成员资格。",
    },
    "market_observations": {
        "table": "l1_market_observations", "date": "session_date",
        "fields": ("session_date","dimension","feature_id","value","unit","provider",
                   "source","observed_at","available_at","vintage_id","pit_status",
                   "quality_status","coverage_n","expected_n","receipt_sha256",
                   "ingested_at"),
        "category": "市场指标", "policy": "OBSERVATION_ONLY",
        "description": "市场级指标观测，含来源、可用时间和覆盖分母。",
    },
    "security_features": {
        "table": "l1_market_security_features", "date": "session_date",
        "fields": ("session_date","security_id","symbol","feature_id","value","unit",
                   "provider","source","available_at","receipt_sha256","pit_status",
                   "quality_status","price_basis","vintage_id","ingested_at"),
        "category": "个股特征", "policy": "RESEARCH_ONLY_PIT_UNVERIFIED",
        "description": "证券级派生特征，必须遵守对应身份与 PIT 限制。",
    },
    "reference_history": {
        "table": "l1_market_reference_series", "date": "observation_date",
        "fields": ("observation_date","series_id","feature_id","value","unit","provider",
                   "source","available_at","receipt_sha256","vintage_id","pit_status",
                   "quality_status","ingested_at"),
        "category": "宏观与跨资产历史", "policy": "CURRENT_VINTAGE_ONLY_NOT_LIVE_FEATURE_COVERAGE",
        "description": "VIX/FRED 等参考序列独立保存，不计入实时市场特征覆盖。",
    },
    "market_events": {
        "table": "l1_market_events", "date": "scheduled_at",
        "fields": ("event_id","source","event_type","scheduled_at","schedule_known_at",
                   "released_at","consensus_value","consensus_known_at","actual_value",
                   "receipt_sha256","vintage_id","ingested_at"),
        "category": "事件与催化剂", "policy": "SCHEDULE_OBSERVATION_ONLY",
        "description": "事件日程与发布时间证据；未有历史 vintage 时不能倒推。",
    },
    "source_health": {
        "table": "l1_market_source_health", "date": "fetched_at",
        "fields": ("source_key","asof_session","fetched_at","status","error_code",
                   "receipt_sha256"),
        "category": "数据源监控", "policy": "OPERATIONAL_EVIDENCE_ONLY",
        "description": "真实 source health 运行记录，不等同于注册代码状态。",
    },
    "quality_checks": {
        "table": "l1_market_quality_checks", "date": "checked_at",
        "fields": ("session_date","dimension","status","reason","coverage_n",
                   "expected_n","checked_at"),
        "category": "质量检查", "policy": "QUALITY_EVIDENCE_ONLY",
        "description": "数据质量检查及覆盖分母。",
    },
    "path_outcomes": {
        "table": "l1_market_path_labels", "date": "available_at",
        "fields": ("session_date","horizon","entry_date","exit_date","forward_return",
                   "mfe","mae","first_touch","status","receipt_sha256","available_at",
                   "up_barrier","down_barrier"),
        "category": "未来路径结果", "policy": "OUTCOME_VALIDATION_NOT_MODEL_INPUT",
        "description": "未来收益与路径结果，仅用于结果验证，不是预测输入。",
    },
    "source_receipts": {
        "table": "l1_market_source_receipts", "date": "fetched_at",
        "fields": ("receipt_sha256","provider","dataset","fetched_at","available_at",
                   "observed_start","observed_end","raw_object_path",
                   "ingested_at"),
        "category": "原始来源回执", "policy": "PROVENANCE_ONLY",
        "description": "原始数据来源回执索引，不返回原始响应正文。",
    },
    "maintenance_runs": {
        "table": "l1_market_run_log", "date": "started_at",
        "fields": ("run_id","command","started_at","completed_at","status"),
        "category": "维护运行记录", "policy": "OPERATIONAL_EVIDENCE_ONLY",
        "description": "L1 数据扫描与维护运行日志。",
    },
}


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_value(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_metadata(value):
    raw = _json_object(value)
    allowed = {
        "feed", "source", "scope", "response_shape", "observation_mode",
        "requested_symbols", "returned_symbols", "expected_n", "coverage_n",
        "coverage_pct", "batch_count", "batch_error_count", "published_at",
        "fetched_at", "latest_observation", "latency_seconds", "status",
    }
    result = {}
    for key in allowed:
        item = raw.get(key)
        if isinstance(item, str):
            if "://" in item or any(marker in item.lower()
                    for marker in ("token=", "apikey=", "api_key", "secret=", "authorization")):
                continue
            result[key] = item[:160]
        elif isinstance(item, (int, float, bool, type(None))):
            result[key] = item
    return result


def _safe_counts(value):
    raw = _json_object(value)
    return {str(key): item for key, item in raw.items()
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(key)) and
            isinstance(item, (int, float, bool))}


def _safe_errors(value):
    raw = _json_object(value)
    result = {}
    for key, item in raw.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(key)):
            continue
        if isinstance(item, str) and re.fullmatch(r"[A-Z0-9_]{2,80}", item):
            result[str(key)] = item
        else:
            result[str(key)] = "DETAIL_REDACTED"
    return result


def _json_object(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _read_only_db(path):
    from .store import duckdb
    return duckdb.connect(str(path), read_only=True)


def _table_names(db):
    return {row[0] for row in db.execute("SHOW TABLES").fetchall()}


def _table_summary(db, resource_id, spec):
    table = spec["table"]
    columns = {row[1]: row[2] for row in db.execute(
        f"PRAGMA table_info('{table}')").fetchall()}
    date_col = spec["date"] if spec["date"] in columns else None
    row_count = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    first_date = last_date = latest_observed = latest_available = latest_fetched = latest_ingested = None
    if date_col and row_count:
        first_date, last_date = db.execute(
            f'SELECT min("{date_col}"), max("{date_col}") FROM "{table}"'
        ).fetchone()
    for field, target in (
        ("observed_at","latest_observed"), ("known_at","latest_observed"),
        ("schedule_known_at","latest_observed"),
        ("available_at","latest_available"), ("fetched_at","latest_fetched"),
        ("ingested_at","latest_ingested"),
    ):
        if field in columns and row_count:
            value = db.execute(
                f'SELECT max("{field}") FROM "{table}"').fetchone()[0]
            if target == "latest_observed":
                latest_observed = value if latest_observed is None else max(latest_observed, value)
            elif target == "latest_available":
                latest_available = value
            elif target == "latest_fetched":
                latest_fetched = value
            else:
                latest_ingested = value
    if latest_fetched is None and "receipt_sha256" in columns and "l1_market_source_receipts" in _table_names(db):
        latest_fetched = db.execute(
            f'''SELECT max(r.fetched_at) FROM "{table}" d
                JOIN l1_market_source_receipts r USING(receipt_sha256)'''
        ).fetchone()[0]
    unique_count = None
    if resource_id == "market_bars" and row_count:
        unique_count = db.execute(
            f'SELECT count(DISTINCT (session_date, security_id, provider, price_basis)) FROM "{table}"'
        ).fetchone()[0]
    elif resource_id == "market_observations" and row_count:
        unique_count = db.execute(
            f'SELECT count(DISTINCT (session_date, feature_id)) FROM "{table}"'
        ).fetchone()[0]
    elif resource_id == "security_features" and row_count:
        unique_count = db.execute(
            f'SELECT count(DISTINCT (session_date, security_id, feature_id)) FROM "{table}"'
        ).fetchone()[0]
    symbols = None
    if "symbol" in columns and row_count:
        symbols = db.execute(f'SELECT count(DISTINCT symbol) FROM "{table}"').fetchone()[0]
    return {
        "dataset_id": resource_id, "name": spec["category"],
        "description": spec["description"], "category": spec["category"],
        "path": _L1_DB.as_posix(), "table": table,
        "status": "COLLECTED" if row_count else "EMPTY",
        "physical_rows": row_count, "unique_rows": unique_count,
        "symbols": symbols, "first_observation": _iso(first_date),
        "last_observation": _iso(last_date),
        "latest_observed_at_utc": _iso(latest_observed),
        "latest_available_at_utc": _iso(latest_available),
        "latest_fetched_at_utc": _iso(latest_fetched),
        "latest_ingested_at_utc": _iso(latest_ingested),
        "use_policy": spec["policy"], "cadence": "按来源实际频率",
        "preview_supported": True, "limitations": [spec["policy"]],
        "columns": [{"name": name, "type": kind} for name, kind in columns.items()],
    }


def _source_rows(db=None):
    tables = _table_names(db) if db is not None else set()
    health = {}
    if "l1_market_source_health" in tables:
        rows = db.execute("""
            SELECT source_key, asof_session, fetched_at, status, error_code,
                   receipt_sha256, metadata_json
            FROM l1_market_source_health
            QUALIFY row_number() OVER (
                PARTITION BY source_key ORDER BY fetched_at DESC, asof_session DESC
            ) = 1
        """).fetchall()
        for row in rows:
            health[row[0]] = {
                "asof_session": _iso(row[1]), "fetched_at_utc": _iso(row[2]),
                "run_status": row[3], "error_code": row[4],
                "receipt_sha256": row[5], "metadata": _safe_metadata(row[6]),
            }
    result = []
    for source in SOURCES:
        observed = health.get(source.key)
        run_status = observed["run_status"] if observed else "NOT_OBSERVED"
        result.append({
            "source_key": source.key, "name": source.name,
            "provider_type": source.provider_type, "datasets": list(source.datasets),
            "cadence": source.cadence, "scope": source.scope,
            "access": source.access, "code_status": source.code_status,
            "pit_status": source.pit_status, "limitation": source.limitation,
            "run_status": run_status,
            "asof_session": observed["asof_session"] if observed else None,
            "fetched_at_utc": observed["fetched_at_utc"] if observed else None,
            "error_code": observed["error_code"] if observed else None,
            "receipt_sha256": observed["receipt_sha256"] if observed else None,
            "metadata": observed["metadata"] if observed else {},
        })
    return result


def warehouse_overview(root):
    root = Path(root).resolve()
    lock = root / _MAINTENANCE_LOCK
    db_path = root / _L1_DB
    if lock.is_file():
        return {"status": "MAINTENANCE_RUNNING", "read_only": True,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "datasets": [], "sources": _source_rows(), "attention": [],
                "limitations": ["数据维护锁生效，暂不并发读取仓库。"]}
    try:
        datasets = []
        sources = []
        if db_path.is_file():
            with _read_only_db(db_path) as db:
                tables = _table_names(db)
                for resource_id, spec in _L1_RESOURCES.items():
                    if spec["table"] in tables:
                        datasets.append(_table_summary(db, resource_id, spec))
                sources = _source_rows(db)
        else:
            sources = _source_rows()

        # Reuse the existing fixed, read-only database catalogue. It does not
        # hash or enumerate the raw-object cache on every page request.
        category_by_id = {
            "market_prices":"行情数据", "yahoo_research_prices":"研究行情",
            "corporate_actions":"公司行为", "sec_filings":"公司申报",
            "sec_candidates":"公司财务候选", "classic_factors":"经典因子",
        }
        for dataset_id, spec in DATASETS.items():
            item = inspect_database(root, dataset_id, spec)
            datasets.append({
                "dataset_id":dataset_id, "name":item.get("name") or dataset_id,
                "category":category_by_id.get(dataset_id,"研究数据"),
                "description":item.get("missing_reason") or "既有权威数据库资产。",
                "path":item.get("path"), "table":item.get("table"),
                "source":item.get("source"), "cadence":item.get("cadence"),
                "status":item.get("status","BLOCKED"),
                "physical_rows":item.get("rows"), "unique_rows":item.get("latest_rows"),
                "symbols":item.get("symbols"), "first_observation":item.get("first_date"),
                "last_observation":item.get("last_date"),
                "latest_available_at_utc":None, "latest_ingested_at_utc":None,
                "use_policy":item.get("use_policy","UNAVAILABLE"),
                "preview_supported":dataset_id in _CATALOG_PREVIEWS,
                "limitations":[item.get("missing_reason") or item.get("use_policy","")],
            })
        for dataset_id, (name, reason, repair) in MISSING.items():
            datasets.append({
                "dataset_id":dataset_id, "name":name, "category":"未满足依赖",
                "description":reason, "path":None, "table":None, "source":None,
                "cadence":"EVIDENCE_DEPENDENT", "status":"BLOCKED",
                "physical_rows":None, "unique_rows":None, "symbols":None,
                "first_observation":None, "last_observation":None,
                "latest_available_at_utc":None, "latest_ingested_at_utc":None,
                "use_policy":"UNAVAILABLE", "preview_supported":False,
                "limitations":[reason,repair],
            })

        attention = []
        for source in sources:
            status = source["run_status"]
            if status in {"FAILED", "BLOCKED", "STALE", "PARTIAL"}:
                attention.append({
                    "id": source["source_key"], "severity":
                        "high" if status in {"FAILED", "BLOCKED"} else "medium",
                    "status": status, "title": source["name"],
                    "reason": source["error_code"] or source["limitation"],
                    "last_observed_at": source["fetched_at_utc"],
                })
        for dataset in datasets:
            if dataset["dataset_id"] not in MISSING and dataset["status"] in {"BLOCKED", "EMPTY"}:
                attention.append({
                    "id":dataset["dataset_id"], "severity":"medium",
                    "status":dataset["status"], "title":dataset["name"],
                    "reason":(dataset.get("limitations") or ["DATASET_NOT_AVAILABLE"])[0],
                    "last_observed_at":None,
                })
        total_rows = sum(int(item["physical_rows"] or 0) for item in datasets)
        populated = sum(bool(item["physical_rows"]) for item in datasets)
        return {
            "status": "OBSERVED" if db_path.is_file() or populated else "PARTIAL",
            "read_only": True,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "database_path": _L1_DB.as_posix() if db_path.is_file() else None,
            "summary": {"datasets": len(datasets), "populated_datasets": populated,
                        "physical_rows": total_rows, "attention_count": len(attention)},
            "datasets": datasets, "sources": sources, "attention": attention,
            "maintenance": {"status": "IDLE"},
            "policy": {"read_only": True, "provider_requests": False,
                       "historical_pit_verified": False, "forecast_eligible": False,
                       "trade_eligible": False},
            "limitations": ["注册代码状态与真实运行状态分开展示。",
                            "当前资产/ETF 代理不代表完整全市场历史广度。",
                            "reference_history 与 path_outcomes 不计入实时模型输入。",
                            "非 L1 数据库暂不提供在线样本预览。"],
        }
    except Exception as exc:
        return {"status": "READ_FAILED", "read_only": True,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "datasets": [], "sources": [], "attention": [],
                "error_code": "WAREHOUSE_READ_FAILED_" + type(exc).__name__}


def warehouse_dataset(root, dataset_id):
    if dataset_id not in _L1_RESOURCES and dataset_id not in DATASETS and dataset_id not in MISSING:
        raise ValueError("WAREHOUSE_DATASET_NOT_ALLOWED")
    overview = warehouse_overview(root)
    dataset = next((item for item in overview.get("datasets", [])
                    if item["dataset_id"] == dataset_id), None)
    if dataset is None:
        return {"status": overview["status"], "dataset_id": dataset_id}
    return {"status": "OBSERVED", "dataset": dataset,
            "policy": {"read_only": True,
                       "preview_supported": bool(dataset.get("preview_supported"))}}


def warehouse_preview(root, dataset_id, *, limit=20, offset=0,
                      symbol=None, start=None, end=None):
    spec = _L1_RESOURCES.get(dataset_id)
    catalog_spec = _CATALOG_PREVIEWS.get(dataset_id)
    if spec is None and catalog_spec is None:
        if dataset_id in DATASETS or dataset_id in MISSING:
            return {"status":"PREVIEW_NOT_SUPPORTED","dataset_id":dataset_id,
                    "rows":[],"total":None,"read_only":True}
        raise ValueError("WAREHOUSE_DATASET_NOT_ALLOWED")
    if isinstance(limit, bool) or not 1 <= int(limit) <= 50:
        raise ValueError("WAREHOUSE_LIMIT_INVALID")
    if isinstance(offset, bool) or not 0 <= int(offset) <= 100000:
        raise ValueError("WAREHOUSE_OFFSET_INVALID")
    for value in (start, end):
        if value is not None and date.fromisoformat(value).isoformat() != value:
            raise ValueError("WAREHOUSE_DATE_INVALID")
    if start and end and start > end:
        raise ValueError("WAREHOUSE_DATE_RANGE_INVALID")
    if symbol is not None and not _SYMBOL.fullmatch(symbol.upper()):
        raise ValueError("WAREHOUSE_SYMBOL_INVALID")
    root = Path(root).resolve()
    if (root / _MAINTENANCE_LOCK).is_file():
        return {"status": "MAINTENANCE_RUNNING", "rows": [], "total": None}
    if catalog_spec is not None:
        path = root / catalog_spec["path"]
        if not path.is_file():
            return {"status":"NOT_CREATED","dataset_id":dataset_id,"rows":[],"total":0}
        try:
            with _read_only_db(path) as db:
                if catalog_spec["table"] not in _table_names(db):
                    return {"status":"NOT_CREATED","dataset_id":dataset_id,"rows":[],"total":0}
                table=catalog_spec["table"]
                columns={row[1] for row in db.execute(
                    f"PRAGMA table_info('{table}')").fetchall()}
                fields=[name for name in catalog_spec["fields"] if name in columns]
                clauses=[catalog_spec["where"]]
                params=[]
                if symbol:
                    if not catalog_spec["symbol"] or "symbol" not in columns:
                        raise ValueError("WAREHOUSE_SYMBOL_FILTER_UNSUPPORTED")
                    clauses.append("symbol=?");params.append(symbol.upper())
                if start:
                    clauses.append(f'"{catalog_spec["date"]}">=?');params.append(start)
                if end:
                    clauses.append(f'"{catalog_spec["date"]}"<=?');params.append(end)
                where=" WHERE "+" AND ".join(clauses)
                total=db.execute(f'SELECT count(*) FROM "{table}"{where}',params).fetchone()[0]
                projection=",".join('"'+name+'"' for name in fields)
                rows=db.execute(
                    f'SELECT {projection} FROM "{table}"{where} '
                    f'ORDER BY "{catalog_spec["date"]}" DESC LIMIT ? OFFSET ?',
                    [*params,int(limit),int(offset)]
                ).fetchall()
                return {"status":"OBSERVED","dataset_id":dataset_id,
                    "columns":fields,"rows":[
                        {name:_json_value(value) for name,value in zip(fields,row)}
                        for row in rows],
                    "total":total,"limit":int(limit),"offset":int(offset),
                    "read_only":True,"table":table,
                    "use_policy":catalog_spec["policy"]}
        except ValueError:
            raise
        except Exception as exc:
            return {"status":"READ_FAILED","rows":[],"total":None,
                    "error_code":"WAREHOUSE_PREVIEW_FAILED_"+type(exc).__name__}
    path = root / _L1_DB
    if not path.is_file():
        return {"status": "NOT_CREATED", "rows": [], "total": 0}
    try:
        with _read_only_db(path) as db:
            tables = _table_names(db)
            table = spec["table"]
            if table not in tables:
                return {"status": "NOT_CREATED", "rows": [], "total": 0}
            columns = {row[1] for row in db.execute(f"PRAGMA table_info('{table}')").fetchall()}
            fields = [name for name in spec["fields"] if name in columns]
            clauses, params = [], []
            if symbol:
                if "symbol" not in columns:
                    raise ValueError("WAREHOUSE_SYMBOL_FILTER_UNSUPPORTED")
                clauses.append("symbol=?"); params.append(symbol.upper())
            date_col = spec["date"]
            if start:
                if date_col not in columns:
                    raise ValueError("WAREHOUSE_DATE_FILTER_UNSUPPORTED")
                clauses.append(f'"{date_col}">=?'); params.append(start)
            if end:
                if date_col not in columns:
                    raise ValueError("WAREHOUSE_DATE_FILTER_UNSUPPORTED")
                clauses.append(f'"{date_col}"<=?'); params.append(end)
            where = " WHERE " + " AND ".join(clauses) if clauses else ""
            total = db.execute(f'SELECT count(*) FROM "{table}"{where}', params).fetchone()[0]
            projection = ",".join('"' + name + '"' for name in fields)
            rows = db.execute(
                f'SELECT {projection} FROM "{table}"{where} '
                f'ORDER BY "{date_col}" DESC LIMIT ? OFFSET ?',
                [*params, int(limit), int(offset)]
            ).fetchall()
            return {"status": "OBSERVED", "dataset_id": dataset_id,
                    "columns": fields, "rows": [
                        {name: _json_value(value) for name, value in zip(fields, row)}
                        for row in rows
                    ],
                    "total": total, "limit": int(limit), "offset": int(offset),
                    "read_only": True, "table": table}
    except ValueError:
        raise
    except Exception as exc:
        return {"status": "READ_FAILED", "rows": [], "total": None,
                "error_code": "WAREHOUSE_PREVIEW_FAILED_" + type(exc).__name__}


def warehouse_runs(root, *, limit=20):
    if isinstance(limit, bool) or not 1 <= int(limit) <= 50:
        raise ValueError("WAREHOUSE_RUN_LIMIT_INVALID")
    root = Path(root).resolve()
    if (root / _MAINTENANCE_LOCK).is_file():
        return {"status":"MAINTENANCE_RUNNING","runs":[]}
    path = root / _L1_DB
    if not path.is_file():
        return {"status":"NOT_CREATED","runs":[]}
    with _read_only_db(path) as db:
        if "l1_market_run_log" not in _table_names(db):
            return {"status": "NOT_CREATED", "runs": []}
        rows = db.execute("""
            SELECT run_id, command, started_at, completed_at, status,
                   counts_json, errors_json
            FROM l1_market_run_log ORDER BY started_at DESC LIMIT ?
        """, [int(limit)]).fetchall()
    return {"status": "OBSERVED", "runs": [{
        "run_id": row[0],
        "command": row[1] if isinstance(row[1], str) and re.fullmatch(r"[A-Za-z0-9_:-]{1,80}", row[1]) else "COMMAND_REDACTED",
        "started_at_utc": _iso(row[2]),
        "completed_at_utc": _iso(row[3]), "status": row[4],
        "counts": _safe_counts(row[5]), "errors": _safe_errors(row[6]),
    } for row in rows]}
