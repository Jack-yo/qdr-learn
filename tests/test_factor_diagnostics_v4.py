"""Mathematical unit tests only; no synthetic market results are published."""
import pandas as pd
import pytest

from quant_research.research.factor_diagnostics import pairwise_daily_rank_correlations


def _panel():
    return pd.DataFrame([{'date': d, 'security_id': i, 'a': float(i),
                          'b': float(9-i), 'c': float((i*7+d)%11)}
                         for d in range(10) for i in range(10)])


def test_detects_redundant_factors_by_session():
    out = pairwise_daily_rank_correlations(_panel(), ['a', 'b', 'c'])
    ab = next(row for row in out if row['factor_a'] == 'a' and row['factor_b'] == 'b')
    assert ab['valid_sessions'] == 10 and ab['median_daily_spearman'] == pytest.approx(-1)
    assert ab['redundancy_warning'] and ab['research_only']


def test_insufficient_cross_sections_have_no_claimed_correlation():
    out = pairwise_daily_rank_correlations(_panel().iloc[:2], ['a', 'b'], min_securities=5)
    assert out[0]['valid_sessions'] == 0 and out[0]['median_daily_spearman'] is None
    assert not out[0]['redundancy_warning']


def test_duplicate_security_dates_rejected():
    frame = _panel()
    frame = pd.concat([frame, frame.iloc[:1]])
    with pytest.raises(ValueError, match='Duplicate'):
        pairwise_daily_rank_correlations(frame, ['a', 'b'])
