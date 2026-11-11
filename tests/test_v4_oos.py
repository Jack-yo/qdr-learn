"""V4 research engine tests use deterministic numeric fixtures, never market claims."""
from datetime import timedelta
import numpy as np
import pandas as pd
import pytest

from quant_research.models.v4_oos import OOSProtocol, run_oos, score_oos


def _sample(n=135):
    sessions = pd.bdate_range('2024-11-01', periods=n)
    rows = []
    for day_index, day in enumerate(sessions):
        for horizon in (1, 3, 5):
            for sid in range(7):
                signal = pd.Timestamp(day).tz_localize('UTC') + pd.Timedelta(hours=23)
                exit_time = signal + pd.Timedelta(days=horizon + 2)
                gross = [0.04,-0.025,0.008,-0.005][(day_index+sid)%4]
                rows.append({'date':day, 'security_id':f'S{sid}', 'horizon':horizon,
                             'signal_time':signal, 'feature_available_at':signal-pd.Timedelta(minutes=10),
                             'exit_time':exit_time, 'label_available_at':exit_time+pd.Timedelta(hours=1),
                             'gross_return':gross, 'excess_return':gross-0.002,
                             'alpha':float((sid+day_index)%11)/11,
                             'market':float(day_index%19)/19,
                             'style':float((sid*3+day_index)%13)/13})
    return pd.DataFrame(rows), sessions


def _run(frame, sessions):
    spec=OOSProtocol(min_training_sessions=35,training_window_sessions=100,
                     calibration_sessions=16,gap_sessions=5,min_calibration_per_class=3)
    return run_oos(frame, {'A':['alpha'],'B':['alpha','market'],
                           'C':['alpha','style'],'D':['alpha','market','style']},
                   sessions, spec, sessions[-20:], input_snapshot_sha256='a'*64)


def test_chronological_oos_and_paired_variants():
    panel, sessions = _sample()
    predictions, folds = _run(panel, sessions)
    assert not predictions.empty and not folds.empty
    assert set(predictions.variant)=={'A','B','C','D'}
    assert not predictions.decision_eligible.any() and predictions.research_only.all()
    assert set(predictions.horizon)=={1,3,5}
    assert folds.model_fit_last_label_available.le(folds.calibration_first_signal).all()
    assert folds.first_test.gt(folds.model_fit_last_label_available).all()
    assert predictions.groupby(['variant','horizon']).size().nunique()==1
    report=score_oos(predictions)
    assert len(report)==12 and (report.rows>0).all()


def test_future_outcomes_never_change_frozen_oos_predictions():
    panel,sessions=_sample()
    reference,_=_run(panel,sessions)
    changed=panel.copy()
    mask=changed.date.isin(sessions[-20:])
    changed.loc[mask,'gross_return']=0.8
    changed.loc[mask,'excess_return']=0.75
    other,_=_run(changed,sessions)
    cols=['variant','horizon','date','security_id','predicted_gross_return',
          'predicted_excess_return','p_up','p_downside']
    pd.testing.assert_frame_equal(reference[cols],other[cols])


def test_future_features_and_invalid_contract_rejected_or_filtered():
    panel,sessions=_sample()
    panel.loc[panel.date.eq(sessions[-1]),'feature_available_at']=pd.Timestamp('2030-01-01',tz='UTC')
    predictions,_=_run(panel,sessions)
    assert not predictions.date.eq(sessions[-1]).any()
    duplicate=pd.concat([panel,panel.iloc[:1]],ignore_index=True)
    with pytest.raises(ValueError,match='Duplicate'):
        _run(duplicate,sessions)


def test_missing_snapshot_digest_and_pre_exit_label_fail():
    frame,sessions=_sample()
    spec=OOSProtocol(min_training_sessions=35,calibration_sessions=16)
    with pytest.raises(ValueError,match='SHA256'):
        run_oos(frame,{'A':['alpha']},sessions,spec,sessions[-20:],input_snapshot_sha256='missing')
    frame.loc[0,'label_available_at']=frame.loc[0,'signal_time']
    with pytest.raises(ValueError,match='post-exit'):
        _run(frame,sessions)


def test_score_does_not_manufacture_future_results():
    frame,sessions=_sample()
    frame.loc[frame.date.isin(sessions[-20:]),['gross_return','excess_return']]=np.nan
    frame.loc[frame.date.isin(sessions[-20:]),'label_available_at']=pd.NaT
    predictions,_=_run(frame,sessions)
    assert predictions[['gross_return','excess_return']].isna().all().all()
    assert score_oos(predictions).empty
