"""V4 paired OOS incremental-value evaluation with session-block bootstrap.

Comparing models on identical signal dates/security IDs avoids reporting a
spurious gain from using different test populations. This is research evidence,
not a proof of alpha profitability or permission to send orders.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


_KEYS = ['date','security_id','horizon']


def _block_ci(daily_values: np.ndarray, *, block_sessions: int = 5,
              repetitions: int = 1000, seed: int = 42) -> tuple[float,float]:
    """Circular-block percentile interval for the mean of session-level deltas."""
    n = len(daily_values)
    if n < max(20, block_sessions * 3) or repetitions < 100:
        raise ValueError('Insufficient sessions or bootstrap repetitions')
    rng = np.random.default_rng(seed)
    block_sessions = min(block_sessions, n)
    outputs = np.empty(repetitions)
    for i in range(repetitions):
        starts = rng.integers(0,n,size=(n + block_sessions - 1)//block_sessions)
        sample = np.concatenate([(s + np.arange(block_sessions)) % n for s in starts])[:n]
        outputs[i] = daily_values[sample].mean()
    return tuple(float(v) for v in np.quantile(outputs,[.025,.975]))


def paired_oos_increment(predictions: pd.DataFrame, *,
                         baseline_variant: str = 'A', challenger_variant: str = 'D',
                         min_sessions: int = 60, block_sessions: int = 5,
                         repetitions: int = 1000, seed: int = 42) -> pd.DataFrame:
    """Return paired daily deltas: positive => challenger has less loss.

    Do not use historical model selection and this report as an independent
    final-test claim. Each trial should be counted in a research registry.
    """
    required = {*_KEYS, 'variant', 'gross_return', 'p_up',
                'predicted_gross_return'}
    if required - set(predictions):
        raise ValueError(f'Missing prediction evidence: {sorted(required - set(predictions))}')
    if predictions.duplicated(_KEYS + ['variant']).any():
        raise ValueError('Duplicate prediction keys invalidate paired comparison')
    if min_sessions < 20:
        raise ValueError('At least 20 independently dated sessions are required')
    left = predictions.loc[predictions.variant.eq(baseline_variant),
        _KEYS + ['gross_return','p_up','predicted_gross_return']]
    right = predictions.loc[predictions.variant.eq(challenger_variant),
        _KEYS + ['gross_return','p_up','predicted_gross_return']]
    aligned = left.merge(right,on=_KEYS,how='inner',suffixes=('_base','_new'),validate='one_to_one')
    if aligned.empty:
        raise ValueError('No matching OOS dates/securities')
    if not np.allclose(aligned.gross_return_base,aligned.gross_return_new,equal_nan=True):
        raise ValueError('Paired model outcomes differ')
    records=[]
    for horizon, sample in aligned.groupby('horizon'):
        actual = sample.gross_return_base
        mask = actual.notna() & sample[['p_up_base','p_up_new',
                                        'predicted_gross_return_base',
                                        'predicted_gross_return_new']].notna().all(axis=1)
        frame = sample.loc[mask].copy()
        if frame.empty:
            continue
        if not frame[['p_up_base','p_up_new']].apply(lambda s:s.between(0,1)).all().all():
            raise ValueError('Calibrated probabilities must be 0–1')
        up = frame.gross_return_base.gt(0).astype(float)
        frame['brier_gain'] = (frame.p_up_base-up)**2 - (frame.p_up_new-up)**2
        frame['gross_mse_gain'] = (frame.predicted_gross_return_base-frame.gross_return_base)**2 - (
            frame.predicted_gross_return_new-frame.gross_return_base)**2
        daily = frame.groupby('date',sort=True)[['brier_gain','gross_mse_gain']].mean()
        if len(daily) < min_sessions:
            records.append({'horizon':int(horizon),'status':'INSUFFICIENT_OOS_SESSIONS',
                            'sessions':len(daily),'rows':len(frame),'baseline_variant':baseline_variant,
                            'challenger_variant':challenger_variant,
                            'brier_gain':None,'brier_gain_ci95':None,
                            'gross_mse_gain':None,'gross_mse_gain_ci95':None,
                            'research_only':True})
            continue
        brier_ci = _block_ci(daily.brier_gain.to_numpy(),block_sessions=block_sessions,
                             repetitions=repetitions,seed=seed)
        mse_ci = _block_ci(daily.gross_mse_gain.to_numpy(),block_sessions=block_sessions,
                           repetitions=repetitions,seed=seed+1)
        records.append({'horizon':int(horizon),'status':'PAIRED_OOS_ESTIMATED',
                        'sessions':len(daily),'rows':len(frame),
                        'baseline_variant':baseline_variant,'challenger_variant':challenger_variant,
                        'brier_gain':float(daily.brier_gain.mean()),'brier_gain_ci95':brier_ci,
                        'gross_mse_gain':float(daily.gross_mse_gain.mean()),'gross_mse_gain_ci95':mse_ci,
                        'probability_gain_ci_excludes_zero':brier_ci[0]>0,
                        'gross_mse_gain_ci_excludes_zero':mse_ci[0]>0,
                        'research_only':True,
                        'note':'Unadjusted 95% block-bootstrap intervals; multiple testing and strategy selection require separate controls'})
    return pd.DataFrame(records)
