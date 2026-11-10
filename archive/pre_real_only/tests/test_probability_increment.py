import pandas as pd
import pytest

from quant_research.research.increment import probability_increment


def sample():
    rows=[]
    for day in pd.date_range("2023-01-01",periods=60):
        for variant,p in [("A",0.5),("B",0.75)]:
            rows.append(dict(date=day,security_id="s",horizon=3,variant=variant,p_up=p,naive_p_up=.5,actual_return=.01))
    return pd.DataFrame(rows)


def test_paired_improvement_formula_and_block_bootstrap():
    result=probability_increment(sample())
    b=result.loc[result.variant.eq("B") & result.baseline.eq("alpha_only_A")].iloc[0]
    assert b.matched_rows==60 and b.matched_dates==60
    assert b.mean_brier_improvement==pytest.approx(.1875)
    assert b.ci95_low==pytest.approx(.1875)
    assert b.ci95_high==pytest.approx(.1875)
    a=result.loc[result.variant.eq("A")]
    assert a.mean_brier_improvement.eq(0).all()
    pd.testing.assert_frame_equal(result,probability_increment(sample()))


def test_pairing_rejects_duplicates_different_targets_and_invalid_probability():
    data=sample()
    with pytest.raises(ValueError,match="Duplicate"):
        probability_increment(pd.concat([data,data.iloc[[0]]]))
    data.loc[data.variant.eq("B"),"actual_return"]=-.01
    with pytest.raises(ValueError,match="outcomes"):
        probability_increment(data)
    data=sample()
    data.loc[0,"p_up"]=1.1
    with pytest.raises(ValueError,match="probabilities"):
        probability_increment(data)


def test_market_scores_missing_outcomes_are_excluded_and_small_sample_ci_null():
    data=sample().loc[lambda d:d.variant.eq("A")].drop(columns=["variant","security_id"]).iloc[:5].copy()
    data.loc[data.index[0],"actual_return"]=float("nan")
    result=probability_increment(data)
    assert result.iloc[0].matched_dates==4
    assert pd.isna(result.iloc[0].ci95_low)
