"""Data-layer API routes under ``/api/v1/data/``."""

import json
import sqlite3
from datetime import date
from urllib.parse import parse_qs

from quant_research.policy import PolicyError


def _single_params(query_string: str) -> dict[str, str]:
    query = parse_qs(query_string, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("Repeated query parameter")
    return {key: values[0] for key, values in query.items()}


def handle(path: str, query_string: str, console):
    """Return ``(status, body[, mime])`` or ``None`` when no route matches."""
    if not path.startswith("/api/v1/data/"):
        return None
    try:
        if path in {"/api/v1/data/universe/asof", "/api/v1/data/universe/history", "/api/v1/data/universe/resolve"}:
            from quant_research.data.forward_universe import asof_directory, observation_changes, resolve_symbols

            params = _single_params(query_string)
            if path.endswith("/asof"):
                if set(params) - {"asof", "q", "state", "limit", "offset"}:
                    raise ValueError("Unexpected asof parameter")
                return 200, asof_directory(
                    console.root,
                    asof_utc=params.get("asof") or None,
                    q=params.get("q", ""),
                    state=params.get("state", "candidate"),
                    limit=int(params.get("limit", "30")),
                    offset=int(params.get("offset", "0")),
                )
            if path.endswith("/history"):
                if set(params) - {"limit"}:
                    raise ValueError("Unexpected history parameter")
                return 200, observation_changes(console.root, limit=int(params.get("limit", "30")))
            if set(params) - {"symbols", "asof"} or not params.get("symbols"):
                raise ValueError("Symbols required")
            return 200, resolve_symbols(console.root, params["symbols"].split(","), asof_utc=params.get("asof") or None)

        if path == "/api/v1/data/actions/pages":
            from quant_research.data.action_pages import audit_action_pages

            params = _single_params(query_string)
            if set(params) - {"symbols", "start", "end", "page_size", "max_pages", "asof"} or not {
                "symbols",
                "start",
                "end",
            } <= set(params):
                raise ValueError("Explicit exact archived source query required")
            return 200, audit_action_pages(
                console.root,
                symbols=params["symbols"].split(","),
                start=params["start"],
                end=params["end"],
                page_size=int(params.get("page_size", "1000")),
                max_pages=int(params.get("max_pages", "100")),
                asof_utc=params.get("asof") or None,
            )

        if path == "/api/v1/data/actions/audit":
            from quant_research.data.action_audit import audit_events

            params = _single_params(query_string)
            if set(params) - {"asof", "symbol", "database", "limit", "offset"}:
                raise ValueError("Unapproved event audit parameters")
            return 200, audit_events(
                console.root,
                asof_utc=params.get("asof") or None,
                symbol=params.get("symbol", ""),
                database=params.get("database", "all"),
                limit=int(params.get("limit", "30")),
                offset=int(params.get("offset", "0")),
            )

        if path == "/api/v1/data/assets":
            from quant_research.data.assets import inventory

            params = _single_params(query_string)
            if set(params) - {"q", "status", "tradable", "limit", "offset"}:
                raise ValueError("Unexpected asset query parameter")
            return 200, inventory(
                console.root,
                q=params.get("q", ""),
                status=params.get("status", "all"),
                tradable=params.get("tradable", "all"),
                limit=int(params.get("limit", "30")),
                offset=int(params.get("offset", "0")),
            )

        if path == "/api/v1/data/close-snapshots":
            from quant_research.data.close_snapshot import read_snapshot

            params = _single_params(query_string)
            if set(params) - {"asof"}:
                return 400, {"status": "BLOCKED", "code": "INVALID_CLOSE_SNAPSHOT_QUERY"}
            asof = params.get("asof")
            if asof is not None:
                try:
                    if date.fromisoformat(asof).isoformat() != asof:
                        raise ValueError("Expected ISO date")
                except ValueError:
                    return 400, {"status": "BLOCKED", "code": "INVALID_CLOSE_SNAPSHOT_QUERY"}
            return 200, read_snapshot(console.root, asof)

        if path.startswith("/api/v1/data/catalog"):
            from quant_research.data.catalog import catalog_artifact

            if query_string:
                raise ValueError("Catalog route has no query parameters")
            names = {
                "/api/v1/data/catalog": "catalog.json",
                "/api/v1/data/catalog/datasets.csv": "datasets.csv",
                "/api/v1/data/catalog/cache_index.csv": "cache_index.csv",
                "/api/v1/data/catalog/excluded_stores.csv": "excluded_stores.csv",
            }
            if path not in names:
                return 404, {"status": "NOT_FOUND"}
            body = catalog_artifact(console.root, names[path])
            if names[path] == "catalog.json":
                data = json.loads(body)
                data.pop("cache_index", None)
                return 200, data
            return 200, body, "text/csv; charset=utf-8"
    except PolicyError as exc:
        return 409, exc.payload()
    except KeyError:
        if path == "/api/v1/data/close-snapshots":
            return 409, {"status": "BLOCKED", "code": "CLOSE_SNAPSHOT_INVALID"}
        if path.startswith("/api/v1/data/catalog"):
            return 409, {"status": "BLOCKED", "code": "CATALOG_INVALID"}
        return 400, {"status": "BLOCKED", "code": "DATA_QUERY_INVALID"}
    except (sqlite3.Error, ValueError, TypeError, OSError):
        if path.startswith("/api/v1/data/universe/"):
            return 400, {"status": "BLOCKED", "code": "UNIVERSE_QUERY_INVALID"}
        if path == "/api/v1/data/actions/pages":
            return 400, {"status": "BLOCKED", "code": "ACTION_PAGE_QUERY_INVALID"}
        if path == "/api/v1/data/actions/audit":
            return 400, {"status": "BLOCKED", "code": "ACTION_AUDIT_QUERY_INVALID"}
        if path == "/api/v1/data/assets":
            return 400, {"status": "BLOCKED", "code": "ASSET_QUERY_INVALID"}
        if path == "/api/v1/data/close-snapshots":
            return 409, {"status": "BLOCKED", "code": "CLOSE_SNAPSHOT_INVALID"}
        if path.startswith("/api/v1/data/catalog"):
            return 409, {"status": "BLOCKED", "code": "CATALOG_INVALID"}
        return 400, {"status": "BLOCKED", "code": "DATA_QUERY_INVALID"}
    return None
