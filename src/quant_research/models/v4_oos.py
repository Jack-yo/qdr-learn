"""V4 rolling out-of-sample conditional-return research.

This independent engine does not grant trading eligibility. It requires a
caller-supplied exchange calendar, timestamped feature/label availability,
and verified source provenance before results can be promoted elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge


@dataclass(frozen=True)
class OOSProtocol:
    min_training_sessions: int = 252
    training_window_sessions: int = 1260
    calibration_sessions: int = 126
    gap_sessions: int = 5
    min_calibration_per_class: int = 8
    ridge_alpha: float = 1.0
    logistic_c: float = 1.0
    downside_threshold: float = -0.02
    seed: int = 42

    def __post_init__(self):
        if (self.min_training_sessions < 30 or self.training_window_sessions < self.min_training_sessions
                or self.calibration_sessions < 10 or self.gap_sessions < 5
                or self.min_calibration_per_class < 2 or self.ridge_alpha <= 0 or self.logistic_c <= 0
                or not -1 < self.downside_threshold < 0):
            raise ValueError('Invalid rolling OOS protocol')


REQUIRED = {'date', 'security_id', 'horizon', 'signal_time', 'feature_available_at',
            'exit_time', 'label_available_at', 'gross_return', 'excess_return'}


def _canonical(panel, features, sessions):
    if missing := REQUIRED - set(panel):
        raise ValueError(f'Missing research panel fields: {sorted(missing)}')
    fields = list(dict.fromkeys(x for columns in features.values() for x in columns))
    if not fields or any(not cols for cols in features.values()):
        raise ValueError('Each model variant needs named feature columns')
    if missing := set(fields) - set(panel):
        raise ValueError(f'Missing feature columns: {sorted(missing)}')
    sessions = pd.DatetimeIndex(sessions)
    if (sessions.tz is not None or sessions.has_duplicates or not sessions.is_monotonic_increasing
            or any(d != d.normalize() for d in sessions)):
        raise ValueError('Exchange session dates must be sorted, unique, and timezone-naive')
    rows = panel.copy()
    rows['date'] = pd.to_datetime(rows.date)
    if rows.date.dt.tz is not None or (~rows.date.isin(sessions)).any():
        raise ValueError('A signal date is outside the supplied exchange calendar')
    if rows.duplicated(['date', 'security_id', 'horizon']).any():
        raise ValueError('Duplicate signal-date/security/horizon')
    if not rows.horizon.isin([1, 3, 5]).all():
        raise ValueError('Only H1/H3/H5 predictions are supported')
    for col in ('signal_time', 'feature_available_at', 'exit_time', 'label_available_at'):
        rows[col] = pd.to_datetime(rows[col], utc=True)
    labeled = rows.gross_return.notna() | rows.excess_return.notna()
    if (rows.loc[labeled, ['gross_return','excess_return']].isna().any().any()
            or rows.loc[labeled, 'label_available_at'].isna().any()
            or (rows.loc[labeled, 'label_available_at'] < rows.loc[labeled, 'exit_time']).any()):
        raise ValueError('Outcome labels require both returns and real post-exit availability')
    if rows.signal_time.isna().any() or rows.feature_available_at.isna().any():
        raise ValueError('Every observation needs a timestamped feature and signal')
    if (rows.loc[labeled, 'signal_time'] >= rows.loc[labeled, 'exit_time']).any():
        raise ValueError('Signal time must precede outcome exit')
    if not np.isfinite(rows.loc[labeled, ['gross_return', 'excess_return']].to_numpy(dtype=float)).all():
        raise ValueError('Nonfinite labeled returns')
    values = rows[fields].apply(pd.to_numeric, errors='coerce')
    rows[fields] = values.replace([np.inf, -np.inf], np.nan)
    return rows, fields, sessions


def _regressor(x, y, x_predict, alpha):
    model = make_pipeline(StandardScaler(), Ridge(alpha=alpha))
    model.fit(x, y)
    return model.predict(x_predict)


def _calibrated_probability(model_train, calibration, test, columns, target, protocol):
    """Chronological fit -> embargo -> held-out Platt calibration -> prediction.

    Return NA, never a made-up calibrated value, for rare or single-class events.
    """
    if model_train.empty or calibration.empty:
        return np.full(len(test), np.nan), 'NO_CALIBRATION_WINDOW'
    a = target(model_train.gross_return.to_numpy(dtype=float))
    b = target(calibration.gross_return.to_numpy(dtype=float))
    if (min(np.bincount(a, minlength=2)) < protocol.min_calibration_per_class
            or min(np.bincount(b, minlength=2)) < protocol.min_calibration_per_class):
        return np.full(len(test), np.nan), 'INSUFFICIENT_CALIBRATION_EVENTS'
    base = make_pipeline(StandardScaler(), LogisticRegression(
        C=protocol.logistic_c, solver='liblinear', max_iter=500, random_state=protocol.seed))
    base.fit(model_train[columns], a)
    scores = base.decision_function(calibration[columns]).reshape(-1, 1)
    calibrator = LogisticRegression(C=100.0, solver='lbfgs', max_iter=500, random_state=protocol.seed)
    calibrator.fit(scores, b)
    predicted_scores = base.decision_function(test[columns]).reshape(-1, 1)
    return calibrator.predict_proba(predicted_scores)[:, 1], 'CALIBRATED_CHRONOLOGICAL_HOLDOUT'


def run_oos(panel: pd.DataFrame, feature_sets: dict[str, list[str]],
            exchange_sessions: pd.DatetimeIndex, protocol: OOSProtocol,
            evaluation_dates, *, input_snapshot_sha256: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Paired A/B/C/D-style OOS research; never emits an executable trade signal.

    Excluding the entire calendar embargo prevents horizon-overlap contamination.
    Calibration dates come AFTER fitting dates, with a second purge/embargo.
    No test outcomes are inspected during fit/calibration.
    """
    if not (isinstance(input_snapshot_sha256, str) and len(input_snapshot_sha256) == 64
            and all(c in '0123456789abcdef' for c in input_snapshot_sha256)):
        raise ValueError('A real input snapshot SHA256 must be supplied')
    rows, fields, sessions = _canonical(panel, feature_sets, exchange_sessions)
    requested = pd.DatetimeIndex(evaluation_dates)
    if requested.empty or requested.tz is not None or (~requested.isin(sessions)).any():
        raise ValueError('Requested OOS dates must be exchange sessions')
    # Compare variants only on the same complete-case population.
    rows = rows.loc[rows[fields].notna().all(axis=1)].copy()
    rows = rows.loc[rows.feature_available_at.le(rows.signal_time)].copy()
    protocol_hash = sha256(json.dumps(protocol.__dict__, sort_keys=True).encode()).hexdigest()
    outputs, folds = [], []
    indices = {date: i for i, date in enumerate(sessions)}
    for quarter, days in pd.Series(sorted(set(requested))).groupby(lambda i: pd.Timestamp(sorted(set(requested))[i]).to_period('Q')):
        fold_days = pd.DatetimeIndex(days.to_list())
        first = fold_days.min()
        loc = indices[first]
        # A five-session embargo precedes every independent forecast fold.
        last_train_index = loc - protocol.gap_sessions - 1
        if last_train_index < 0:
            continue
        allowed = sessions[max(0,last_train_index-protocol.training_window_sessions+1):last_train_index+1]
        candidates = rows.loc[rows.date.isin(allowed)
                              & rows.gross_return.notna()
                              & rows.label_available_at.le(rows.signal_time.map(lambda _: rows.loc[rows.date.eq(first),'signal_time'].min() if rows.date.eq(first).any() else pd.NaT))].copy()
        # The signal and label are never allowed to cross the test-fold fit time.
        fold_test = rows.loc[rows.date.isin(fold_days)].copy()
        if fold_test.empty:
            continue
        fit_time = fold_test.signal_time.min()
        candidates = rows.loc[rows.date.isin(allowed) & rows.gross_return.notna()
                              & rows.label_available_at.le(fit_time)
                              & rows.exit_time.lt(fit_time)].copy()
        training_days = sorted(candidates.date.unique())
        if len(training_days) < protocol.min_training_sessions:
            continue
        calibration_dates = training_days[-protocol.calibration_sessions:]
        first_cal_date = pd.Timestamp(calibration_dates[0])
        cal_loc = indices[first_cal_date]
        last_model_date = sessions[cal_loc-protocol.gap_sessions-1] if cal_loc > protocol.gap_sessions else None
        calibration = candidates.loc[candidates.date.isin(calibration_dates)].copy()
        early = candidates.loc[candidates.date.le(last_model_date)] if last_model_date is not None else candidates.iloc[:0]
        first_cal_time = calibration.signal_time.min() if not calibration.empty else pd.NaT
        early = early.loc[early.label_available_at.le(first_cal_time) & early.exit_time.lt(first_cal_time)]
        if early.date.nunique() < protocol.min_training_sessions - protocol.calibration_sessions - protocol.gap_sessions:
            continue
        for horizon in (1, 3, 5):
            past = candidates.loc[candidates.horizon.eq(horizon)]
            early_h = early.loc[early.horizon.eq(horizon)]
            cal_h = calibration.loc[calibration.horizon.eq(horizon)]
            test_h = fold_test.loc[fold_test.horizon.eq(horizon)]
            if past.empty or early_h.empty or test_h.empty:
                continue
            for variant, cols in feature_sets.items():
                test_x = test_h[cols].to_numpy(dtype=float)
                reg_gross = _regressor(past[cols], past.gross_return, test_x, protocol.ridge_alpha)
                reg_excess = _regressor(past[cols], past.excess_return, test_x, protocol.ridge_alpha)
                pu, up_status = _calibrated_probability(
                    early_h, cal_h, test_h, cols, lambda v: (v > 0).astype(int), protocol)
                pdn, dn_status = _calibrated_probability(
                    early_h, cal_h, test_h, cols,
                    lambda v: (v <= protocol.downside_threshold).astype(int), protocol)
                result = test_h[['date','security_id','horizon','signal_time','exit_time',
                                 'gross_return','excess_return']].copy()
                result['variant'] = variant
                result['predicted_gross_return'] = reg_gross
                result['predicted_excess_return'] = reg_excess
                result['p_up'], result['p_downside'] = pu, pdn
                result['up_calibration_status'], result['downside_calibration_status'] = up_status, dn_status
                result['baseline_up_rate'] = float((past.gross_return>0).mean())
                result['baseline_downside_rate'] = float((past.gross_return<=protocol.downside_threshold).mean())
                result['model_fit_time'] = fit_time
                result['model_version'] = 'v4-' + protocol_hash[:12] + '-' + variant
                result['source_snapshot_sha256'] = input_snapshot_sha256
                result['research_only'], result['decision_eligible'] = True, False
                outputs.append(result)
                folds.append({'quarter':str(quarter),'horizon':horizon,'variant':variant,
                              'fit_time':fit_time,'train_sessions':past.date.nunique(),
                              'model_fit_last_label_available':early_h.label_available_at.max(),
                              'calibration_first_signal':first_cal_time,
                              'calibration_sessions':cal_h.date.nunique(),
                              'first_test':test_h.date.min(),'last_test':test_h.date.max(),
                              'input_snapshot_sha256':input_snapshot_sha256})
    return (pd.concat(outputs, ignore_index=True) if outputs else pd.DataFrame(),
            pd.DataFrame(folds))


