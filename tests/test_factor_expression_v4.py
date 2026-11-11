"""V4 factor DSL safety/causality tests; synthetic data only for math unit tests."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quant_research.features.expression import compile_expression


def _context():
    idx = pd.bdate_range('2025-01-02', periods=30)
    close = pd.DataFrame({'A': np.arange(10, 40, dtype=float),
                          'B': np.arange(25, 55, dtype=float)}, index=idx)
    return SimpleNamespace(close=close,
                           panels={'close': close, 'open': close-1, 'high': close+1,
                                   'low': close-2, 'volume': close*100},
                           returns=close.pct_change(fill_method=None))


def test_custom_factor_reversal_and_window():
    c = _context()
    factor = compile_expression('-ret(close,5)')
    assert factor.lookback == 5
    actual = factor.compute(c)
    pd.testing.assert_frame_equal(actual, -(c.close/c.close.shift(5)-1))
    assert actual.iloc[:5].isna().all().all()


def test_formula_prefix_causality_and_alignment():
    c = _context()
    factor = compile_expression('0.4 * rank(ret(close,3)) - 0.6 * zscore(mean(volume,5))')
    values = factor.compute(c)
    for n in (12, 25):
        prefix = SimpleNamespace(close=c.close.iloc[:n],
            panels={k:v.iloc[:n] for k,v in c.panels.items()},
            returns=c.returns.iloc[:n])
        pd.testing.assert_frame_equal(values.iloc[:n], factor.compute(prefix))
    assert values.index.equals(c.close.index) and values.columns.equals(c.close.columns)


@pytest.mark.parametrize('formula', [
    'close.shift(-1)', '__import__("os").system("whoami")', 'ret(close,-1)',
    'ret(close,0)', 'lag(close, False)', 'lag(mean(close,200),100)',
    'close[0]', '[x for x in close]', 'lambda x:x',
    'sum(x for x in close)', '1+2', 'std(close,1)', 'rank(7)',
])
def test_disallowed_or_noncausal_formulas_fail(formula):
    with pytest.raises(ValueError):
        compile_expression(formula)


def test_zero_division_produces_missing_values():
    c = _context()
    assert compile_expression('close / (close - close)').compute(c).isna().all().all()


def test_missing_data_not_forward_filled():
    c = _context()
    c.panels['close'] = c.close.copy()
    c.panels['close'].iloc[-2,0] = np.nan
    out = compile_expression('mean(close,3)').compute(c)
    assert pd.isna(out.iloc[-1,0]) and pd.notna(out.iloc[-1,1])
