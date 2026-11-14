"""L1 research-only daily market observatory.

No vendor feed, PIT stock universe, forecast probability, or live trading
eligibility is inferred from caller-provided tables. All observations are
limited to data actually available by each session's decision cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Domain:
    key: str
    name: str
    phase: str
    required_source: str


DOMAINS = (
    Domain('price', 'Price / trend', 'P0', 'daily OHLCV'),
    Domain('breadth', 'Equity breadth', 'P0', 'PIT stock membership + daily OHLCV'),
    Domain('volatility', 'Volatility structure', 'P0', 'daily OHLCV; options for IV'),
    Domain('options_pricing', 'Options pricing', 'P1', 'licensed historical option surface'),
    Domain('options_positioning', 'Options hedging / positioning', 'P2', 'options OI + assumptions'),
    Domain('microstructure', 'Liquidity microstructure', 'P2', 'bid/ask / order-book feed'),
    Domain('correlation', 'Correlation / dispersion', 'P0', 'cross-sectional daily OHLCV'),
    Domain('cross_asset', 'Cross-asset transmission', 'P1', 'ETF / rates / spreads'),
    Domain('positioning', 'Crowding / positioning', 'P2', 'dated reports and ETF flows'),
    Domain('events', 'Macro and event calendar', 'P1', 'release timestamps + revisions'),
    Domain('funding', 'Funding / financial conditions', 'P2', 'rate / funding series'),
    Domain('path', 'Return path / tail events', 'P0', 'timestamped OHLCV; intraday for same-bar order'),
)

_REQUIRED_BARS = {'date', 'security_id', 'symbol', 'open', 'high', 'low',
                  'close', 'volume', 'available_at'}
_REQUIRED_CLOCK = {'date', 'decision_cutoff_utc'}
_REQUIRED_UNIVERSE = {'date', 'security_id', 'is_member', 'available_at'}


def _sessions(data: pd.DataFrame, name: str, required: set[str]) -> pd.DataFrame:
    if not isinstance(data, pd.DataFrame) or required - set(data.columns):
        raise ValueError(f'{name} missing fields: {sorted(required - set(getattr(data, "columns", [])))}')
    out = data.copy()
    out['date'] = pd.to_datetime(out['date'], errors='raise')
    if out.date.dt.tz is not None or out.date.isna().any() or (out.date != out.date.dt.normalize()).any():
        raise ValueError(f'{name} dates must be timezone-naive sessions')
    if 'available_at' in out:
        out['available_at'] = pd.to_datetime(out['available_at'], utc=True)
    return out


def compute_l1_observations(
    bars: pd.DataFrame,
    cutoffs: pd.DataFrame,
    universe: pd.DataFrame | None = None,
    *,
    benchmark: str = 'SPY',
    min_breadth_coverage: float = 0.98,
    min_breadth_members: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute dated price and optional breadth observables, never predictions.

    Bars and universe records arriving after their own session cutoff are
    rejected, not silently backfilled. Breadth needs a complete daily PIT
    membership table; its mere presence does not constitute PIT attestation.
    Returns (dated observations, per-session coverage and block reasons).
    """
    if not 0 < min_breadth_coverage <= 1 or min_breadth_members < 2:
        raise ValueError('Invalid breadth minimums')
    b = _sessions(bars, 'bars', _REQUIRED_BARS)
    c = _sessions(cutoffs, 'cutoffs', _REQUIRED_CLOCK)
    c['decision_cutoff_utc'] = pd.to_datetime(c['decision_cutoff_utc'], utc=True)
    if c.date.duplicated().any() or c.decision_cutoff_utc.isna().any():
        raise ValueError('One valid cutoff is required per session')
    if b.duplicated(['date', 'security_id']).any():
        raise ValueError('Duplicate security bars for a session')
    if b[['security_id', 'symbol']].isna().any().any():
        raise ValueError('Unidentified securities')
    for field in ('open', 'high', 'low', 'close', 'volume'):
        b[field] = pd.to_numeric(b[field], errors='coerce')
    if (b[['open', 'high', 'low', 'close', 'volume']].isna().any().any()
            or not np.isfinite(b[['open', 'high', 'low', 'close', 'volume']].to_numpy()).all()
            or (b[['open', 'high', 'low', 'close']] <= 0).any().any()
            or (b.volume < 0).any()
            or (b.high < b[['open', 'close', 'low']].max(axis=1)).any()
            or (b.low > b[['open', 'close', 'high']].min(axis=1)).any()):
        raise ValueError('Nonfinite or inconsistent OHLCV')
    b = b.merge(c, on='date', how='left', validate='many_to_one')
    if b.decision_cutoff_utc.isna().any() or b.available_at.isna().any():
        raise ValueError('Missing decision cutoff or bar available_at')
    if (b.available_at > b.decision_cutoff_utc).any():
        raise ValueError('Bar arrives after its session decision cutoff')
    if (b.groupby('date').symbol.nunique() != b.groupby('date').security_id.nunique()).any():
        raise ValueError('Ambiguous same-day security identity')
    b = b.sort_values(['security_id', 'date']).reset_index(drop=True)
    session_position = {d: i for i, d in enumerate(c.sort_values('date').date)}
    b['session_position'] = b.date.map(session_position)
    grouped = b.groupby('security_id', sort=False)
    b['prior_close'] = grouped.close.shift(1)
    gap1 = b.session_position.sub(grouped.session_position.shift(1)).eq(1)
    b['ret_1'] = b.close.div(b.prior_close).sub(1).where(gap1)
    b['ma20'] = grouped.close.transform(lambda v: v.rolling(20, min_periods=20).mean())
    b['ma20'] = b.ma20.where(b.session_position.sub(grouped.session_position.shift(19)).eq(19))
    b['prev_low20'] = grouped.close.transform(lambda v: v.shift(1).rolling(20, min_periods=20).min())
    b['prev_low20'] = b.prev_low20.where(b.session_position.sub(grouped.session_position.shift(20)).eq(20))
    b['new_low20'] = (b.close < b.prev_low20).where(b.prev_low20.notna())
    b['dollar_volume'] = b.close * b.volume
    px = b.loc[b.symbol.eq(benchmark)].sort_values('date').copy()
    if px.empty or px.date.duplicated().any() or set(px.date) != set(c.date):
        raise ValueError('Missing or ambiguous benchmark session')
    output = px[['date', 'decision_cutoff_utc', 'close']].rename(columns={'close': 'benchmark_close'})
    output['market_return_1'] = px.ret_1.to_numpy()
    for w in (5, 20):
        output[f'market_return_{w}'] = px.close.div(px.close.shift(w)).sub(1).to_numpy()
        output[f'market_vol_{w}'] = (px.ret_1.rolling(w, min_periods=w).std() * np.sqrt(252)).to_numpy()
    output['market_vol_ratio'] = output.market_vol_5.div(output.market_vol_20.replace(0, np.nan))
    output['market_overnight_return'] = px.open.div(px.prior_close).sub(1).to_numpy()
    output['market_intraday_return'] = px.close.div(px.open).sub(1).to_numpy()
    output['market_close_location'] = ((px.close - px.low) / (px.high - px.low).replace(0, np.nan)).to_numpy()
    downside = px.ret_1.clip(upper=0)
    output['market_downside_rv20'] = (downside.pow(2).rolling(20, min_periods=20).mean() * 252).pow(.5).to_numpy()
    for name, positive, negative in [('equal_weight', 'RSP', 'SPY'),
                                      ('credit_proxy', 'HYG', 'LQD'),
                                      ('small_cap', 'IWM', 'SPY')]:
        subset = b.loc[b.symbol.isin((positive, negative))].pivot(index='date', columns='symbol', values='close')
        if positive in subset and negative in subset:
            ratio = subset[positive] / subset[negative]
            output[f'{name}_relative_return_5'] = output.date.map(ratio.div(ratio.shift(5)).sub(1))
        else:
            output[f'{name}_relative_return_5'] = np.nan
    quality = c[['date']].copy().sort_values('date')
    quality['benchmark_present'] = quality.date.isin(px.date)
    quality['breadth_universe_size'] = 0
    quality['breadth_bar_coverage'] = np.nan
    quality['breadth_20d_feature_coverage'] = np.nan
    quality['breadth_status'] = 'NO_PIT_UNIVERSE'
    breadth_cols = ('breadth_up_share', 'breadth_above_ma20_share',
                    'breadth_new_low20_share', 'breadth_down_dollar_volume_share')
    for col in breadth_cols:
        output[col] = np.nan
    if universe is not None:
        u = _sessions(universe, 'universe', _REQUIRED_UNIVERSE)
        if u.duplicated(['date', 'security_id']).any() or u.available_at.isna().any():
            raise ValueError('Duplicate or undated daily membership')
        if not u.is_member.map(lambda x: type(x) in (bool, np.bool_)).all():
            raise ValueError('is_member must be boolean')
        u = u.merge(c, on='date', how='left', validate='many_to_one')
        if u.decision_cutoff_utc.isna().any() or (u.available_at > u.decision_cutoff_utc).any():
            raise ValueError('Membership not known at its decision cutoff')
        for day, members in u.loc[u.is_member].groupby('date'):
            mask = quality.date.eq(day)
            eligible = members.security_id.unique()
            total = len(eligible)
            quality.loc[mask, 'breadth_universe_size'] = total
            if total < min_breadth_members:
                quality.loc[mask, 'breadth_status'] = 'INSUFFICIENT_MEMBERS'
                continue
            daily = b.loc[b.date.eq(day) & b.security_id.isin(eligible)]
            if daily.security_id.nunique() > total:
                raise ValueError('Membership and bars mismatch')
            coverage = len(daily) / total
            quality.loc[mask, 'breadth_bar_coverage'] = coverage
            eligible20 = daily[['ma20', 'prev_low20']].notna().all(axis=1).mean() if len(daily) else 0.0
            quality.loc[mask, 'breadth_20d_feature_coverage'] = eligible20
            if coverage < min_breadth_coverage:
                quality.loc[mask, 'breadth_status'] = 'INSUFFICIENT_BAR_COVERAGE'
                continue
            quality.loc[mask, 'breadth_status'] = 'RESEARCH_ONLY_UNATTESTED_PIT'
            rowmask = output.date.eq(day)
            if not rowmask.any():
                continue
            if daily.ret_1.notna().all():
                output.loc[rowmask, 'breadth_up_share'] = (daily.ret_1 > 0).mean()
                denominator = daily.dollar_volume.sum()
                if denominator > 0:
                    output.loc[rowmask, 'breadth_down_dollar_volume_share'] = (
                        daily.loc[daily.ret_1 < 0, 'dollar_volume'].sum() / denominator)
            if eligible20 >= min_breadth_coverage:
                complete20 = daily.loc[daily[['ma20', 'prev_low20']].notna().all(axis=1)]
                output.loc[rowmask, 'breadth_above_ma20_share'] = (complete20.close > complete20.ma20).mean()
                output.loc[rowmask, 'breadth_new_low20_share'] = (complete20.close < complete20.prev_low20).mean()
        # Zero-member dates are distinct from missing membership snapshots.
        known_days = set(u.date)
        active_days = set(u.loc[u.is_member, 'date'])
        quality.loc[quality.date.isin(known_days - active_days), 'breadth_status'] = 'INSUFFICIENT_MEMBERS'
        quality.loc[~quality.date.isin(known_days), 'breadth_status'] = 'MISSING_UNIVERSE_DAY'
    output = output.merge(quality, on='date', how='left', validate='one_to_one')
    output['research_only'] = True
    output['forecast_eligible'] = False
    return output.sort_values('date').reset_index(drop=True), quality.reset_index(drop=True)