def score_oos(predictions: pd.DataFrame, *, downside_threshold: float = -0.02) -> pd.DataFrame:
    """Explicit benchmark comparisons; no promotion/eligibility decisions."""
    if predictions.empty:
        return pd.DataFrame()
    required = {'variant','horizon','date','security_id','gross_return','excess_return',
                'predicted_gross_return','predicted_excess_return','p_up','p_downside',
                'baseline_up_rate','baseline_downside_rate'}
    if required - set(predictions):
        raise ValueError('Missing prediction score fields')
    rows = []
    for (variant, horizon), group in predictions.groupby(['variant','horizon']):
        truth = group.dropna(subset=['gross_return','excess_return'])
        if truth.empty:
            continue
        record = {'variant':variant,'horizon':int(horizon),
                  'rows':len(truth),'sessions':truth.date.nunique(),
                  'gross_mse':float(mean_squared_error(truth.gross_return,truth.predicted_gross_return)),
                  'excess_mse':float(mean_squared_error(truth.excess_return,truth.predicted_excess_return)),
                  'brier_up':None,'baseline_brier_up':None,
                  'brier_downside':None,'baseline_brier_downside':None}
        for name, label, prob, naive in [
            ('up', truth.gross_return.gt(0), 'p_up', 'baseline_up_rate'),
            ('downside', truth.gross_return.le(downside_threshold), 'p_downside', 'baseline_downside_rate')]:
            scored = truth.dropna(subset=[prob,naive])
            if not scored.empty:
                y = label.loc[scored.index].astype(int)
                record['brier_'+name] = float(brier_score_loss(y,scored[prob]))
                record['baseline_brier_'+name] = float(brier_score_loss(y,scored[naive]))
        rows.append(record)
    return pd.DataFrame(rows)
