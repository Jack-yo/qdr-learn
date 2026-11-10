"""Read-only G8.2 audit of *observed* corporate-event source vintages.

Checks archived Alpaca corporate-action events against the original response bytes,
request receipts, observation times and (when available) G7 asset UUID observations.
A verified case is NOT full historical coverage, legal issuer identity, PIT
publication, an action entitlement, or a cash-settlement certification.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode

from quant_research.data.forward_universe import _asof
from quant_research.policy import PolicyError

SHA = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,19}\Z")
ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"
DATABASES = {"g2": "g2_evidence.duckdb", "maintenance": "real_v21.duckdb", "research": "research.duckdb"}


def _safe_time(value):
    if not isinstance(value, str):
        raise ValueError("Timezone-aware source timestamp required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Naive source timestamp rejected")
    return result.astimezone(timezone.utc)


def _receipt_index(raw_root):
    """Index *actual archived* fetch receipts, never request cache pointers."""
    root = Path(raw_root) / "receipts"
    if not root.is_dir():
        return {}
    index = {}
    for path in root.glob("*.json"):
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(receipt, dict) or receipt.get("url") != ENDPOINT:
                continue
            digest = receipt.get("sha256")
            params = receipt.get("params")
            if not isinstance(digest, str) or not SHA.fullmatch(digest) or not isinstance(params, dict):
                continue
            actual_request = hashlib.sha256((ENDPOINT + "?" + urlencode(sorted(params.items()))).encode()).hexdigest()
            if receipt.get("request_key") != actual_request:
                continue
            _safe_time(receipt.get("fetched_at"))
            index.setdefault(digest, []).append(receipt)
        except (OSError, ValueError, TypeError):
            continue
    return index


def _event_day(payload):
    if not isinstance(payload, dict):
        return None
    for key in ("ex_date", "process_date", "payable_date"):
        day = payload.get(key)
        if isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            return day
    return None


def _audit_record(record, raw_root, receipts, cutoff):
    """Independently cross-check one database row with immutable source bytes."""
    result = {"event_id": str(record.get("provider_event_id", "")),
              "event_type": str(record.get("event_type", "")),
              "symbol": str(record.get("symbol") or ""),
              "raw_sha256": record.get("raw_sha256"),
              "observed_at_utc": record.get("retrieved_at_utc"),
              "event_day": _event_day(record.get("payload") or {}),
              "source_verified": False, "receipt_verified": False,
              "event_published_at_verified": False,
              "complete_action_history_verified": False,
              "issuer_identity_verified": False,
              "historical_pit_eligible": False,
              "settlement_eligible": False,
              "real_orders_enabled": False}
    reasons = []
    try:
        if record.get("provider") != "ALPACA" or record.get("source_endpoint") != ENDPOINT:
            raise ValueError("SOURCE_ENDPOINT_UNAPPROVED")
        digest = record.get("raw_sha256")
        if not isinstance(digest, str) or not SHA.fullmatch(digest):
            raise ValueError("SOURCE_DIGEST_INVALID")
        observed = _safe_time(record.get("retrieved_at_utc"))
        available = _safe_time(record.get("available_at_utc"))
        if observed != available or observed > cutoff:
            raise ValueError("SOURCE_TIME_AFTER_CUTOFF_OR_MISMATCH")
        if record.get("published_at_utc") is not None:
            # The collected provider response did not verify publication time.
            raise ValueError("UNVERIFIED_HISTORICAL_PUBLICATION_CLAIM")
        path = Path(raw_root) / "objects" / digest
        payload_bytes = path.read_bytes()
        if hashlib.sha256(payload_bytes).hexdigest() != digest:
            raise ValueError("SOURCE_RAW_HASH_MISMATCH")
        body = json.loads(payload_bytes)
        if not isinstance(body, dict):
            raise ValueError("SOURCE_SCHEMA_INVALID")
        groups = body.get("corporate_actions")
        if not isinstance(groups, dict):
            raise ValueError("SOURCE_SCHEMA_INVALID")
        events = groups.get(record.get("event_type"))
        if not isinstance(events, list):
            raise ValueError("EVENT_GROUP_MISSING")
        matches = [x for x in events if isinstance(x, dict) and x.get("id") == record.get("provider_event_id")]
        if len(matches) != 1 or matches[0] != record.get("payload"):
            raise ValueError("EVENT_NOT_IN_ORIGINAL_SOURCE")
        if (matches[0].get("symbol") or matches[0].get("old_symbol") or matches[0].get("acquiree_symbol")) != record.get("symbol"):
            raise ValueError("EVENT_SYMBOL_MISMATCH")
        result["source_verified"] = True
        if body.get("next_page_token"):
            reasons.append("SOURCE_PAGE_CHAIN_UNPROVEN")
        valid_receipts = []
        for r in receipts.get(digest, []):
            try:
                params = r["params"]
                if (_safe_time(r["fetched_at"]) != observed
                        or result["symbol"] not in str(params.get("symbols", "")).split(",")):
                    continue
                day = result["event_day"]
                if day is not None and not (str(params.get("start", "")) <= day <= str(params.get("end", ""))):
                    continue
                valid_receipts.append(r)
            except (ValueError, TypeError, KeyError):
                continue
        if not valid_receipts:
            reasons.append("AUTHENTICATED_REQUEST_RECEIPT_MISSING")
        else:
            result["receipt_verified"] = True
            result["source_request_sha256"] = valid_receipts[0]["request_key"]
            if valid_receipts[0]["params"].get("page_token"):
                reasons.append("NON_FIRST_ACTION_PAGE_NO_CHAIN_PROOF")
    except (OSError, ValueError, TypeError, KeyError, UnicodeDecodeError, AttributeError) as exc:
        reasons.append(str(exc) if isinstance(exc, ValueError) else "SOURCE_BYTES_UNAVAILABLE_OR_INVALID")
    if not result["source_verified"] or not result["receipt_verified"]:
        reasons.append("SOURCE_PROVENANCE_INCOMPLETE")
    reasons += ["NO_VERIFIED_EVENT_PUBLICATION_TIME", "NO_COMPLETE_ACTION_COVERAGE",
                "NO_AS_FILED_ISSUER_SECURITY_BRIDGE", "NO_SETTLEMENT_ENTITLEMENT_PROOF"]
    result["missing_evidence"] = list(dict.fromkeys(reasons))
    result["status"] = ("SOURCE_EVENT_VERIFIED_OBSERVATION_ONLY"
                         if result["source_verified"] and result["receipt_verified"]
                         else "BLOCKED_SOURCE_EVIDENCE")
    return result


def _read_archives(root, cutoff, symbol, databases, max_rows):
    """Read-only DuckDB access; no migrations, inserts, capability flags or orders."""
    if not any((Path(root) / "data" / DATABASES[name]).is_file() for name in databases):
        raise PolicyError("NO_CORPORATE_EVENT_ARCHIVE",
                          "No real corporate-event database was found; collect G2 events first",
                          ["g2-audit or maintain-data real provider cache"])
    try:
        import duckdb
    except ImportError as exc:
        raise PolicyError("DUCKDB_REQUIRED", "Corporate-event audit needs the installed DuckDB runtime") from exc
    rows, available = [], []
    for name in databases:
        path = Path(root) / "data" / DATABASES[name]
        if not path.is_file():
            continue
        with duckdb.connect(str(path), read_only=True) as db:
            tables = {r[0] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
            if "corporate_event_versions" not in tables:
                continue
            available.append(name)
            records = db.execute("""SELECT record_json,provider,event_id,raw_sha256,event_type,symbol,observed_at
                   FROM corporate_event_versions WHERE observed_at<=? AND (?='' OR symbol=?)
                   ORDER BY observed_at DESC LIMIT ?""",
                [cutoff, symbol, symbol, max_rows]).fetchall()
            for content, provider, event_id, sha, kind, code, observed in records:
                try:
                    obj = json.loads(content)
                    if not isinstance(obj, dict):
                        raise ValueError
                except (TypeError, ValueError):
                    obj = {}
                # Must match the stored relational fields; record_json alone cannot certify them.
                try:
                    timestamp_valid = (isinstance(obj.get("retrieved_at_utc"), str)
                                       and _safe_time(obj["retrieved_at_utc"]) == observed.astimezone(timezone.utc))
                except (ValueError, TypeError, AttributeError):
                    timestamp_valid = False
                if (obj.get("provider") != provider or obj.get("provider_event_id") != event_id
                        or obj.get("raw_sha256") != sha or obj.get("event_type") != kind
                        or obj.get("symbol") != code
                        or not timestamp_valid):
                    obj = {"provider_event_id": event_id, "event_type": kind, "symbol": code,
                           "raw_sha256": sha, "retrieved_at_utc": observed.isoformat(),
                           "_relational_conflict": True}
                rows.append(obj)
    if not available:
        raise PolicyError("NO_CORPORATE_EVENT_ARCHIVE",
                          "No existing verified corporate-event version database; run the real G2 collection first",
                          ["g2-audit or maintain-data with real provider cache"])
    # A record in two physical DBs is a *single source vintage*.
    unique = {}
    for item in rows:
        key = (item.get("provider_event_id"), item.get("raw_sha256"))
        unique.setdefault(key, item)
    return list(unique.values()), available


def audit_events(project_root, *, asof_utc=None, symbol="", database="all", limit=30, offset=0):
    """Review actual event vintages known by cutoff. This API never grants PIT."""
    if (not isinstance(symbol, str) or (symbol and not SYMBOL.fullmatch(symbol))
            or database not in {*DATABASES, "all"}
            or type(limit) is not int or not 1 <= limit <= 100
            or type(offset) is not int or not 0 <= offset <= 100000):
        raise PolicyError("ACTION_AUDIT_QUERY_INVALID", "Use an uppercase symbol, approved DB, and valid pagination")
    cutoff = _asof(asof_utc)
    names = list(DATABASES) if database == "all" else [database]
    # Page up to the offset, then de-duplicate before slicing.
    records, sources = _read_archives(project_root, cutoff, symbol, names, offset + limit + 300)
    records.sort(key=lambda x: x.get("retrieved_at_utc") or "", reverse=True)
    selected = records[offset:offset + limit]
    receipts = _receipt_index(Path(project_root) / "data/raw")
    result = []
    for item in selected:
        if item.get("_relational_conflict"):
            result.append({"event_id": item["provider_event_id"], "symbol": item.get("symbol"),
                           "status": "BLOCKED_SOURCE_EVIDENCE", "source_verified": False,
                           "receipt_verified": False, "historical_pit_eligible": False,
                           "settlement_eligible": False,
                           "missing_evidence": ["DATABASE_EVENT_ROW_DIFFERS_FROM_ORIGINAL_JSON"]})
        else:
            result.append(_audit_record(item, Path(project_root) / "data/raw", receipts, cutoff))
    # Attach a *contemporaneously observed* provider UUID if an authenticated G7
    # snapshot existed by the user-requested cutoff. Never attach this UUID to
    # historic event dates or claim a share-class/issuer bridge.
    provider_snapshot = {"status": "BLOCKED_NO_ASOF_ASSET_SNAPSHOT"}
    try:
        from collections import Counter
        from quant_research.data.forward_universe import _select
        snapshot, _, _ = _select(project_root, cutoff)
        counts = Counter(a["symbol"] for a in snapshot["rows"])
        mapping = {a["symbol"]:a["id"] for a in snapshot["rows"] if counts[a["symbol"]] == 1}
        provider_snapshot = {"status": "OBSERVED_ONLY_NOT_HISTORICAL_IDENTITY",
                             "snapshot_id": snapshot["snapshot_id"],
                             "observed_at_utc": snapshot["observed_at"].isoformat()}
        for item in result:
            item["provider_asset_uuid_at_query_cutoff"] = mapping.get(item.get("symbol"))
            item["ticker_ambiguous_at_cutoff"] = counts[item.get("symbol")] > 1
            item["asset_uuid_not_a_permanent_issuer_id"] = True
    except PolicyError as exc:
        provider_snapshot["code"] = exc.code
    return {
        "status": "SOURCE_CASE_AUDIT_ONLY_NOT_PIT",
        "source": "ALPACA", "asof_utc": cutoff.isoformat(), "symbol": symbol or None,
        "databases_read": sources, "unique_vintages_seen": len(records),
        "provider_asset_snapshot": provider_snapshot,
        "offset": offset, "limit": limit, "events": result,
        "source_verified_count": sum(x.get("source_verified", False) and x.get("receipt_verified", False) for x in result),
        "blocked_source_count": sum(x["status"] == "BLOCKED_SOURCE_EVIDENCE" for x in result),
        "event_coverage": "BLOCKED", "historical_identity": "BLOCKED",
        "historical_pit_eligible": False, "settlement_eligible": False,
        "real_orders_enabled": False,
        "missing_evidence": ["effective-dated issuer/share-class identity",
                             "all-page corporate-action history and complete coverage",
                             "actual historical event publication time",
                             "independent split/dividend/delist entitlement and cash accounting",
                             "historical delisted and renamed security universe"],
    }
