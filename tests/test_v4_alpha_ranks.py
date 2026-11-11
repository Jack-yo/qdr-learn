"""Alpha factor ranking tests use numeric fixtures only."""
import pandas as pd
import pytest

from quant_research.research.v4_alpha_ranks import evaluate_alpha_ranking


def _predictions(nsecurities=30,nsessions=80):
    days=pd.bdate_range('2024-02-01',periods=nsessions)
    return pd.DataFrame([
        {'date':day,'security_id':f'S{sid}','variant':'A','horizon':3,
         'predicted_excess_return':float(sid)/nsecurities,
         'excess_return':float(sid)/nsecurities - .5}
        for day in days for sid in range(nsecurities)
    ])


def test_rank_ic_and_group_spread_are_descriptive():
    report,daily=evaluate_alpha_ranking(_predictions())
    assert len(report)==1 and len(daily)==80
    row=report.iloc[0]
    assert row.status=='OOS_CROSS_SECTION_STUDIED'
    assert row.rank_ic_mean==pytest.approx(1)
    assert row.mean_top_bottom_spread>0
    assert row.not_a_costed_portfolio_backtest and row.research_only


def test_too_few_securities_never_generates_pseudo_ic():
    report,daily=evaluate_alpha_ranking(_predictions(nsecurities=8))
    assert report.empty and daily.empty


def test_duplicate_future_returns_rejected():
    rows=_predictions()
    with pytest.raises(ValueError,match='Duplicate'):
        evaluate_alpha_ranking(pd.concat([rows,rows.iloc[:1]]))
