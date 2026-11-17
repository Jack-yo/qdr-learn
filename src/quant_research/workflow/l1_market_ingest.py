"""Persist L1 live scans and expose the six-system / twelve-dimension store.

Live snapshots are stored as current observations with explicit receipt lineage.
No write in this module grants historical PIT, forecast, or trading eligibility.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from pathlib import Path
import threading

from quant_research.data.l1_market_catalog import (
    FEATURE_BY_KEY, catalog_payload, coverage_matrix,
)
from quant_research.data.l1_market_store import L1MarketStore

_SHA = re.compile(r"^[a-f0-9]{64}$")
_STORE_LOCK = threading.RLock()

_FEATURE_ALIASES = {
    "cboe_pcr_total": "put_call_volume_ratio",
    "cboe_pcr_etp": "etp_put_call_ratio",
    "cboe_pcr_index": "index_put_call_ratio",
    "cboe_pcr_equity": "equity_put_call_ratio",
    "cboe_spx_put_call_oi": "options_oi_put_call",
    "cboe_trf_notional_share": "trf_notional_share",
    "cftc_emini_sp500_lev_net_pct_oi": "cftc_sp500_net_pct_oi",
    "nyfed_sofr": "sofr_pct",
    "nyfed_effr": "effr_pct",
    "nyfed_sofr_minus_effr_bp": "sofr_effr_spread_bp",
    "vix": "vix_close",
    "credit_spread": "hy_oas",
    "treasury_yield": "treasury_10y_pct",
    "sofr": "sofr_pct",
}
_SOURCE_ALIASES = {
    "nyfed_sofr": "nyfed",
    "nyfed_effr": "nyfed",
    "cftc_sp500": "cftc",
    "cftc_nasdaq": "cftc",
    "cftc_gold": "cftc",
    "cftc_wti": "cftc",
    "cboe_options": "cboe_daily_options",
    "cboe_equity_volume": "cboe_market_volume",
    "fomc_calendar": "fed_calendar",
    "fred_cross_asset": "fred_alfred",
    "market_breadth": "market_breadth",
    "stock_sample": "alpaca_bars",
}
_VALUE_SCALE = {
    "spy_return_1": 100.0, "spy_return_5": 100.0, "spy_return_20": 100.0,
    "rv5": 100.0, "rv20": 100.0, "downside_rv20": 100.0,
    "breadth_proxy_rsp_spy_5": 100.0, "small_cap_relative_5": 100.0,
    "credit_proxy_hyg_lqd_5": 100.0, "drawdown20": 100.0,
    "overnight": 100.0, "intraday": 100.0, "sector_dispersion_1": 100.0,
    "sector_up_share_1": 100.0, "duration_proxy_5": 100.0,
    "credit_spread": 100.0,
}


def _aware(value, fallback=None):
    value = value or fallback or datetime.now(timezone.utc)
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if not isinstance(value, datetime) else value
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("L1_INGEST_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return stamp.astimezone(timezone.utc)


def _json_digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _register_receipt(store, digest, *, provider, dataset, fetched_at,
                      available_at=None, metadata=None):
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise ValueError("L1_INGEST_RECEIPT_SHA256_INVALID")
    fetched = _aware(fetched_at)
    store.write_receipt(
        provider=str(provider or "UNKNOWN"),
        dataset=str(dataset),
        fetched_at=fetched,
        available_at=_aware(available_at, fetched),
        receipt_sha256=digest,
        metadata=metadata or {},
    )
    return digest


def persist_public_scan(root, payload, *, scan_kind):
    """Append official/extended scanner output to DuckDB with honest provenance."""
    if not isinstance(payload, dict) or payload.get("schema") not in {
        "qdr.l1.official.v1", "qdr.l1.extended.v1"
    }:
        raise ValueError("L1_PUBLIC_SCAN_SCHEMA_INVALID")
    now = _aware(payload.get("fetched_at"))
    asof = str(payload.get("asof_session") or now.date().isoformat())
    written_features = written_health = written_events = 0
    skipped_features = []
    with _STORE_LOCK, L1MarketStore(root) as store:
        health_rows = []
        for name, item in (payload.get("source_health") or {}).items():
            source_key = _SOURCE_ALIASES.get(name, name)
            digest = item.get("receipt_sha256")
            fetched = _aware(item.get("fetched_at"), now)
            if digest:
                _register_receipt(store, digest, provider=item.get("source") or source_key,
                    dataset=scan_kind + "_source_health", fetched_at=fetched,
                    available_at=fetched, metadata={"source_key": source_key,
                    "pit": item.get("pit"), "effective_date": item.get("effective_date")})
            input_receipts=item.get("input_receipts") or []
            for input_index,input_digest in enumerate(input_receipts):
                if input_digest and input_digest != digest:
                    input_source=("alpaca_assets" if name=="market_breadth" and input_index==0
                                  else "alpaca_snapshots" if name=="market_breadth"
                                  else source_key)
                    _register_receipt(store,input_digest,provider=input_source,
                        dataset=scan_kind+"_input_source_receipt",fetched_at=fetched,
                        available_at=fetched,metadata={"derived_parent":digest,"source_key":input_source})
            if name=="market_breadth":
                assets_ok=bool(input_receipts)
                health_rows.append({"source_key":"alpaca_assets","asof_session":asof,
                    "fetched_at":fetched,"status":"OBSERVED" if assets_ok else "MISSING",
                    "error_code":None if assets_ok else item.get("code"),
                    "receipt_sha256":input_receipts[0] if assets_ok else None,
                    "metadata":{"scope":"CURRENT_ACTIVE_TRADABLE_NON_OTC_DIRECTORY"}})
                snapshot_receipts=input_receipts[1:]
                health_rows.append({"source_key":"alpaca_snapshots","asof_session":asof,
                    "fetched_at":fetched,"status":item.get("status") or "MISSING",
                    "error_code":item.get("code"),
                    "receipt_sha256":snapshot_receipts[0] if snapshot_receipts else None,
                    "metadata":{"coverage_n":item.get("coverage_n"),
                        "expected_n":item.get("expected_n"),
                        "observation_mode":item.get("observation_mode"),
                        "feed_sources":item.get("feed_sources"),
                        "snapshot_receipt_count":len(snapshot_receipts),
                        "snapshot_receipts":snapshot_receipts}})
                health_rows.append({"source_key":"market_breadth","asof_session":asof,
                    "fetched_at":fetched,"status":item.get("status") or "MISSING",
                    "error_code":item.get("code"),"receipt_sha256":digest,
                    "metadata":{"coverage_n":item.get("coverage_n"),
                        "expected_n":item.get("expected_n")}})
                continue
            health_rows.append({
                "source_key": source_key, "asof_session": asof,
                "fetched_at": fetched, "status": item.get("status") or "MISSING",
                "error_code": item.get("code"),
                "receipt_sha256": digest,
                "metadata": {k:v for k,v in item.items()
                             if k not in {"receipt_sha256","fetched_at","status","code"}},
            })
        written_health = store.write_source_health(health_rows)

        observation_rows = []
        for item in payload.get("features") or []:
            raw_id = str(item.get("feature_id") or item.get("id") or "")
            feature_id = _FEATURE_ALIASES.get(raw_id, raw_id)
            spec = FEATURE_BY_KEY.get(feature_id)
            if spec is None:
                skipped_features.append(raw_id)
                continue
            digest = item.get("receipt_sha256")
            if not digest:
                skipped_features.append(raw_id + ":NO_RECEIPT")
                continue
            fetched = _aware(item.get("fetched_at"), now)
            provider = str(item.get("source") or scan_kind.upper())
            _register_receipt(store, digest, provider=provider,
                dataset=scan_kind + "_observation", fetched_at=fetched,
                available_at=fetched, metadata={
                    "derived_receipt": item.get("source") == "ALPACA_ACTIVE_US_EQUITY_SNAPSHOT_BREADTH",
                    "observed_date": item.get("observed_date"),
                    "pit": item.get("pit"),
                    "metadata": item.get("metadata") or {},
                })
            observation_rows.append({
                "session_date": str(item.get("observed_date") or asof),
                "dimension": spec.dimension,
                "feature_id": feature_id,
                "value": item.get("value"),
                "unit": item.get("unit") or spec.unit,
                "provider": provider,
                "source": provider,
                "observed_at": None,
                "available_at": fetched,
                "vintage_id": scan_kind + ":" + str(item.get("observed_date") or asof),
                "pit_status": item.get("pit") or "CURRENT_OBSERVATION_NOT_HISTORICAL_PIT",
                "quality_status": item.get("status") or "OBSERVED",
                "coverage_n": item.get("coverage_n"),
                "expected_n": item.get("expected_n"),
                "receipt_sha256": digest,
                "metadata": {"label": item.get("label"),
                    "observed_date": item.get("observed_date"),
                    **(item.get("metadata") or {})},
            })
        written_features = store.write_observations(observation_rows)

        event_rows = []
        for event in payload.get("calendar_events") or []:
            digest = event.get("receipt_sha256")
            if not digest:
                continue
            fetched = _aware(event.get("schedule_known_at"), now)
            _register_receipt(store, digest, provider=event.get("source") or "BLS",
                dataset=scan_kind + "_calendar_event", fetched_at=fetched,
                available_at=fetched, metadata={"event_id": event.get("event_id")})
            event_rows.append({
                "event_id": str(event.get("event_id") or ""),
                "event_type": str(event.get("event_type") or "BLS"),
                "scheduled_at": event.get("start_utc") or event.get("scheduled_at"),
                "schedule_known_at": event.get("schedule_known_at"),
                "source": event.get("source") or "BLS",
                "receipt_sha256": digest,
                "vintage_id": scan_kind + ":" + str(event.get("schedule_known_at") or ""),
                "metadata": {"name": event.get("name")},
            })
        written_events = store.write_events(event_rows)
    return {"status":"PERSISTED","features":written_features,
            "source_health":written_health,"events":written_events,
            "skipped_features":skipped_features}


def persist_l1_v2(root, payload):
    """Persist V2 raw ETF and Level-1 observations without promoting them to PIT."""
    if not isinstance(payload, dict) or not isinstance(payload.get("domains"), list):
        raise ValueError("L1_V2_PAYLOAD_INVALID")
    now = _aware(payload.get("fetched_at"))
    asof = str(payload.get("asof_session") or now.date().isoformat())
    source_receipts = payload.get("source_receipts") or []
    input_hashes = []
    source_times = []
    with _STORE_LOCK, L1MarketStore(root) as store:
        for receipt in source_receipts:
            digest = receipt.get("sha256") or receipt.get("receipt_sha256")
            if not digest:
                continue
            fetched = _aware(receipt.get("fetched_at"), now)
            source_times.append(fetched)
            input_hashes.append(digest)
            _register_receipt(store, digest, provider=receipt.get("source") or "ALPACA",
                dataset="l1_v2_market_bars", fetched_at=fetched, available_at=fetched,
                metadata={k:v for k,v in receipt.items() if k not in {"sha256","fetched_at"}})
        available = max(source_times) if source_times else now
        rows = []
        for domain in payload["domains"]:
            for item in domain.get("features") or []:
                raw_id = str(item.get("feature_id") or item.get("id") or "")
                feature_id = _FEATURE_ALIASES.get(raw_id, raw_id)
                spec = FEATURE_BY_KEY.get(feature_id)
                if spec is None:
                    continue
                value = item.get("value")
                if value is not None:
                    value = float(value) * _VALUE_SCALE.get(raw_id, 1.0)
                digest = _json_digest({"session":asof,"feature":feature_id,
                    "value":value,"inputs":sorted(input_hashes),"engine":"L1_V2_DERIVED_V1"})
                _register_receipt(store, digest, provider="QDR_L1_V2_DERIVED",
                    dataset="l1_v2_derived_observation", fetched_at=now,
                    available_at=available, metadata={"input_receipts":sorted(input_hashes),
                    "feature_id":feature_id,"raw_feature_id":raw_id})
                rows.append({
                    "session_date": str(item.get("observed_date") or asof),
                    "dimension": spec.dimension, "feature_id":feature_id,
                    "value":value,"unit":spec.unit,
                    "provider":"QDR_L1_V2_DERIVED",
                    "source":item.get("source") or "ALPACA_ETF_HISTORY",
                    "observed_at":None,"available_at":available,
                    "vintage_id":"l1_v2:"+asof,
                    "pit_status":item.get("pit") or "CURRENT_OBSERVATION_NOT_HISTORICAL_PIT",
                    "quality_status":item.get("status") or "OBSERVED",
                    "receipt_sha256":digest,
                    "metadata":{"label":item.get("label"),"domain":domain.get("id"),
                                "fetched_at":item.get("fetched_at")},
                })
        written = store.write_observations(rows)
        health = []
        for domain in payload["domains"]:
            health.append({"source_key":"l1_v2."+str(domain.get("id") or "unknown"),
                "asof_session":asof,"fetched_at":now,"status":domain.get("status") or "MISSING",
                "metadata":{"coverage":domain.get("coverage"),"reason":domain.get("reason")}})
        if input_hashes:
            health.append({"source_key":"alpaca_bars","asof_session":asof,
                "fetched_at":available,"status":"OBSERVED","receipt_sha256":input_hashes[-1],
                "metadata":{"source_receipts":len(input_hashes),"scope":"ETF_HISTORICAL_BARS"}})
        written_health = store.write_source_health(health)
    return {"status":"PERSISTED","features":written,"source_health":written_health,
            "source_receipts":len(input_hashes)}


def market_data_snapshot(root, *, asof=None, db_path=None):
    """Read the actual stored six-system / twelve-dimension coverage and provenance."""
    with _STORE_LOCK, L1MarketStore(root,db_path=db_path) as store:
        status = store.status()
        observations = store.read_observations(asof=asof)
        security = store.read_security_features(asof=asof)
        health = store.read_source_health(asof=asof)
        labels = store.read_path_labels(asof=asof)
        obs_rows = observations.to_dict("records") if not observations.empty else []
        sec_rows = security.to_dict("records") if not security.empty else []
        combined = obs_rows + sec_rows
        latest_health = []
        health_map = {}
        if not health.empty:
            # An as-of query cannot expose a source-health result fetched after
            # the requested day, even if its observed session belongs to that day.
            if asof:
                health = health.loc[
                    health["fetched_at"].astype(str).str.slice(0, 10).le(str(asof))]
            health = health.sort_values("fetched_at")
            for source_key, group in health.groupby("source_key", sort=True):
                row = group.iloc[-1].to_dict()
                if hasattr(row.get("asof_session"),"isoformat"):
                    row["asof_session"]=row["asof_session"].isoformat()
                if hasattr(row.get("fetched_at"),"isoformat"):
                    row["fetched_at"]=row["fetched_at"].isoformat()
                latest_health.append(row)
                health_map[str(source_key)] = {"status":str(row.get("status") or "MISSING")}
        reference_date = str(asof or datetime.now(timezone.utc).date().isoformat())
        coverage = coverage_matrix(
            combined, source_health=health_map, asof=asof,
            freshness_asof=reference_date)
        path_summary = {
            "rows":len(labels),
            "horizons":sorted({int(x) for x in labels.horizon.tolist()}) if not labels.empty else [],
            "latest_session":str(labels.session_date.max()) if not labels.empty else None,
            "outcome_only":True,
        }
        return {
            "schema":"qdr.l1.market_data_snapshot.v1",
            "generated_at_utc":datetime.now(timezone.utc).isoformat(),
            "catalog":catalog_payload(),
            "status":status,
            "coverage":coverage,
            "source_health":latest_health,
            "path_labels":path_summary,
            "policy":{"historical_pit_verified":False,"forecast_eligible":False,
                      "trade_eligible":False},
        }
