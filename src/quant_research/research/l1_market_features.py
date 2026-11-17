"""Six-system L1 feature engine. Outputs are research observations or labels.

Breadth requires a complete dated universe snapshot and current source receipts.
PIT is never inferred from a current directory. Forward path labels are isolated
from predictor features and are available only after their future window ends.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re

import numpy as np
import pandas as pd

from quant_research.data.l1_market_catalog import FEATURE_BY_KEY

_SHA = re.compile(r"^[a-f0-9]{64}$")
_SECTOR_ETFS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK",
                "XLP", "XLRE", "XLU", "XLV", "XLY")
_STYLE_ETFS = ("IWB", "IWM", "IWD", "IWF", "MTUM", "QUAL",
               "USMV", "VLUE", "VTV", "VUG")
_REQUIRED_BARS = {"security_id", "symbol", "open", "high", "low", "close",
                  "volume", "available_at", "provider", "price_basis", "receipt_sha256"}


def _dates(frame, label):
    out = frame.copy()
    if "session_date" not in out:
        if "date" not in out:
            raise ValueError(label + "_SESSION_DATE_REQUIRED")
        out = out.rename(columns={"date": "session_date"})
    out["session_date"] = pd.to_datetime(out.session_date, errors="raise")
    if out.session_date.dt.tz is not None or out.session_date.isna().any():
        raise ValueError(label + "_SESSION_DATE_MUST_BE_NAIVE")
    if (out.session_date != out.session_date.dt.normalize()).any():
        raise ValueError(label + "_SESSION_DATE_NOT_NORMALIZED")
    return out


def _aware_utc(value, *, optional=False):
    if optional and (value is None or pd.isna(value)):
        return pd.NaT
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return stamp.tz_convert("UTC")


def _cutoffs(cutoffs):
    c = _dates(cutoffs, "CUTOFFS")
    if "decision_cutoff_utc" not in c:
        raise ValueError("DECISION_CUTOFF_REQUIRED")
    c["decision_cutoff_utc"] = c.decision_cutoff_utc.map(_aware_utc)
    if c.decision_cutoff_utc.isna().any() or c.session_date.duplicated().any():
        raise ValueError("CUTOFFS_DUPLICATE_OR_MISSING")
    return c.sort_values("session_date").reset_index(drop=True)


def _bars(bars, cutoffs):
    b = _dates(bars, "BARS")
    missing = _REQUIRED_BARS - set(b.columns)
    if missing:
        raise ValueError("BARS_MISSING_COLUMNS:" + ",".join(sorted(missing)))
    if b.duplicated(["session_date", "security_id", "provider", "price_basis"]).any():
        raise ValueError("DUPLICATE_SECURITY_BARS")
    if b.duplicated(["session_date", "symbol"]).any():
        raise ValueError("DUPLICATE_SYMBOL_BARS")
    b["available_at"] = b.available_at.map(_aware_utc)
    if b.available_at.isna().any():
        raise ValueError("BAR_AVAILABLE_AT_REQUIRED")
    if not b.receipt_sha256.astype(str).str.fullmatch(_SHA).all():
        raise ValueError("BAR_RECEIPT_SHA256_INVALID")
    if b[["security_id", "symbol", "provider", "price_basis"]].isna().any().any():
        raise ValueError("BAR_IDENTITY_MISSING")
    for field in ("open", "high", "low", "close", "volume"):
        b[field] = pd.to_numeric(b[field], errors="coerce")
    values = b[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or
        (b[["open", "high", "low", "close"]] <= 0).any().any() or (b.volume < 0).any()):
        raise ValueError("BAR_PRICE_OR_VOLUME_INVALID")
    if ((b.high < b[["open", "close", "low"]].max(axis=1)).any() or
        (b.low > b[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("BAR_OHLC_INCONSISTENT")
    b = b.merge(cutoffs, on="session_date", how="left", validate="many_to_one")
    if b.decision_cutoff_utc.isna().any():
        raise ValueError("BAR_OUTSIDE_CUTOFF_CALENDAR")
    if (b.available_at > b.decision_cutoff_utc).any():
        raise ValueError("BAR_ARRIVED_AFTER_DECISION_CUTOFF")
    return b.sort_values(["security_id", "session_date"]).reset_index(drop=True)


def _receipt_digest(session, inputs, version="L1_MARKET_FEATURES_V1"):
    payload = json.dumps({"session": str(session), "inputs": sorted(set(inputs)),
                          "engine": version}, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _record(session, dimension, feature_id, value, unit, available_at,
            receipt_sha, *, quality="OBSERVED", pit="PIT_UNVERIFIED",
            coverage_n=None, expected_n=None, source="QDR_DERIVED",
            metadata=None, provider="QDR_FEATURE_ENGINE", vintage="L1_FEATURES_V1"):
    if feature_id not in FEATURE_BY_KEY:
        raise ValueError("UNREGISTERED_FEATURE:" + feature_id)
    if FEATURE_BY_KEY[feature_id].dimension != dimension:
        raise ValueError("FEATURE_DIMENSION_MISMATCH:" + feature_id)
    if not _SHA.fullmatch(str(receipt_sha)):
        raise ValueError("FEATURE_RECEIPT_SHA256_INVALID")
    numeric = None if value is None or pd.isna(value) else float(value)
    if numeric is not None and not np.isfinite(numeric):
        raise ValueError("FEATURE_VALUE_NONFINITE")
    return {
        "session_date": pd.Timestamp(session).date().isoformat(),
        "dimension": dimension, "feature_id": feature_id, "value": numeric,
        "unit": unit, "provider": provider, "source": source,
        "observed_at": None, "available_at": pd.Timestamp(available_at).isoformat(),
        "vintage_id": vintage, "pit_status": pit,
        "quality_status": quality, "coverage_n": coverage_n,
        "expected_n": expected_n, "receipt_sha256": receipt_sha,
        "metadata": metadata or {},
    }


def _security_record(session, security_id, symbol, feature_id, value, unit,
                     available_at, receipt_sha, *, source, price_basis):
    return {
        "session_date": pd.Timestamp(session).date().isoformat(),
        "security_id": str(security_id), "symbol": str(symbol),
        "feature_id": feature_id, "value": None if pd.isna(value) else float(value),
        "unit": unit, "provider": "QDR_FEATURE_ENGINE", "source": source,
        "available_at": pd.Timestamp(available_at).isoformat(),
        "receipt_sha256": receipt_sha, "pit_status": "PIT_UNVERIFIED",
        "quality_status": "OBSERVED" if pd.notna(value) else "MISSING",
        "price_basis": price_basis, "vintage_id": "L1_FEATURES_V1",
    }


def _per_security_features(bars, cutoffs):
    sessions = pd.DatetimeIndex(cutoffs.session_date)
    security_rows = []
    benchmark = bars.loc[bars.symbol.eq("SPY")].sort_values("session_date")
    benchmark_close = benchmark.set_index("session_date").close.reindex(sessions)
    benchmark_ret5 = benchmark_close.div(benchmark_close.shift(5)).sub(1)
    for (security_id, provider, price_basis), group in bars.groupby(
            ["security_id", "provider", "price_basis"], sort=False):
        group = group.sort_values("session_date").set_index("session_date")
        symbol = str(group.symbol.iloc[-1])
        if group.symbol.nunique() != 1:
            raise ValueError("SECURITY_SYMBOL_MAPPING_CHANGED_WITHOUT_IDENTITY_EVENT")
        x = group.reindex(sessions)
        close = pd.to_numeric(x.close, errors="coerce")
        high = pd.to_numeric(x.high, errors="coerce")
        low = pd.to_numeric(x.low, errors="coerce")
        ret1 = close.pct_change(fill_method=None)
        for window in (5, 20, 60):
            x[f"ret_{window}"] = close.div(close.shift(window)).sub(1)
        x["ret_1"] = ret1
        prior_close = close.shift(1)
        true_range = pd.concat([(high-low), (high-prior_close).abs(),
                                (low-prior_close).abs()], axis=1).max(axis=1)
        x["atr14_pct"] = true_range.rolling(14, min_periods=14).mean().div(close)
        x["drawdown20"] = close.div(close.rolling(20, min_periods=20).max()).sub(1)
        x["rv20"] = ret1.rolling(20, min_periods=20).std() * np.sqrt(252)
        for day in sessions:
            row = x.loc[day]
            if pd.isna(row.close):
                continue
            past = group.loc[group.index <= day]
            available = past.available_at.max()
            digest = _receipt_digest(day, past.receipt_sha256.dropna().tolist(),
                                     version="L1_SECURITY_FEATURES_V1:"+str(security_id))
            for feature, col, scale in (
                ("security_return_1", "ret_1", 100.0),
                ("security_return_5", "ret_5", 100.0),
                ("security_return_20", "ret_20", 100.0),
                ("security_return_60", "ret_60", 100.0),
                ("atr14_pct", "atr14_pct", 100.0),
                ("drawdown20", "drawdown20", 100.0),
                ("rv20", "rv20", 100.0),
            ):
                security_rows.append(_security_record(day, security_id, symbol, feature,
                    row[col] * scale if pd.notna(row[col]) else np.nan,
                    "%", available, digest, source=str(provider), price_basis=str(price_basis)))
            if symbol in _SECTOR_ETFS and pd.notna(row.ret_5) and pd.notna(benchmark_ret5.loc[day]):
                security_rows.append(_security_record(day, security_id, symbol, "sector_relative_5",
                    (row.ret_5-benchmark_ret5.loc[day])*100, "%",
                    available, digest, source=str(provider), price_basis=str(price_basis)))
            if symbol in _STYLE_ETFS and pd.notna(row.ret_5) and pd.notna(benchmark_ret5.loc[day]):
                security_rows.append(_security_record(day, security_id, symbol, "style_relative_5",
                    (row.ret_5-benchmark_ret5.loc[day])*100, "%",
                    available, digest, source=str(provider), price_basis=str(price_basis)))
    return security_rows


def _breadth_features(bars, cutoffs, universe, min_coverage):
    if universe is None or universe.empty:
        return [], [{"session_date": d.date().isoformat(), "dimension": "breadth",
                     "status": "MISSING", "reason": "NO_DATED_UNIVERSE",
                     "coverage_n": 0, "expected_n": None} for d in cutoffs.session_date]
    u = _dates(universe, "UNIVERSE")
    required = {"universe_id", "security_id", "symbol", "is_member",
                "known_at", "snapshot_complete", "provider", "receipt_sha256"}
    if required - set(u.columns):
        raise ValueError("UNIVERSE_MISSING_COLUMNS:" + ",".join(sorted(required-set(u.columns))))
    if u.duplicated(["session_date", "universe_id", "security_id"]).any():
        raise ValueError("DUPLICATE_UNIVERSE_MEMBERSHIP")
    if not u.is_member.map(lambda v: type(v) in (bool, np.bool_)).all():
        raise ValueError("UNIVERSE_MEMBERSHIP_NOT_BOOLEAN")
    if not u.snapshot_complete.map(lambda v: type(v) in (bool, np.bool_)).all():
        raise ValueError("UNIVERSE_COMPLETENESS_NOT_BOOLEAN")
    if not u.receipt_sha256.astype(str).str.fullmatch(_SHA).all():
        raise ValueError("UNIVERSE_RECEIPT_SHA256_INVALID")
    u["known_at"] = u.known_at.map(_aware_utc)
    u = u.merge(cutoffs, on="session_date", how="left", validate="many_to_one")
    if u.decision_cutoff_utc.isna().any() or (u.known_at > u.decision_cutoff_utc).any():
        raise ValueError("UNIVERSE_NOT_KNOWN_AT_DECISION_CUTOFF")
    sessions = pd.DatetimeIndex(cutoffs.session_date)
    indexed = {}
    for security_id, group in bars.groupby("security_id", sort=False):
        x = group.sort_values("session_date").set_index("session_date").reindex(sessions)
        close = pd.to_numeric(x.close, errors="coerce")
        high = pd.to_numeric(x.high, errors="coerce")
        low = pd.to_numeric(x.low, errors="coerce")
        volume = pd.to_numeric(x.volume, errors="coerce")
        ret = close.pct_change(fill_method=None)
        indexed[security_id] = pd.DataFrame({
            "ret": ret, "close": close, "volume": volume,
            "ma20": close.rolling(20, min_periods=20).mean(),
            "ma50": close.rolling(50, min_periods=50).mean(),
            "ma200": close.rolling(200, min_periods=200).mean(),
            "prev_high252": high.shift(1).rolling(252, min_periods=252).max(),
            "prev_low252": low.shift(1).rolling(252, min_periods=252).min(),
        }, index=sessions)
    output, quality = [], []
    ad_line, ad_line_started, ad_line_valid = 0, False, True
    ad_line_universe_id, ad_line_membership_basis = None, None
    for cutoff in cutoffs.itertuples(index=False):
        day = cutoff.session_date
        rows = u.loc[u.session_date.eq(day)]
        if rows.empty:
            if ad_line_started:
                ad_line_valid = False
            quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                            "status": "MISSING", "reason": "MISSING_UNIVERSE_DAY",
                            "coverage_n": 0, "expected_n": None})
            continue
        if rows.universe_id.nunique()!=1:
            if ad_line_started:
                ad_line_valid = False
            quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                            "status": "PARTIAL", "reason": "MULTIPLE_UNIVERSE_IDS",
                            "coverage_n": 0, "expected_n": int(rows.is_member.sum())})
            continue
        if not rows.snapshot_complete.all():
            if ad_line_started:
                ad_line_valid = False
            quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                            "status": "PARTIAL", "reason": "UNIVERSE_SNAPSHOT_NOT_ATTESTED_COMPLETE",
                            "coverage_n": 0, "expected_n": int(rows.is_member.sum())})
            continue
        current_universe_id=str(rows.universe_id.iloc[0])
        current_membership_basis=(str(rows.membership_basis.iloc[0])
                                  if "membership_basis" in rows else None)
        if ad_line_universe_id is None:
            ad_line_universe_id=current_universe_id
            ad_line_membership_basis=current_membership_basis
        elif (current_universe_id!=ad_line_universe_id or
              current_membership_basis!=ad_line_membership_basis):
            ad_line_valid=False
        members = rows.loc[rows.is_member]
        expected = len(members)
        if expected < 30:
            if ad_line_started:
                ad_line_valid = False
            quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                            "status": "PARTIAL", "reason": "UNIVERSE_TOO_SMALL",
                            "coverage_n": 0, "expected_n": expected})
            continue
        current = []
        for member in members.itertuples(index=False):
            values = indexed.get(member.security_id)
            if values is None:
                continue
            record = values.loc[day]
            if pd.notna(record.close) and pd.notna(record.ret):
                current.append(record)
        coverage = len(current) / expected if expected else 0
        if coverage < min_coverage:
            if ad_line_started:
                ad_line_valid = False
            quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                            "status": "PARTIAL", "reason": "BAR_COVERAGE_BELOW_THRESHOLD",
                            "coverage_n": len(current), "expected_n": expected})
            continue
        data = pd.DataFrame(current)
        advances = int((data.ret > 0).sum())
        declines = int((data.ret < 0).sum())
        unchanged = int((data.ret == 0).sum())
        up_volume = float(data.loc[data.ret > 0, "volume"].sum())
        down_volume = float(data.loc[data.ret < 0, "volume"].sum())
        total_volume = up_volume + down_volume
        trin = ((advances / declines) / (up_volume / down_volume)
                if advances and declines and up_volume > 0 and down_volume > 0 else np.nan)
        if not ad_line_started:
            ad_line_started = True
            ad_line = advances - declines
        elif ad_line_valid:
            ad_line += advances - declines
        daily_bars = bars.loc[bars.session_date.eq(day) & bars.security_id.isin(members.security_id)]
        available = max(daily_bars.available_at.max(), members.known_at.max())
        digest = _receipt_digest(day,
            daily_bars.receipt_sha256.tolist()+members.receipt_sha256.tolist(),
            version="L1_BREADTH_FEATURES_V1")
        metrics = [
            ("advances", advances, "只"), ("declines", declines, "只"),
            ("ad_line", ad_line if ad_line_valid else np.nan, "累计只数"),
            ("up_volume_share", up_volume / total_volume * 100 if total_volume else np.nan, "%"),
            ("downside_sync_share", float((data.ret < 0).mean() * 100), "%"),
            ("stock_dispersion_1", float(data.ret.std(ddof=0) * 100), "%"),
            ("pct_above_ma20", float((data.loc[data.ma20.notna(),"close"] >
                                      data.loc[data.ma20.notna(),"ma20"]).mean() * 100)
             if data.ma20.notna().sum()/expected >= min_coverage else np.nan, "%"),
            ("pct_above_ma50", float((data.loc[data.ma50.notna(),"close"] >
                                      data.loc[data.ma50.notna(),"ma50"]).mean() * 100)
             if data.ma50.notna().sum()/expected >= min_coverage else np.nan, "%"),
            ("pct_above_ma200", float((data.loc[data.ma200.notna(),"close"] >
                                       data.loc[data.ma200.notna(),"ma200"]).mean() * 100)
             if data.ma200.notna().sum()/expected >= min_coverage else np.nan, "%"),
            ("new_high_52w", int((data.loc[data.prev_high252.notna(),"close"] >
                                  data.loc[data.prev_high252.notna(),"prev_high252"]).sum())
             if data.prev_high252.notna().sum()/expected >= min_coverage else np.nan, "只"),
            ("new_low_52w", int((data.loc[data.prev_low252.notna(),"close"] <
                                 data.loc[data.prev_low252.notna(),"prev_low252"]).sum())
             if data.prev_low252.notna().sum()/expected >= min_coverage else np.nan, "只"),
            ("trin", trin, "倍"),
        ]
        for feature_id, value, unit in metrics:
            feature_dimension = FEATURE_BY_KEY[feature_id].dimension
            output.append(_record(day, feature_dimension, feature_id, value, unit,
                available, digest, quality="OBSERVED" if pd.notna(value) else "MISSING",
                pit="PIT_UNVERIFIED_CURRENT_UNIVERSE", coverage_n=len(current), expected_n=expected,
                source="CURRENT_COMPLETE_UNIVERSE_SNAPSHOT",
                metadata={"universe_id": str(members.universe_id.iloc[0]),
                          "advances": advances, "declines": declines,
                          "unchanged": unchanged, "coverage": coverage,
                          "pit_attested": False}))
        quality.append({"session_date": day.date().isoformat(), "dimension": "breadth",
                        "status": "OBSERVED_CURRENT_SNAPSHOT_NOT_PIT",
                        "reason": "CURRENT_UNIVERSE_ONLY",
                        "coverage_n": len(current), "expected_n": expected})
    return output, quality


def _market_level_features(bars, cutoffs):
    out = []
    by_symbol = {symbol: group.sort_values("session_date").set_index("session_date")
                 for symbol, group in bars.groupby("symbol", sort=False)}
    spy = by_symbol.get("SPY")
    if spy is None:
        return out
    sessions = pd.DatetimeIndex(cutoffs.session_date)
    close = pd.to_numeric(spy.close.reindex(sessions), errors="coerce")
    high = pd.to_numeric(spy.high.reindex(sessions), errors="coerce")
    low = pd.to_numeric(spy.low.reindex(sessions), errors="coerce")
    ret = close.pct_change(fill_method=None)
    rv = {w: ret.rolling(w, min_periods=w).std() * np.sqrt(252) for w in (5,20,60)}
    downside = ret.clip(upper=0).pow(2).rolling(20, min_periods=20).mean().mul(252).pow(.5)
    dd20 = close.div(close.rolling(20, min_periods=20).max()).sub(1)
    atr = pd.concat([high-low, (high-close.shift(1)).abs(),
                     (low-close.shift(1)).abs()], axis=1).max(axis=1).rolling(14, min_periods=14).mean().div(close)
    source = str(spy.provider.iloc[-1])
    for i, day in enumerate(sessions):
        if pd.isna(close.loc[day]):
            continue
        source_rows = spy.loc[spy.index <= day]
        available = source_rows.available_at.max()
        digest = _receipt_digest(day, source_rows.receipt_sha256.tolist())
        for feature_id, value, unit, scale in (
            ("spy_return_1", ret.loc[day], "%", 100.0),
            ("spy_return_5", close.loc[day] / close.shift(5).loc[day] - 1 if pd.notna(close.shift(5).loc[day]) else np.nan, "%", 100.0),
            ("spy_return_20", close.loc[day] / close.shift(20).loc[day] - 1 if pd.notna(close.shift(20).loc[day]) else np.nan, "%", 100.0),
            ("spy_return_60", close.loc[day] / close.shift(60).loc[day] - 1 if pd.notna(close.shift(60).loc[day]) else np.nan, "%", 100.0),
            ("rv5", rv[5].loc[day], "%", 100.0), ("rv20", rv[20].loc[day], "%", 100.0),
            ("rv60", rv[60].loc[day], "%", 100.0), ("downside_rv20", downside.loc[day], "%", 100.0),
            ("drawdown20", dd20.loc[day], "%", 100.0), ("atr14_pct", atr.loc[day], "%", 100.0),
        ):
            out.append(_record(day, FEATURE_BY_KEY[feature_id].dimension, feature_id,
                value*scale if pd.notna(value) else np.nan, unit, available, digest,
                quality="OBSERVED" if pd.notna(value) else "MISSING",
                source=source, metadata={"benchmark": "SPY", "price_basis": str(spy.price_basis.iloc[-1])}))
        sector_returns, sector_sources, sector_available = {}, [], []
        for symbol in _SECTOR_ETFS:
            group = by_symbol.get(symbol)
            if group is None:
                continue
            series = pd.to_numeric(group.close.reindex(sessions), errors="coerce")
            prior = series.shift(5)
            if pd.notna(series.loc[day]) and pd.notna(prior.loc[day]) and prior.loc[day] > 0:
                sector_returns[symbol] = series.loc[day] / prior.loc[day] - 1
                sector_available.append(group.loc[day, "available_at"])
                sector_sources.extend(group.loc[group.index <= day, "receipt_sha256"].dropna().tolist())
        if len(sector_returns) >= 6:
            digest2 = _receipt_digest(day, sector_sources, version="L1_SECTOR_ETF_FEATURES_V1")
            sector_avail = max(sector_available)
            out.append(_record(day, "correlation", "sector_dispersion_5",
                float(np.std(list(sector_returns.values()), ddof=0) * 100), "%",
                sector_avail, digest2, coverage_n=len(sector_returns),
                expected_n=len(_SECTOR_ETFS), source="ALPACA_SECTOR_ETF_CROSS_SECTION",
                metadata={"symbols": sorted(sector_returns), "proxy": True}))
            returns = pd.DataFrame({
                s: pd.to_numeric(by_symbol[s].close.reindex(sessions), errors="coerce").pct_change(fill_method=None)
                for s in sector_returns
            })
            window = returns.iloc[max(0, i-19):i+1]
            corr_value = np.nan
            if len(window) == 20 and window.notna().all().all():
                corr = window.corr().to_numpy()
                upper = corr[np.triu_indices_from(corr, 1)]
                corr_value = float(np.mean(upper)) if len(upper) else np.nan
            out.append(_record(day, "correlation", "sector_corr_20", corr_value,
                "corr", sector_avail, digest2,
                quality="OBSERVED" if pd.notna(corr_value) else "MISSING",
                coverage_n=len(sector_returns), expected_n=len(_SECTOR_ETFS),
                source="ALPACA_SECTOR_ETF_CROSS_SECTION",
                metadata={"symbols": sorted(sector_returns), "proxy": True}))
    return out


def _external_features(external, cutoffs):
    if external is None or external.empty:
        return []
    x = _dates(external, "EXTERNAL")
    required = {"feature_id", "value", "unit", "source", "provider", "available_at", "receipt_sha256"}
    if required - set(x.columns):
        raise ValueError("EXTERNAL_FEATURES_MISSING_COLUMNS")
    x["available_at"] = x.available_at.map(_aware_utc)
    x = x.merge(cutoffs, on="session_date", how="left", validate="many_to_one")
    if x.decision_cutoff_utc.isna().any() or (x.available_at > x.decision_cutoff_utc).any():
        raise ValueError("EXTERNAL_FEATURE_NOT_AVAILABLE_AT_CUTOFF")
    records = []
    for row in x.itertuples(index=False):
        feature = FEATURE_BY_KEY.get(row.feature_id)
        if feature is None or feature.dimension == "path":
            raise ValueError("EXTERNAL_FEATURE_NOT_REGISTERED_OR_IS_OUTCOME")
        digest = str(row.receipt_sha256)
        if not _SHA.fullmatch(digest):
            raise ValueError("EXTERNAL_RECEIPT_SHA256_INVALID")
        records.append(_record(row.session_date, feature.dimension, row.feature_id,
            row.value, row.unit, row.available_at, digest,
            quality="OBSERVED", pit=getattr(row, "pit_status", "PIT_UNVERIFIED"),
            source=row.source, provider=row.provider, metadata={"external": True}))
    return records


def _event_features(events, cutoffs):
    if events is None or events.empty:
        return []
    x = events.copy()
    required = {"event_id", "event_type", "scheduled_at", "schedule_known_at",
                "source", "receipt_sha256"}
    if required - set(x.columns):
        raise ValueError("EVENTS_MISSING_COLUMNS")
    x["scheduled_at"] = x.scheduled_at.map(_aware_utc)
    x["schedule_known_at"] = x.schedule_known_at.map(_aware_utc)
    if "released_at" in x:
        x["released_at"] = x.released_at.map(lambda v: _aware_utc(v, optional=True))
    if "consensus_known_at" in x:
        x["consensus_known_at"] = x.consensus_known_at.map(lambda v: _aware_utc(v, optional=True))
    x["event_type"] = x.event_type.astype(str).str.upper()
    records = []
    for cutoff in cutoffs.itertuples(index=False):
        known = x.loc[x.schedule_known_at.le(cutoff.decision_cutoff_utc)]
        for event_type, feature_id in (("CPI","days_to_cpi"),("NFP","days_to_nfp"),("FOMC","days_to_fomc")):
            future = known.loc[(known.event_type == event_type) &
                               (known.scheduled_at > cutoff.decision_cutoff_utc)].sort_values("scheduled_at")
            if future.empty:
                continue
            row = future.iloc[0]
            days = (row.scheduled_at.date() - cutoff.session_date.date()).days
            digest = str(row.receipt_sha256)
            records.append(_record(cutoff.session_date, "events", feature_id, days, "days",
                row.schedule_known_at, digest, pit="CURRENT_SCHEDULE_NOT_HISTORICAL_PIT",
                source=row.source, metadata={"event_id": row.event_id,
                "scheduled_at": row.scheduled_at.isoformat()}))
        required_surprise = {"actual_value", "consensus_value", "released_at", "consensus_known_at"}
        if required_surprise <= set(x.columns):
            released = known.loc[x.released_at.notna() & x.consensus_known_at.notna() &
                x.released_at.le(cutoff.decision_cutoff_utc) &
                x.consensus_known_at.le(cutoff.decision_cutoff_utc) &
                x.actual_value.notna() & x.consensus_value.notna()]
            if not released.empty:
                row = released.sort_values("released_at").iloc[-1]
                records.append(_record(cutoff.session_date, "events", "macro_surprise",
                    float(row.actual_value) - float(row.consensus_value), "native units",
                    max(row.released_at, row.consensus_known_at), str(row.receipt_sha256),
                    pit="PIT_UNVERIFIED_UNLESS_CONSENSUS_VINTAGE_ATTESTED",
                    source=row.source, metadata={"event_id": row.event_id,
                    "event_type": row.event_type, "actual": row.actual_value,
                    "consensus": row.consensus_value}))
    return records


def compute_forward_path_labels(bars, cutoffs, *, benchmark="SPY",
                                up_barrier=0.02, down_barrier=-0.015,
                                horizons=(1,3,5)):
    """Compute future labels separately; never returns predictor feature rows."""
    c = _cutoffs(cutoffs)
    b = _bars(bars, c)
    px = b.loc[b.symbol.eq(benchmark)].sort_values("session_date").set_index("session_date")
    sessions = list(c.session_date)
    labels = []
    for i, day in enumerate(sessions):
        for horizon in horizons:
            if i + horizon >= len(sessions):
                continue
            window_days = sessions[i+1:i+horizon+1]
            path = px.reindex(window_days)
            if path[["open","high","low","close"]].isna().any().any():
                continue
            entry = float(path.open.iloc[0])
            if entry <= 0:
                continue
            exit_price = float(path.close.iloc[-1])
            mfe = float(path.high.max()/entry - 1)
            mae = float(path.low.min()/entry - 1)
            for day2, bar in path.iterrows():
                hit_up = float(bar.high/entry - 1) >= up_barrier
                hit_down = float(bar.low/entry - 1) <= down_barrier
                if hit_up and hit_down:
                    first = "ORDER_AMBIGUOUS"
                    break
                if hit_up:
                    first = "UP_FIRST"
                    break
                if hit_down:
                    first = "DOWN_FIRST"
                    break
            else:
                first = "NO_TOUCH"
            digest = _receipt_digest(day, path.receipt_sha256.tolist(), version="L1_PATH_LABELS_V1")
            labels.append({
                "session_date": day.date().isoformat(), "horizon": horizon,
                "entry_date": window_days[0].date().isoformat(),
                "exit_date": window_days[-1].date().isoformat(),
                "forward_return": exit_price/entry - 1, "mfe": mfe, "mae": mae,
                "first_touch": first, "status": "OUTCOME_ONLY_NOT_PREDICTOR",
                "receipt_sha256": digest, "available_at": path.available_at.max().isoformat(),
                "up_barrier": up_barrier, "down_barrier": down_barrier,
            })
    return pd.DataFrame(labels)


def compute_l1_market_features(bars, cutoffs, *, universe=None, external=None,
                               events=None, min_breadth_coverage=0.98):
    """Return market observations, per-security features, breadth quality and labels."""
    c = _cutoffs(cutoffs)
    b = _bars(bars, c)
    observations = _market_level_features(b, c)
    security_features = _per_security_features(b, c)
    breadth, quality = _breadth_features(b, c, universe, min_breadth_coverage)
    observations.extend(breadth)
    observations.extend(_external_features(external, c))
    observations.extend(_event_features(events, c))
    unique = {}
    for row in observations:
        key = (row["session_date"], row["feature_id"], row["provider"],
               row["vintage_id"], row["receipt_sha256"])
        unique[key] = row
    observations = sorted(unique.values(), key=lambda x: (x["session_date"], x["dimension"], x["feature_id"]))
    labels = compute_forward_path_labels(b, c)
    return {
        "observations": pd.DataFrame(observations),
        "security_features": pd.DataFrame(security_features),
        "breadth_quality": pd.DataFrame(quality),
        "path_labels": labels,
        "policy": {"historical_pit_verified": False, "forecast_eligible": False,
                   "trade_eligible": False, "path_labels_separate_from_predictors": True},
    }
