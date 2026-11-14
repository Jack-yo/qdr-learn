"""Current-vintage, ETF-only L1 observation adapter.

This module is deliberately separate from the archived L1 research reader.  It
uses the verified source/availability evidence carried by ``load_real_bundle``
to keep the UI populated when no research archive exists, but it never turns a
current revised snapshot into a PIT observation or a forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_research.data.bundle import load_real_bundle
from quant_research.research.l1_features import DOMAINS, REGISTRY, OPTIONAL_NAMES
from quant_research.clock import TradingClock


STATUS = "CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION"
_DRIVER_FEATURES = ('market_return_1','market_return_5','market_vol_20','market_vol_ratio',
                    'credit_proxy_relative_return_5','sector_corr_20',
                    'market_intraday_return','market_close_location')
_MISSING_REASONS = {
    'breadth':'HISTORICAL_PIT_UNIVERSE_NOT_VERIFIED',
    'options_pricing':'OPTION_PRICING_HISTORY_NOT_CONNECTED',
    'options_positioning':'OPTION_POSITION_HISTORY_NOT_CONNECTED',
    'microstructure':'ORDER_BOOK_HISTORY_NOT_CONNECTED',
    'positioning':'POSITION_FLOW_HISTORY_NOT_CONNECTED',
    'events':'POINT_IN_TIME_EVENT_HISTORY_NOT_CONNECTED',
    'funding':'POINT_IN_TIME_FUNDING_HISTORY_NOT_CONNECTED',
}


def _missing_reason(feature: str, domain: str) -> str:
    if domain in _MISSING_REASONS:
        return _MISSING_REASONS[domain]
    if feature in OPTIONAL_NAMES:
        return 'EXTERNAL_SERIES_NOT_CONNECTED'
    return 'INSUFFICIENT_OR_GAPPED_ETF_HISTORY'


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise ValueError("CURRENT_OBSERVATION_NAIVE_TIMESTAMP")
    return stamp.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def _domain_payload(values: dict[str, float | None], feature_available: dict[str, str | None]) -> list[dict[str, Any]]:
    result = []
    for domain, title in DOMAINS.items():
        names = [name for name, item_domain in REGISTRY.items() if item_domain == domain]
        available = [name for name in names if values.get(name) is not None]
        result.append({
            "id": domain,
            "name": title,
            "status": "OBSERVED" if len(available) == len(names) else ("PARTIAL" if available else "MISSING"),
            "value": values.get(available[0]) if available else None,
            "label": available[0] if available else None,
            "unit": ("ratio" if available and (available[0].endswith("_ratio") or "corr" in available[0]) else "fraction") if available else None,
            "coverage": {"available": len(available), "registered": len(names)},
            "source_available_at": feature_available.get(available[0]) if available else None,
        })
    return result


_SECTOR_ETFS = ("XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE")


def _historical_values(prices: pd.DataFrame):
    """Calculate current-vintage observations on an explicit XNYS session grid."""
    values = {name: None for name in REGISTRY}
    available = {name: None for name in REGISTRY}
    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    for field in ("open", "high", "low", "close"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    frame["available_at"] = pd.to_datetime(frame["available_at"], utc=True, errors="raise")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("CURRENT_OBSERVATION_DUPLICATE_SYMBOL_SESSION")
    clock = TradingClock()
    end=clock.session(str(frame.date.max().date()))
    pos=clock.calendar.sessions.get_loc(end)
    expected=clock.calendar.sessions[max(0,pos-60):pos+1].tz_localize(None)
    frame=frame.loc[frame.date.isin(expected)].copy()
    numeric=frame[['open','high','low','close']]
    valid=(np.isfinite(numeric).all(axis=1) & numeric.gt(0).all(axis=1)
           & frame.high.ge(numeric[['open','close','low']].max(axis=1))
           & frame.low.le(numeric[['open','close','high']].min(axis=1)))
    frame.loc[~valid,['open','high','low','close']]=np.nan
    wide = frame.pivot(index="date", columns="symbol", values="close").reindex(expected)
    avail = frame.pivot(index="date", columns="symbol", values="available_at").reindex(expected)

    def window(symbols: tuple[str, ...], n: int):
        if any(s not in wide for s in symbols) or len(wide) < n:
            return None
        px, at = wide[list(symbols)], avail[list(symbols)]
        if px.iloc[-n:].isna().any().any() or at.iloc[-n:].isna().any().any():
            return None
        return px.iloc[-n:], at.iloc[-n:]

    def set_value(name: str, value: Any, at: pd.DataFrame | pd.Series | None):
        values[name] = _finite(value)
        if values[name] is not None and at is not None:
            latest_at = at.max().max() if isinstance(at, pd.DataFrame) else at.max()
            available[name] = _iso(latest_at)

    windows={}
    for n in (1,3,5,10,20,60):
        data=window(('SPY',),n+1)
        if data is None:continue
        px,at=data
        value=float(px.SPY.iloc[-1]/px.SPY.iloc[0]-1)
        windows[str(n)]={'value':value,'unit':'fraction','available_at':_iso(at.max().max()),
                         'source':'ALPACA:SIP:raw:SPY','basis':'RAW_PRICE_RETURN_NOT_TOTAL_RETURN'}
        if n in (1,5,20):set_value(f'market_return_{n}',value,at)
    spy=window(('SPY',),2)
    if spy is not None:
        px,at=spy
        last=frame.loc[(frame.symbol=='SPY') & (frame.date==expected[-1])].iloc[0]
        set_value('market_overnight_return',last.open/px.SPY.iloc[-2]-1,at)
    for n in (5,20):
        data=window(('SPY',),n+1)
        if data is None:continue
        px,at=data; returns=px.SPY.pct_change(fill_method=None).iloc[1:]
        set_value(f'market_vol_{n}',returns.std()*np.sqrt(252),at)
        if n==20:
            set_value('market_downside_rv20',np.sqrt((returns.clip(upper=0)**2).mean()*252),at)
            if values['market_return_5'] is not None:
                set_value('market_return_acceleration',values['market_return_5']/5-values['market_return_20']/20,at)
    if values['market_vol_5'] is not None and values['market_vol_20']:
        set_value('market_vol_ratio',values['market_vol_5']/values['market_vol_20'],window(('SPY',),21)[1])
    data=window(('SPY',),26)
    if data is not None:
        px,at=data; returns=px.SPY.pct_change(fill_method=None).iloc[1:]
        prior=returns.iloc[:20].std()*np.sqrt(252)
        current=returns.iloc[-20:].std()*np.sqrt(252)
        if np.isfinite(prior) and prior>0:
            set_value('market_vol_change_5',current/prior-1,at)
    data=window(('SPY',),6)
    if data is not None:
        _,at=data; gap=frame.loc[frame.symbol.eq('SPY')].set_index('date').reindex(expected).iloc[-6:]
        set_value('market_gap_abs_5',(gap.open/gap.close.shift(1)-1).abs().iloc[-5:].mean(),at)
    data=window(('SPY',),5)
    if data is not None:
        _,at=data; days=frame.loc[frame.symbol.eq('SPY')].set_index('date').reindex(expected).iloc[-5:]
        set_value('market_range_5',((days.high-days.low)/days.open).mean(),at)

    for name, positive, negative in (("equal_weight", "RSP", "SPY"), ("credit_proxy", "HYG", "LQD"), ("small_cap", "IWM", "SPY")):
        pair = window((positive, negative), 6)
        if pair is not None:
            px, at = pair
            ratio = px[positive] / px[negative]
            set_value(f"{name}_relative_return_5", ratio.iloc[-1] / ratio.iloc[-6] - 1, at)

    sectors5 = window(_SECTOR_ETFS, 6)
    if sectors5 is not None:
        px, at = sectors5
        set_value('sector_dispersion_5',(px.iloc[-1]/px.iloc[0]-1).std(ddof=0),at)
    sectors = window(_SECTOR_ETFS, 21)
    if sectors is not None:
        px, at = sectors
        returns = px.pct_change().iloc[1:]
        corr = returns.iloc[-20:].corr().to_numpy()
        tri = corr[np.triu_indices_from(corr, 1)]
        set_value("sector_corr_20", tri.mean() if np.isfinite(tri).all() else None, at.iloc[-21:])
    return values, available, windows


def build_current_observation(bundle, *, benchmark: str = "SPY", asof: str | None = None) -> dict[str, Any]:
    """Return an ``observations_for_api``-compatible descriptive payload.

    ``bundle`` must be the result of :func:`load_real_bundle`; accepting the
    bundle object also makes source and timestamp checks easy to unit-test.
    Multi-session raw-price indicators are descriptive current-vintage proxies;
    they are not action-adjusted total returns or historical PIT evidence.
    """
    if not hasattr(bundle, "prices") or not hasattr(bundle, "metadata"):
        raise TypeError("bundle must be a DatasetBundle returned by load_real_bundle")
    prices = bundle.prices
    metadata = bundle.metadata
    if prices.empty:
        raise ValueError("CURRENT_OBSERVATION_NO_REAL_DATA")
    if metadata.get('source')!='ALPACA' or metadata.get('feed')!='sip':
        raise ValueError('CURRENT_OBSERVATION_UNSUPPORTED_SOURCE')
    if 'adjustment_basis' in prices and set(prices.adjustment_basis) != {'raw'}:
        raise ValueError('CURRENT_OBSERVATION_MIXED_PRICE_BASIS')
    required = {"date", "symbol", "open", "high", "low", "close", "available_at"}
    missing = required - set(prices.columns)
    if missing:
        raise ValueError(f"CURRENT_OBSERVATION_SCHEMA_MISSING:{sorted(missing)}")
    dates = pd.to_datetime(prices.date, errors="coerce")
    if dates.isna().any():
        raise ValueError("CURRENT_OBSERVATION_INVALID_DATE")
    latest = dates.max().date().isoformat()
    session = asof or metadata.get("asof_date_et") or latest
    if session != latest:
        raise ValueError("CURRENT_OBSERVATION_ASOF_MISMATCH")
    rows = prices.loc[dates.dt.date.astype(str).eq(session) & prices.symbol.eq(benchmark)].copy()
    if len(rows) != 1:
        raise ValueError("CURRENT_OBSERVATION_BENCHMARK_SESSION_MISSING")
    row = rows.iloc[0]
    numeric = {name: _finite(row[name]) for name in ("open", "high", "low", "close")}
    if any(value is None or value <= 0 for value in numeric.values()):
        raise ValueError("CURRENT_OBSERVATION_INVALID_BENCHMARK_BAR")
    if numeric['high'] < max(numeric['open'], numeric['close'], numeric['low']) or numeric['low'] > min(numeric['open'], numeric['close'], numeric['high']):
        raise ValueError("CURRENT_OBSERVATION_INVALID_BENCHMARK_BAR")

    values: dict[str, float | None] = {name: None for name in REGISTRY}
    values["market_intraday_return"] = _finite(numeric["close"] / numeric["open"] - 1.0)
    bar_range = numeric["high"] - numeric["low"]
    values["market_close_location"] = _finite((numeric["close"] - numeric["low"]) / bar_range) if bar_range > 0 else None
    historical, feature_available, windows = _historical_values(prices)
    feature_available['market_intraday_return']=_iso(row.available_at)
    feature_available['market_close_location']=_iso(row.available_at)
    for name, value in historical.items():
        if value is not None:
            values[name] = value
    for stamp in prices.available_at:
        _iso(stamp)
    if "event_time" in prices:
        for stamp in prices.event_time:
            _iso(stamp)
    all_available = pd.to_datetime(prices.available_at, utc=True, errors="raise")
    all_event = pd.to_datetime(prices.event_time, utc=True, errors="raise") if "event_time" in prices else None
    cutoff_stamp = pd.Timestamp(metadata.get("knowledge_cutoff_utc"))
    if cutoff_stamp.tzinfo is None or cutoff_stamp>pd.Timestamp.now(tz='UTC'):
        raise ValueError('CURRENT_OBSERVATION_INVALID_CUTOFF')
    if all_event is not None and (all_event > all_available).any():
        raise ValueError("CURRENT_OBSERVATION_INVALID_TIMING")
    if (all_available > cutoff_stamp).any():
        raise ValueError("CURRENT_OBSERVATION_INVALID_TIMING")
    available_at = _iso(all_available.max())
    source = str(metadata.get("source", row.get("source", "UNKNOWN")))
    source_time = {
        "available_at": available_at,
        "event_time": _iso(row.get("event_time")),
        "knowledge_cutoff_utc": _iso(metadata.get("knowledge_cutoff_utc")),
        "source": source,
        "feed": metadata.get("feed", row.get("feed")),
        "adjustment_basis": row.get("adjustment_basis", metadata.get("adjustment_bases")),
    }
    if not all(source_time[key] for key in ('available_at', 'event_time', 'knowledge_cutoff_utc')):
        raise ValueError('CURRENT_OBSERVATION_MISSING_TIMESTAMP')
    if not pd.Timestamp(source_time['event_time']) <= pd.Timestamp(available_at) <= pd.Timestamp(source_time['knowledge_cutoff_utc']):
        raise ValueError('CURRENT_OBSERVATION_INVALID_TIMING')
    features = []
    groups={'equal_weight_relative_return_5':'RSP,SPY', 'credit_proxy_relative_return_5':'HYG,LQD',
            'small_cap_relative_return_5':'IWM,SPY','sector_corr_20':','.join(_SECTOR_ETFS),
            'sector_dispersion_5':','.join(_SECTOR_ETFS)}
    for feature, domain in REGISTRY.items():
        value = values[feature]
        observed = value is not None
        features.append({
            "id": feature,
            "domain": domain,
            "status": "OBSERVED" if observed else "MISSING",
            "value": value,
            "source": (source + ':SIP:raw:' + groups.get(feature,'SPY')) if observed else None,
            "available_at": feature_available.get(feature) if observed else None,
            "reason": "CURRENT_VINTAGE_ETF_RETROSPECTIVE" if observed else _missing_reason(feature, domain),
            "unit": "ratio" if (feature.endswith("_ratio") or "corr" in feature) else "fraction" if observed else None,
            "research_only": True,
            "research_eligible": False,
            "price_basis": "raw" if observed else None,
            "corporate_action_status": "NOT_INDEPENDENTLY_VERIFIED" if observed else None,
        })
    drivers = [{"label": name, "value": values[name], "unit": "ratio" if name.endswith('_ratio') or 'corr' in name else 'fraction', "status": "OBSERVED",
                "delta": None, "oos_increment": None}
               for name in _DRIVER_FEATURES if values[name] is not None]
    return {
        "schema": "qdr.l1.market.v1",
        "status": STATUS,
        "asof_session": session,
        "knowledge_cutoff_utc": source_time["knowledge_cutoff_utc"],
        "source_snapshot_sha256": metadata.get("snapshot_sha256"),
        "source_time": source_time,
        "source_version_kind": metadata.get("source_version_kind", "current_revised_snapshot"),
        "model_version": None,
        "domains": _domain_payload(values, feature_available),
        "drivers": drivers,
        "features": features,
        "return_windows": windows,
        "feature_rows": 1,
        "historical_pit_verified": False,
        "current_prediction_eligible": False,
        "forecast_eligible": False,
        "forecast": None,
        "research_archive_available": False,
        "limitations": [
            "CURRENT_VINTAGE_NOT_HISTORICAL_PIT",
            "ETF_PROXY_ONLY_NOT_FULL_MARKET_BREADTH",
            "RAW_ETF_HISTORY_CORPORATE_ACTION_CONTINUITY_NOT_PROVEN",
            "DESCRIPTIVE_OBSERVATION_NOT_FORECAST",
        ],
    }


def current_observation_for_api(database: str | Path, *, source: str = "alpaca",
                                asof: str | None = None, cutoff: datetime | str | None = None,
                                start: str | None = None, raw_root: str | Path = Path("data/raw"),
                                symbols: list[str] | None = None, benchmark: str = "SPY") -> dict[str, Any]:
    """Load only the needed 61 sessions of receipt-verified current-vintage data."""
    if source.lower()!='alpaca' or benchmark!='SPY':
        raise ValueError('CURRENT_OBSERVATION_UNSUPPORTED_SOURCE')
    database=Path(database)
    instant=pd.Timestamp(cutoff if cutoff is not None else datetime.now(timezone.utc))
    if instant.tzinfo is None or instant>pd.Timestamp.now(tz='UTC'):
        raise ValueError('CURRENT_OBSERVATION_INVALID_CUTOFF')
    instant=instant.tz_convert('UTC')
    if asof is None:
        from quant_research.data.store import duckdb
        from quant_research.policy import PolicyError
        if (database.parent/'catalog/.maintenance.lock').is_file():
            raise PolicyError('DATA_MAINTENANCE_RUNNING','Retry after data maintenance')
        if not database.is_file():
            raise PolicyError('NO_REAL_DATA','Real warehouse is unavailable')
        with duckdb.connect(str(database),read_only=True) as db:
            day=db.execute('''SELECT max(p.date) FROM prices_daily p JOIN price_observations o
                USING(security_id,date,source,feed,adjustment_basis,raw_sha256)
                WHERE p.symbol='SPY' AND p.source='ALPACA' AND p.feed='sip'
                AND p.adjustment_basis='raw' AND p.event_time<=? AND o.available_at<=? AND o.ingested_at<=?''',
                [instant.to_pydatetime()]*3).fetchone()[0]
        if day is None:raise PolicyError('NO_REAL_DATA','No observable SPY session')
        asof=str(day)
    clock=TradingClock()
    day=clock.session(asof)
    if start is None:
        position=clock.calendar.sessions.get_loc(day)
        start=str(clock.calendar.sessions[max(0,position-60)].date())
    bundle = load_real_bundle(database, source=source, asof=asof, cutoff=instant.to_pydatetime(),
                              start=start, raw_root=Path(raw_root), symbols=symbols)
    return build_current_observation(bundle, benchmark=benchmark, asof=asof)


observations_for_api = current_observation_for_api

