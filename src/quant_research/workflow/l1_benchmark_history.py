"""Small L1 benchmark history sync.

Purpose: persist only the liquid market benchmark basket and a small set of
public macro/risk series used for monitoring and research. This is intentionally
not a full-US-equity historical warehouse and does not establish historical PIT.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import math

from quant_research.clock import TradingClock
from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.data.l1_market_store import L1MarketStore


BENCHMARK_SYMBOLS = tuple(LiveSources.ETF_SYMBOLS)
BAR_PROVIDER = "ALPACA_BENCHMARK"
BAR_BASIS = "split"
OVERLAP_CALENDAR_DAYS = 10

# Public/current-vintage history for charts, distributions and data diagnostics.
# It is not admitted as historical PIT evidence.
FRED_BASELINES = {
    "hy_oas": ("BAMLH0A0HYM2", "cross_asset", "bps", 100.0),
    "real_yield_10y": ("DFII10", "cross_asset", "%", 1.0),
    "breakeven_10y": ("T10YIE", "cross_asset", "%", 1.0),
    "treasury_2y_pct": ("DGS2", "cross_asset", "%", 1.0),
    "treasury_10y_pct": ("DGS10", "cross_asset", "%", 1.0),
    "sofr_pct": ("SOFR", "funding", "%", 1.0),
    "effr_pct": ("EFFR", "funding", "%", 1.0),
}
USD_SERIES = "DTWEXBGS"


def _latest_completed_session(now=None):
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("BENCHMARK_SYNC_TIME_MUST_BE_AWARE")
    stamp = stamp.astimezone(timezone.utc)
    clock = TradingClock()
    session = clock.calendar.date_to_session(stamp.date(), direction="previous")
    while clock.close(session) + clock.delay > stamp:
        session = clock.calendar.previous_session(session)
    return session.date().isoformat(), stamp


def _derived_digest(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                             default=str).encode("utf-8")).hexdigest()


def _register_transport_receipts(store, receipts, *, dataset):
    registered = []
    for item in receipts:
        digest = str(item.get("sha256") or "")
        if len(digest) != 64:
            raise ValueError("BENCHMARK_SOURCE_RECEIPT_INVALID")
        store.write_receipt(
            provider="ALPACA",
            dataset=dataset,
            fetched_at=item["fetched_at"],
            available_at=item["fetched_at"],
            observed_start=item.get("start"),
            observed_end=item.get("end"),
            receipt_sha256=digest,
            metadata={**item, "raw_provider_body_stored": False},
        )
        registered.append(digest)
    return registered


def _bar_available_at(clock, day):
    return (clock.close(clock.session(day)) + clock.delay).astimezone(timezone.utc)


def _normalize_alpaca_bars(raw, aggregate_receipt):
    clock = TradingClock()
    records = []
    for symbol in BENCHMARK_SYMBOLS:
        for item in raw.get(symbol, []):
            day = str(item.get("t") or "")[:10]
            if len(day) != 10:
                raise ValueError("BENCHMARK_BAR_DATE_INVALID")
            values = [item.get(k) for k in ("o", "h", "l", "c", "v")]
            try:
                opn, high, low, close, volume = [float(x) for x in values]
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("BENCHMARK_BAR_NUMERIC_INVALID") from exc
            if (not all(math.isfinite(x) for x in (opn, high, low, close, volume)) or
                min(opn, high, low, close) <= 0 or volume < 0 or
                high < max(opn, close, low) or low > min(opn, close, high)):
                raise ValueError("BENCHMARK_BAR_OHLC_INVALID")
            records.append({
                "session_date": day,
                "security_id": "SYMBOL:" + symbol,
                "symbol": symbol,
                "open": opn, "high": high, "low": low, "close": close,
                "volume": volume,
                "vwap": item.get("vw"),
                "trade_count": item.get("n"),
                "provider": BAR_PROVIDER,
                "price_basis": BAR_BASIS,
                "identity_status": "SYMBOL_ONLY_SPLIT_ADJUSTED_RESEARCH_NOT_PIT",
                "available_at": _bar_available_at(clock, day),
                "receipt_sha256": aggregate_receipt,
            })
    if not records:
        raise ValueError("BENCHMARK_HISTORY_EMPTY")
    keys = [(x["session_date"], x["symbol"]) for x in records]
    if len(keys) != len(set(keys)):
        raise ValueError("BENCHMARK_HISTORY_DUPLICATE_SYMBOL_DATE")
    return records


def _expected_sessions(start, end):
    clock = TradingClock()
    first = date.fromisoformat(str(start))
    last = date.fromisoformat(str(end))
    return [x.date().isoformat() for x in clock.calendar.sessions
            if first <= x.date() <= last]


def _bar_quality(store, start, end):
    frame = store.read_bars(start=start, end=end, symbols=BENCHMARK_SYMBOLS)
    if not frame.empty:
        frame = frame.loc[(frame.provider == BAR_PROVIDER) &
                          (frame.price_basis == BAR_BASIS)].copy()
    expected = _expected_sessions(start, end)
    expected_set = set(expected)
    details = {}
    actual_total = 0
    missing_total = 0
    stale = []
    for symbol in BENCHMARK_SYMBOLS:
        rows = frame.loc[frame.symbol.eq(symbol)] if not frame.empty else frame
        dates = set(rows.session_date.astype(str).tolist()) if not rows.empty else set()
        missing = sorted(expected_set - dates)
        actual_total += len(dates & expected_set)
        missing_total += len(missing)
        latest = max(dates) if dates else None
        if latest != end:
            stale.append(symbol)
        details[symbol] = {
            "rows": len(dates & expected_set),
            "missing_sessions": len(missing),
            "missing_sample": missing[:5],
            "latest_session": latest,
        }
    expected_total = len(expected) * len(BENCHMARK_SYMBOLS)
    coverage = actual_total / expected_total if expected_total else 0.0
    status = "OBSERVED" if coverage >= 0.995 and not stale else "PARTIAL"
    return {
        "status": status,
        "coverage_n": actual_total,
        "expected_n": expected_total,
        "coverage_pct": round(coverage * 100, 4),
        "missing_sessions": missing_total,
        "stale_symbols": stale,
        "symbol_count": len(BENCHMARK_SYMBOLS),
        "details": details,
    }


def _sync_bars(store, sources, *, years, refresh, history_feed, asof, stamp,
               force_bootstrap=False):
    full_start = date.fromisoformat(asof) - timedelta(days=int(years * 366))
    existing = store.read_bars(symbols=BENCHMARK_SYMBOLS)
    if not existing.empty:
        existing = existing.loc[(existing.provider == BAR_PROVIDER) &
                                (existing.price_basis == BAR_BASIS)]
    incremental = not force_bootstrap and not existing.empty
    if incremental:
        last_by_symbol = existing.groupby("symbol").session_date.max().to_dict()
        if set(last_by_symbol) == set(BENCHMARK_SYMBOLS):
            oldest_latest = min(x.isoformat() if hasattr(x, "isoformat") else str(x)
                                for x in last_by_symbol.values())
            start = max(full_start, date.fromisoformat(oldest_latest) -
                        timedelta(days=OVERLAP_CALENDAR_DAYS))
        else:
            start = full_start
            incremental = False
    else:
        start = full_start
    days = (date.fromisoformat(asof) - start).days + 1
    raw, receipts = sources.bars(
        days=days, symbols=BENCHMARK_SYMBOLS,
        start_date=start.isoformat(), end_date=asof,
        adjustment=BAR_BASIS, history_feed=history_feed,
        refresh=refresh,
    )
    input_hashes = _register_transport_receipts(
        store, receipts, dataset="core_benchmark_daily_bars_page")
    aggregate = _derived_digest({
        "dataset": "core_benchmark_daily_bars",
        "symbols": BENCHMARK_SYMBOLS,
        "start": start.isoformat(), "end": asof,
        "adjustment": BAR_BASIS,
        "input_receipts": sorted(input_hashes),
    })
    fetched = max(datetime.fromisoformat(str(x["fetched_at"]).replace("Z", "+00:00"))
                  for x in receipts)
    store.write_receipt(
        provider="QDR_DERIVED_RECEIPT",
        dataset="core_benchmark_daily_bars",
        fetched_at=fetched, available_at=fetched,
        observed_start=start, observed_end=asof,
        receipt_sha256=aggregate,
        metadata={"derived_receipt": True, "input_receipts": input_hashes,
                  "symbols": list(BENCHMARK_SYMBOLS), "adjustment": BAR_BASIS,
                  "historical_pit_verified": False},
    )
    records = _normalize_alpaca_bars(raw, aggregate)
    written = store.write_bars(records)
    quality = _bar_quality(store, full_start.isoformat(), asof)
    store.write_quality_checks([{
        "session_date": asof, "dimension": "price",
        "status": quality["status"],
        "reason": "CORE_BENCHMARK_HISTORY_SYNC",
        "coverage_n": quality["coverage_n"],
        "expected_n": quality["expected_n"],
        "checked_at": stamp,
        "metadata": {
            "symbols": list(BENCHMARK_SYMBOLS),
            "window_start": full_start.isoformat(),
            "window_end": asof,
            "request_start": start.isoformat(),
            "incremental": incremental,
            "coverage_pct": quality["coverage_pct"],
            "missing_sessions": quality["missing_sessions"],
            "stale_symbols": quality["stale_symbols"],
            "price_basis": BAR_BASIS,
            "historical_pit_verified": False,
        },
    }])
    return {
        "status": quality["status"],
        "mode": "INCREMENTAL" if incremental else "BOOTSTRAP",
        "request_start": start.isoformat(), "window_start": full_start.isoformat(),
        "asof_session": asof, "rows_received": len(records),
        "rows_written": written, "source_pages": len(receipts),
        "coverage": quality,
        "receipt_sha256": aggregate,
        "historical_pit_verified": False,
    }


def _register_series_receipt(store, receipt, dataset, observed_start, observed_end,
                             provider=None):
    digest = str(receipt["sha256"])
    store.write_receipt(
        provider=provider or str(receipt.get("source") or "PUBLIC_SERIES"),
        dataset=dataset,
        fetched_at=receipt["fetched_at"],
        available_at=receipt["fetched_at"],
        observed_start=observed_start, observed_end=observed_end,
        receipt_sha256=digest,
        metadata={**receipt, "raw_provider_body_stored": False,
                  "historical_pit_verified": False},
    )
    return digest


def _obs(feature, dimension, day, value, unit, provider, source, receipt, fetched,
         metadata=None):
    return {
        "session_date": day, "dimension": dimension, "feature_id": feature,
        "value": value, "unit": unit, "provider": provider, "source": source,
        "observed_at": None, "available_at": fetched,
        "vintage_id": "CURRENT_DOWNLOAD:" + receipt[:12],
        "pit_status": "CURRENT_VINTAGE_NOT_HISTORICAL_PIT",
        "quality_status": "OBSERVED", "coverage_n": None, "expected_n": None,
        "receipt_sha256": receipt, "metadata": metadata or {},
    }


def _sync_macro(store, sources, *, years, refresh, asof):
    start = (date.fromisoformat(asof) - timedelta(days=int(years * 366))).isoformat()
    output = {"status": "OBSERVED", "series": {}, "blocked": {}}
    observations = []

    # VIX public historical download.
    try:
        values, receipt = sources.cboe_vix(refresh=refresh)
        selected = {d: v for d, v in values.items() if start <= d <= asof}
        if not selected:
            raise SourceUnavailable("CBOE_VIX_HISTORY_EMPTY")
        digest = _register_series_receipt(
            store, receipt, "vix_history_current_download",
            min(selected), max(selected), provider="CBOE")
        fetched = receipt["fetched_at"]
        observations.extend(_obs(
            "vix_close", "volatility", d, float(v), "点", "CBOE",
            "CBOE_VIX_CURRENT_DOWNLOAD", digest, fetched,
            {"current_download_not_historical_vintage": True})
            for d, v in sorted(selected.items()))
        output["series"]["vix_close"] = len(selected)
    except (SourceUnavailable, ValueError, TypeError, KeyError) as exc:
        output["blocked"]["vix_close"] = getattr(exc, "code", type(exc).__name__)

    loaded = {}
    for feature, (series_id, dimension, unit, scale) in FRED_BASELINES.items():
        try:
            values, receipt = sources.fred(series_id, refresh=refresh,
                                           days=int(years * 366) + 30)
            selected = {d: float(v) * scale for d, v in values.items()
                        if start <= d <= asof and math.isfinite(float(v))}
            if not selected:
                raise SourceUnavailable("FRED_HISTORY_EMPTY_" + series_id)
            digest = _register_series_receipt(
                store, receipt, "fred_history_current_download:" + series_id,
                min(selected), max(selected), provider="FRED")
            fetched = receipt["fetched_at"]
            observations.extend(_obs(
                feature, dimension, d, v, unit, "FRED",
                "FRED_" + series_id + "_CURRENT_DOWNLOAD", digest, fetched,
                {"series_id": series_id,
                 "registry_primary_source_may_differ": True,
                 "current_download_not_historical_vintage": True})
                for d, v in sorted(selected.items()))
            loaded[series_id] = (selected, digest, fetched)
            output["series"][feature] = len(selected)
        except (SourceUnavailable, ValueError, TypeError, KeyError) as exc:
            output["blocked"][feature] = getattr(exc, "code", type(exc).__name__)

    # Broad trade-weighted USD is an explicit DXY proxy.
    try:
        values, receipt = sources.fred(USD_SERIES, refresh=refresh,
                                       days=int(years * 366) + 60)
        selected = sorted((d, float(v)) for d, v in values.items()
                          if start <= d <= asof and math.isfinite(float(v)) and float(v) > 0)
        if len(selected) < 6:
            raise SourceUnavailable("FRED_USD_HISTORY_INSUFFICIENT")
        digest = _register_series_receipt(
            store, receipt, "fred_history_current_download:" + USD_SERIES,
            selected[0][0], selected[-1][0], provider="FRED")
        fetched = receipt["fetched_at"]
        for i in range(5, len(selected)):
            day, value = selected[i]
            previous = selected[i - 5][1]
            observations.append(_obs(
                "dxy_return_5", "cross_asset", day,
                (value / previous - 1.0) * 100.0, "%", "FRED",
                "FRED_DTWEXBGS_BROAD_USD_PROXY", digest, fetched,
                {"series_id": USD_SERIES,
                 "proxy": "BROAD_TRADE_WEIGHTED_USD_NOT_DXY",
                 "current_download_not_historical_vintage": True}))
        output["series"]["dxy_return_5"] = len(selected) - 5
    except (SourceUnavailable, ValueError, TypeError, KeyError) as exc:
        output["blocked"]["dxy_return_5"] = getattr(exc, "code", type(exc).__name__)

    # Derived spreads from current-vintage FRED history.
    for feature, left, right, dimension in (
        ("treasury_2s10s_bp", "DGS10", "DGS2", "cross_asset"),
        ("sofr_effr_spread_bp", "SOFR", "EFFR", "funding"),
    ):
        if left not in loaded or right not in loaded:
            output["blocked"][feature] = "MISSING_COMPONENT_HISTORY"
            continue
        lv, ld, lf = loaded[left]
        rv, rd, rf = loaded[right]
        common = sorted(set(lv) & set(rv))
        if not common:
            output["blocked"][feature] = "NO_OVERLAPPING_COMPONENT_HISTORY"
            continue
        digest = _derived_digest({
            "feature": feature, "left_receipt": ld, "right_receipt": rd,
            "transform": "100*(left-right)",
        })
        fetched = max(datetime.fromisoformat(str(lf).replace("Z", "+00:00")),
                      datetime.fromisoformat(str(rf).replace("Z", "+00:00")))
        store.write_receipt(
            provider="QDR_DERIVED_RECEIPT", dataset="benchmark_macro_derived",
            fetched_at=fetched, available_at=fetched,
            observed_start=common[0], observed_end=common[-1],
            receipt_sha256=digest,
            metadata={"derived_receipt": True, "inputs": [ld, rd],
                      "historical_pit_verified": False},
        )
        observations.extend(_obs(
            feature, dimension, d, (lv[d] - rv[d]) * 100.0, "bps",
            "QDR_DERIVED", "FRED_CURRENT_DOWNLOAD_DERIVED",
            digest, fetched,
            {"components": [left, right],
             "current_download_not_historical_vintage": True})
            for d in common)
        output["series"][feature] = len(common)

    if observations:
        output["rows_written"] = store.write_observations(observations)
    else:
        output["rows_written"] = 0
        output["status"] = "BLOCKED"
    if output["blocked"] and output["status"] == "OBSERVED":
        output["status"] = "PARTIAL"
    output["historical_pit_verified"] = False
    return output


def sync_benchmark_history(root, *, years=5, refresh=False, sources=None,
                           now=None, history_feed=None, force_bootstrap=False,
                           include_macro=True, db_path=None):
    if not 3 <= int(years) <= 5:
        raise ValueError("BENCHMARK_HISTORY_YEARS_MUST_BE_3_TO_5")
    asof, stamp = _latest_completed_session(now)
    feed = sources or LiveSources(root, now=(lambda: stamp))
    with L1MarketStore(root, db_path=db_path) as store:
        bars = _sync_bars(
            store, feed, years=int(years), refresh=refresh,
            history_feed=history_feed, asof=asof, stamp=stamp,
            force_bootstrap=force_bootstrap)
        macro = (_sync_macro(store, feed, years=int(years), refresh=refresh, asof=asof)
                 if include_macro else {"status": "SKIPPED", "series": {},
                                        "blocked": {}, "rows_written": 0})
        return {
            "schema": "qdr.l1.benchmark_history_sync.v1",
            "status": "OBSERVED" if bars["status"] == "OBSERVED" and
                      macro["status"] in ("OBSERVED", "SKIPPED") else "PARTIAL",
            "asof_session": asof,
            "years": int(years),
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "bars": bars, "macro": macro,
            "store_status": store.status(),
            "historical_pit_verified": False,
            "forecast_eligible": False,
            "trade_eligible": False,
        }
