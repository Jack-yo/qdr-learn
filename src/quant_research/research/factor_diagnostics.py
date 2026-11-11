"""V4 multifactor redundancy diagnostics on comparable daily cross-sections.

Each date is a correlated cross-sectional observation. The result is descriptive
research only, not evidence of a tradable or calibrated alpha forecast.
"""
from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd


def pairwise_daily_rank_correlations(
    frame: pd.DataFrame, factor_columns: list[str], *,
    min_securities: int = 5, high_correlation: float = 0.85,
) -> list[dict]:
    """Median of per-date Spearman correlations on complete common securities."""
    if len(factor_columns) < 2 or len(set(factor_columns)) != len(factor_columns):
        raise ValueError('Specify at least two distinct factors')
    if not 2 <= min_securities <= 100000:
        raise ValueError('Invalid minimum cross-section')
    required = {'date', 'security_id', *factor_columns}
    if required - set(frame):
        raise ValueError('Factor cross-section is missing required columns')
    if frame.duplicated(['date', 'security_id']).any():
        raise ValueError('Duplicate date/security observations')
    if not 0 < high_correlation <= 1:
        raise ValueError('Invalid redundancy threshold')
    out = []
    by_date = list(frame.groupby('date', sort=True))
    for a, b in combinations(factor_columns, 2):
        daily = []
        for _, rows in by_date:
            valid = rows[[a, b]].apply(pd.to_numeric, errors='coerce').replace([np.inf, -np.inf], np.nan).dropna()
            if len(valid) < min_securities or valid[a].nunique() < 2 or valid[b].nunique() < 2:
                continue
            value = valid[a].rank().corr(valid[b].rank())
            if pd.notna(value):
                daily.append(float(value))
        median = float(np.median(daily)) if daily else None
        out.append({'factor_a': a, 'factor_b': b,
                    'valid_sessions': len(daily),
                    'median_daily_spearman': median,
                    'redundancy_warning': bool(median is not None and abs(median) >= high_correlation),
                    'research_only': True})
    return out
