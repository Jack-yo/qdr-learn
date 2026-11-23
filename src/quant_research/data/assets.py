"""Read-only, prospectively observed Alpaca US-equity asset directory.

Only real authenticated GET /v2/assets responses enter this archive. Neither
historical constituent eligibility nor permanent issuer identity is inferred.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from collections import Counter
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from quant_research.policy import PolicyError

ENDPOINTS = {
    "paper": "https://paper-api.alpaca.markets/v2/assets",
    "live": "https://api.alpaca.markets/v2/assets",
}
SCHEMA = "ALPACA_ASSETS_OBSERVED_V1"
MAX_BYTES = 20 * 1024 * 1024
# Alpaca's ``us_equity`` catalogue includes provider identifiers such as
# CUSIP-like ``98400U111`` and retained symbols such as ``VEAC_DELISTED``.
# They are archived as current vendor identifiers, not classified as common
# stock tickers.  Keep the validation ASCII/path-safe without discarding those
# legitimate provider records; downstream research-symbol selection remains
# separately strict and explicit.
SYMBOL = re.compile(r"(?=.{1,32}\Z)(?=.*[A-Za-z0-9])[A-Za-z0-9_.\-]+\Z")
SHA = re.compile(r"[0-9a-f]{64}")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError("ASSET_OBSERVATION_TIME_INVALID", "Missing or invalid actual UTC observation time") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise PolicyError("ASSET_OBSERVATION_TIME_INVALID", "Asset observation requires a timezone-aware timestamp")
    return result.astimezone(timezone.utc)


def _validate_payload(raw: bytes):
    if not isinstance(raw, bytes) or not 2 <= len(raw) <= MAX_BYTES:
        raise PolicyError("ASSET_RESPONSE_INVALID", "Asset response is empty or exceeds the configured size")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise PolicyError("ASSET_RESPONSE_INVALID", "Asset response is not valid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise PolicyError("ASSET_RESPONSE_INVALID", "Alpaca did not return a nonempty asset list")
    if len(payload) > 200000:
        raise PolicyError("ASSET_RESPONSE_INVALID", "Asset count exceeds the safety limit")
    by_id = {}
    for record in payload:
        if not isinstance(record, dict):
            raise PolicyError("ASSET_SCHEMA_INVALID", "Each asset must be a JSON object")
        asset_id, sym = record.get("id"), record.get("symbol")
        try:
            parsed = UUID(str(asset_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise PolicyError("ASSET_ID_INVALID", "An Alpaca asset has no valid UUID") from exc
        if str(parsed) != str(asset_id).lower() or not isinstance(sym, str) or not SYMBOL.fullmatch(sym):
            raise PolicyError("ASSET_IDENTITY_AMBIGUOUS", "Asset ID/symbol must be explicit and unambiguous")
        if record.get("class") != "us_equity":
            raise PolicyError("ASSET_CLASS_INVALID", "Only the explicit us_equity source response is supported")
        if record.get("status") not in ("active", "inactive"):
            raise PolicyError("ASSET_STATUS_INVALID", "An asset has an unknown activation status")
        if type(record.get("tradable")) is not bool or not isinstance(record.get("exchange"), str):
            raise PolicyError("ASSET_SCHEMA_INVALID", "Missing tradability or exchange metadata")
        # Tickers can be reused. Preserve separate vendor asset IDs and
        # expose collisions instead of silently merging different identities.
        if asset_id in by_id:
            raise PolicyError("ASSET_IDENTITY_AMBIGUOUS", "Duplicate Alpaca asset UUID in one observed response")
        by_id[asset_id] = record
    return payload


def _root(project_root):
    return Path(project_root).resolve() / "data" / "managed" / "asset_observations"


def _immutable(path: Path, data: bytes):
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise PolicyError("ASSET_ARCHIVE_CONFLICT", "Existing evidence bytes differ from immutable archive")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            if path.read_bytes() != data:
                raise PolicyError("ASSET_ARCHIVE_CONFLICT", "Concurrent archive content changed")
            return
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _replace(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temp.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_manifest(folder, snapshot_id):
    if not isinstance(snapshot_id, str) or not SHA.fullmatch(snapshot_id):
        raise PolicyError("ASSET_ARCHIVE_INVALID", "Invalid asset snapshot digest")
    path = folder / "snapshots" / (snapshot_id + ".json")
    if not path.is_file():
        raise PolicyError("ASSET_ARCHIVE_MISSING", "Immutable asset manifest is absent")
    raw_manifest = path.read_bytes()
    if _digest(raw_manifest) != snapshot_id:
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Asset snapshot manifest SHA256 mismatch")
    try:
        manifest = json.loads(raw_manifest)
    except ValueError as exc:
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Unreadable asset snapshot manifest") from exc
    if manifest.get("schema") != SCHEMA or manifest.get("endpoint") not in ENDPOINTS.values():
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Unsupported provenance manifest")
    _timestamp(manifest.get("observed_at_utc"))
    digest = manifest.get("raw_sha256")
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Raw asset SHA256 is missing")
    path = folder / "objects" / digest
    if not path.is_file():
        raise PolicyError("ASSET_ARCHIVE_MISSING", "Raw provider asset response is absent")
    payload = path.read_bytes()
    if _digest(payload) != digest:
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Raw provider asset response SHA256 mismatch")
    records = _validate_payload(payload)
    if len(records) != manifest.get("returned_records"):
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Asset count changed from original source response")
    return manifest, records


def _latest(folder):
    path = folder / "latest.json"
    if not path.is_file():
        raise PolicyError("NO_REAL_ASSET_OBSERVATION", "No authenticated Alpaca asset snapshot was archived")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "The latest asset pointer is unreadable") from exc
    if set(data) != {"schema", "snapshot_id"} or data["schema"] != SCHEMA:
        raise PolicyError("ASSET_ARCHIVE_TAMPERED", "Invalid latest pointer")
    return _read_manifest(folder, data["snapshot_id"])


def _observed_changes(previous, current):
    if previous is None:
        return None
    old = {row["id"]: row for row in previous}
    new = {row["id"]: row for row in current}
    common = set(old) & set(new)
    return {
        "new_to_response": len(set(new) - set(old)),
        "absent_from_response": len(set(old) - set(new)),
        "same_asset_id_symbol_changed": sum(old[i]["symbol"] != new[i]["symbol"] for i in common),
        "same_asset_id_status_changed": sum(old[i]["status"] != new[i]["status"] for i in common),
        "not_a_delisting_or_rename_certificate": True,
    }


def archive_response(project_root, raw: bytes, *, endpoint: str, observed_at_utc: str):
    """Archive real, previously authenticated response bytes. Not a public fake-data API."""
    if endpoint not in ENDPOINTS.values():
        raise PolicyError("ASSET_ENDPOINT_UNAPPROVED", "Only approved Alpaca read-only asset API is accepted")
    recorded = _timestamp(observed_at_utc)
    if recorded > datetime.now(timezone.utc):
        raise PolicyError("ASSET_OBSERVATION_TIME_INVALID", "Observation cannot be in the future")
    records = _validate_payload(raw)
    folder = _root(project_root)
    prior_id, prior = None, None
    if (folder / "latest.json").is_file():
        prior_manifest, prior = _latest(folder)
        if _timestamp(prior_manifest["observed_at_utc"]) > recorded:
            raise PolicyError("ASSET_OBSERVATION_ORDER", "A newer source observation is already archived")
        prior_id = _digest(_canonical(prior_manifest))
    sha = _digest(raw)
    manifest = {
        "schema": SCHEMA,
        "source": "ALPACA",
        "endpoint": endpoint,
        "query": {"asset_class": "us_equity", "status": "all_via_omission"},
        "observed_at_utc": recorded.isoformat(),
        "raw_sha256": sha,
        "returned_records": len(records),
        "previous_snapshot_id": prior_id,
        "scope": "CURRENT_PROVIDER_ASSET_LIST_ONLY",
        "historical_pit_eligible": False,
        "permanent_issuer_identity_verified": False,
        "individual_stock_classification_verified": False,
    }
    manifest_bytes = _canonical(manifest)
    snapshot_id = _digest(manifest_bytes)
    _immutable(folder / "objects" / sha, raw)
    _immutable(folder / "snapshots" / (snapshot_id + ".json"), manifest_bytes)
    # Update the mutable pointer only after both immutable assets are persisted.
    _replace(folder / "latest.json", _canonical({"schema": SCHEMA, "snapshot_id": snapshot_id}))
    return {"snapshot_id": snapshot_id, "observed_at_utc": manifest["observed_at_utc"],
            "returned_records": len(records), "changes": _observed_changes(prior, records),
            "historical_pit_eligible": False}


def fetch_assets(*, endpoint="paper", timeout=25):
    if endpoint not in ENDPOINTS:
        raise PolicyError("ASSET_ENDPOINT_UNAPPROVED", "Unknown Alpaca trading asset endpoint")
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise PolicyError("MISSING_CREDENTIALS", "Alpaca read-only asset request needs locally configured API credentials")
    request = Request(ENDPOINTS[endpoint] + "?asset_class=us_equity",
                      headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                               "Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise PolicyError("ASSET_PROVIDER_HTTP_ERROR", "Alpaca asset endpoint returned a non-200 response")
            # Read a bounded response; do not persist credentials, headers, or auth URLs.
            raw = response.read(MAX_BYTES + 1)
            received = datetime.now(timezone.utc).isoformat()
    except HTTPError as exc:
        raise PolicyError("ASSET_PROVIDER_HTTP_ERROR", f"Alpaca read-only assets HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise PolicyError("ASSET_PROVIDER_UNAVAILABLE", "Alpaca assets endpoint unavailable or request timed out") from None
    _validate_payload(raw)
    return raw, ENDPOINTS[endpoint], received


def sync(project_root, *, endpoint="paper", offline=False):
    if offline:
        summary = inventory(project_root, limit=0)
        return {"status": "OFFLINE_VERIFIED", "snapshot_id": summary["snapshot_id"],
                "observed_at_utc": summary["observed_at_utc"], "no_new_observation": True}
    raw, source, observed = fetch_assets(endpoint=endpoint)
    return {"status": "ARCHIVED_OBSERVATION", **archive_response(project_root, raw, endpoint=source, observed_at_utc=observed)}


def inventory(project_root, *, q="", status="all", tradable="all", limit=30, offset=0):
    if not isinstance(q, str) or len(q) > 64 or status not in {"all", "active", "inactive"} or tradable not in {"all", "true", "false"}:
        raise PolicyError("ASSET_QUERY_INVALID", "Invalid asset directory filters")
    if type(limit) is not int or not 0 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1000000:
        raise PolicyError("ASSET_QUERY_INVALID", "Asset pagination out of range")
    folder = _root(project_root)
    manifest, data = _latest(folder)
    filtered = [asset for asset in data if
                (status == "all" or asset["status"] == status) and
                (tradable == "all" or asset["tradable"] is (tradable == "true")) and
                (not q or q.casefold() in asset["symbol"].casefold() or q.casefold() in str(asset.get("name") or "").casefold())]
    filtered.sort(key=lambda row: (row["symbol"], row["id"]))
    symbol_counts = Counter(row["symbol"] for row in data)
    prev = None
    if manifest.get("previous_snapshot_id"):
        _, prev = _read_manifest(folder, manifest["previous_snapshot_id"])
    return {
        "status": "OBSERVED_CURRENT_CATALOG_NOT_HISTORICAL_PIT",
        "source": manifest["source"], "endpoint": manifest["endpoint"],
        "snapshot_id": _digest(_canonical(manifest)),
        "raw_sha256": manifest["raw_sha256"],
        "observed_at_utc": manifest["observed_at_utc"],
        "returned_records": len(data),
        "active": sum(x["status"] == "active" for x in data),
        "active_tradable": sum(x["status"] == "active" and x["tradable"] for x in data),
        "symbol_collision_count": sum(count > 1 for count in symbol_counts.values()),
        "filtered_count": len(filtered), "offset": offset, "limit": limit,
        "assets": [{"asset_id": a["id"], "symbol": a["symbol"], "name": a.get("name") or "",
                    "exchange": a["exchange"], "status": a["status"], "tradable": a["tradable"]}
                   for a in filtered[offset:offset + limit]],
        "observed_changes": _observed_changes(prev, data),
        "capabilities": {
            "current_asset_metadata": "OBSERVATION_ONLY",
            "historical_universe": "BLOCKED_NO_PIT_MEMBERSHIP",
            "historical_name_changes": "BLOCKED_NO_EFFECTIVE_DATED_HISTORY",
            "issuer_identity": "BLOCKED_VENDOR_ASSET_ID_IS_NOT_PROOF_OF_ISSUER_ID",
            "stock_vs_etf": "BLOCKED_NO_VERIFIED_CLASSIFICATION",
            "corporate_action_settlement": "BLOCKED_NEEDS_VERIFIED_EVENTS",
        },
    }