def scan_l1_anomalies(observations: pd.DataFrame, *, lookback: int = 60,
                      min_history: int = 20, z_limit: float = 2.0) -> pd.DataFrame:
    """Scan anomalies relative to strictly earlier observations; no forecasts."""
    if lookback < min_history or min_history < 10 or z_limit <= 0:
        raise ValueError('Invalid anomaly window')
    if observations.date.duplicated().any() or not observations.date.is_monotonic_increasing:
        raise ValueError('Observations must have unique increasing sessions')
    fields = ('market_return_1', 'market_vol_ratio', 'market_downside_rv20',
              'breadth_up_share', 'breadth_new_low20_share',
              'breadth_down_dollar_volume_share', 'credit_proxy_relative_return_5')
    result = []
    for field in fields:
        if field not in observations:
            continue
        values = pd.to_numeric(observations[field], errors='coerce')
        past = values.shift(1).rolling(lookback, min_periods=min_history)
        mean, std = past.mean(), past.std()
        z = (values - mean) / std.replace(0, np.nan)
        for i in np.flatnonzero(z.abs().ge(z_limit).fillna(False).to_numpy()):
            result.append({'date': observations.date.iloc[i], 'feature': field,
                           'value': float(values.iloc[i]), 'past_mean': float(mean.iloc[i]),
                           'z_score': float(z.iloc[i]), 'status': 'OBSERVATION_ONLY',
                           'predictive_evidence': 'NOT_TESTED'})
    return pd.DataFrame(result, columns=('date','feature','value','past_mean','z_score',
                                          'status','predictive_evidence')).sort_values('date').reset_index(drop=True)