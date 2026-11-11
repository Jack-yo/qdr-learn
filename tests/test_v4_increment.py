"""OOS significance tests cover paired sample alignment, not profitability."""
import numpy as np
import pandas as pd
import pytest

from quant_research.research.v4_increment import paired_oos_increment


def _sample(sessions=85, securities=6):
    dates=pd.bdate_range('2024-03-01',periods=sessions)
    rows=[]
    for d,day in enumerate(dates):
        for security in range(securities):
            outcome=.02 if (d+security)%2==0 else -.02
            for variant in ('A','D'):
                forecast=.005 if variant=='A' else outcome
                p=.5 if variant=='A' else (.8 if outcome>0 else .2)
                rows.append({'date':day,'security_id':f'ID{security}','horizon':3,
                             'variant':variant,'gross_return':outcome,
                             'p_up':p,'predicted_gross_return':forecast})
    return pd.DataFrame(rows)


def test_paired_positive_gain_and_block_bootstrap():
    report=paired_oos_increment(_sample(),repetitions=200)
    row=report.iloc[0]
    assert row.status=='PAIRED_OOS_ESTIMATED'
    assert row.sessions==85 and row.rows==85*6
    assert row.brier_gain==pytest.approx(.21,abs=1e-8)
    assert row.brier_gain_ci95[0]>0
    assert row.gross_mse_gain>0
    assert row.research_only


def test_missing_samples_do_not_produce_false_significance():
    report=paired_oos_increment(_sample(sessions=30),min_sessions=60,repetitions=200)
    row=report.iloc[0]
    assert row.status=='INSUFFICIENT_OOS_SESSIONS'
    assert row.brier_gain is None and row.gross_mse_gain_ci95 is None


def test_identical_outcomes_and_unique_keys_required():
    frame=_sample()
    bad=frame.copy()
    bad.loc[bad.variant.eq('D'),'gross_return']=.99
    with pytest.raises(ValueError,match='outcomes differ'):
        paired_oos_increment(bad,repetitions=200)
    with pytest.raises(ValueError,match='Duplicate'):
        paired_oos_increment(pd.concat([frame,frame.iloc[:1]]))
