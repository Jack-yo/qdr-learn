"""Synthetic input contract tests; no synthetic result is a market forecast."""
import numpy as np
import pandas as pd
import pytest

from quant_research.research.l1_observatory import (
    DOMAINS, compute_l1_observations, scan_l1_anomalies,
)


def sample(n=85, members=32):
    days = pd.bdate_range('2024-01-02', periods=n)
    symbols = ['SPY', 'RSP', 'HYG', 'LQD', 'IWM'] + [f'AA{i:03d}' for i in range(members)]
    clocks = pd.DataFrame({'date': days,
                           'decision_cutoff_utc': days.tz_localize('UTC') + pd.Timedelta(hours=22)})
    records, universe = [], []
    for i, day in enumerate(days):
        for j, s in enumerate(symbols):
            base = 100 + j * 1.5 + i * (0.2 if j % 2 else -0.08) + np.sin(i / 6 + j) * .3
            price = max(base, 3.0)
            records.append({'date': day, 'security_id': s, 'symbol': s,
                            'open': price * .999, 'high': price * 1.01,
                            'low': price * .99, 'close': price,
                            'volume': 1000 + 4 * j + i,
                            'available_at': pd.Timestamp(day).tz_localize('UTC') + pd.Timedelta(hours=21)})
            if s.startswith('AA'):
                universe.append({'date': day, 'security_id': s, 'is_member': True,
                                 'available_at': pd.Timestamp(day).tz_localize('UTC') + pd.Timedelta(hours=20)})
    return pd.DataFrame(records), clocks, pd.DataFrame(universe)


def test_registry_has_twelve_distinct_research_domains():
    assert len(DOMAINS) == 12
    assert len({d.key for d in DOMAINS}) == 12


def test_breadth_requires_explicit_membership_and_has_no_forecast_status():
    b, clocks, members = sample()
    observed, quality = compute_l1_observations(b, clocks, members)
    assert len(observed) == 85
    assert quality.breadth_status.eq('RESEARCH_ONLY_UNATTESTED_PIT').all()
    assert observed.breadth_up_share.iloc[21:].between(0, 1).all()
    assert observed.breadth_above_ma20_share.iloc[21:].between(0, 1).all()
    assert observed.breadth_new_low20_share.iloc[21:].between(0, 1).all()
    assert not observed.forecast_eligible.any()
    without, q = compute_l1_observations(b, clocks)
    assert without.breadth_up_share.isna().all()
    assert q.breadth_status.eq('NO_PIT_UNIVERSE').all()


def test_missing_coverage_blocks_breadth_but_not_benchmark_price():
    b, clocks, members = sample()
    day = clocks.date.iloc[-1]
    b = b.loc[~(b.date.eq(day) & b.symbol.isin([f'AA{x:03d}' for x in range(5)]))]
    result, quality = compute_l1_observations(b, clocks, members)
    last = result.iloc[-1]
    assert quality.iloc[-1].breadth_status == 'INSUFFICIENT_BAR_COVERAGE'
    assert pd.isna(last.breadth_up_share)
    assert pd.notna(last.market_return_5)


def test_dated_arrival_checks_reject_retroactive_data():
    b, clocks, members = sample()
    b.loc[b.index[-1], 'available_at'] = clocks.decision_cutoff_utc.iloc[-1] + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='after its session decision cutoff'):
        compute_l1_observations(b, clocks, members)
    b, clocks, members = sample()
    members.loc[members.index[-1], 'available_at'] = clocks.decision_cutoff_utc.iloc[-1] + pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match='Membership not known'):
        compute_l1_observations(b, clocks, members)


def test_no_future_row_changes_past_features():
    b, clocks, members = sample()
    a, _ = compute_l1_observations(b, clocks, members)
    future = clocks.date.iloc[-1]
    revised = b.copy()
    flag = revised.date.eq(future) & revised.symbol.eq('SPY')
    revised.loc[flag, ['open', 'high', 'low', 'close']] = [125.0, 126.0, 124.0, 125.5]
    z, _ = compute_l1_observations(revised, clocks, members)
    for field in ('market_return_5', 'market_vol_20', 'market_close_location',
                  'breadth_up_share'):
        pd.testing.assert_series_equal(a[field].iloc[:-1], z[field].iloc[:-1])


def test_anomalies_only_use_past_and_never_imply_prediction():
    b, clocks, members = sample()
    obs, _ = compute_l1_observations(b, clocks, members)
    initial = scan_l1_anomalies(obs)
    changed = obs.copy()
    changed.loc[changed.index[-1], 'market_return_1'] = -0.7
    post = scan_l1_anomalies(changed)
    assert set(post.status) <= {'OBSERVATION_ONLY'}
    assert set(post.predictive_evidence) <= {'NOT_TESTED'}
    assert (post.date == obs.date.iloc[-1]).any()
    pd.testing.assert_frame_equal(initial.loc[initial.date < obs.date.iloc[-1]].reset_index(drop=True),
                                  post.loc[post.date < obs.date.iloc[-1]].reset_index(drop=True))


def test_cli_archive_is_read_only_research_with_sha(tmp_path):
    import json
    from quant_research.workflow.l1_observe import run
    b, clocks, members = sample(n=40)
    files = {'bars': b, 'cutoffs': clocks, 'universe': members}
    for name, frame in files.items():
        frame.to_csv(tmp_path / f'{name}.csv', index=False)
    args = {k: tmp_path / f'{k}.csv' for k in files}
    manifest = run(**args, output=tmp_path / 'study')
    assert manifest['rows'] == 40
    assert manifest['forecast_eligible'] is False
    assert manifest['historical_pit_verified'] is False
    assert manifest['kind'] == 'L1_RESEARCH_OBSERVATIONS_ONLY'
    saved = json.loads((tmp_path / 'study/manifest.json').read_text())
    assert saved['outputs_sha256'] == manifest['outputs_sha256']
    with pytest.raises(FileExistsError):
        run(**args, output=tmp_path / 'study')


def test_missing_one_session_does_not_create_two_day_daily_return():
    b, clocks, members = sample()
    missing_day = clocks.date.iloc[45]
    missing = b.loc[~(b.date.eq(missing_day) & b.symbol.eq('AA005'))]
    obs, quality = compute_l1_observations(missing, clocks, members)
    assert quality.loc[quality.date.eq(missing_day), 'breadth_bar_coverage'].iloc[0] < 1
    # At the following session the missing stock's return is not silently
    # treated as a legitimate one-day move; aggregate breadth stays blocked.
    following = clocks.date.iloc[46]
    assert pd.isna(obs.loc[obs.date.eq(following), 'breadth_up_share'].iloc[0])
