"""V4 four-layer conditional-Alpha research composition.

A/B/C/D is a paired experiment over identical dated observations. No model
is promoted from a positive metric alone: source/identity certification,
multiple-testing controls and continuous forward evidence are separate gates.
"""
from __future__ import annotations

import pandas as pd

from quant_research.models.v4_oos import OOSProtocol, run_oos, score_oos
from quant_research.models.v4_panel import prepare_v4_alpha_panel
from quant_research.research.v4_increment import paired_oos_increment
from quant_research.research.v4_alpha_ranks import evaluate_alpha_ranking


def study_conditional_alpha(*, factors: pd.DataFrame, labels: pd.DataFrame,
                            market_style: pd.DataFrame, trading_clock,
                            exchange_sessions: pd.DatetimeIndex,
                            alpha_factor_names: list[str], evaluation_dates,
                            source_snapshot_sha256: str,
                            protocol: OOSProtocol = OOSProtocol()) -> dict:
    """Strict-input model study. Never calls a broker or writes simulated fills."""
    panel, contract = prepare_v4_alpha_panel(
        factors, labels, market_style, trading_clock,
        expected_factor_names=alpha_factor_names)
    market = sorted(c for c in contract['market_style_columns'] if c.startswith('market_')
                    and pd.api.types.is_numeric_dtype(panel[c]))
    style = sorted(c for c in contract['market_style_columns'] if c.startswith('style_')
                   and pd.api.types.is_numeric_dtype(panel[c]))
    if not market or not style:
        raise ValueError('Comparable numeric market AND style features required')
    for name in alpha_factor_names:
        if name not in panel or not pd.api.types.is_numeric_dtype(panel[name]):
            raise ValueError(f'Invalid numeric Alpha feature: {name}')
    groups = {'A':list(alpha_factor_names),
              'B':list(alpha_factor_names)+market,
              'C':list(alpha_factor_names)+style,
              'D':list(alpha_factor_names)+market+style}
    predictions, folds = run_oos(
        panel, groups, exchange_sessions, protocol, evaluation_dates,
        input_snapshot_sha256=source_snapshot_sha256)
    report = score_oos(predictions)
    increments = (
        paired_oos_increment(predictions,baseline_variant='A',challenger_variant='D',
                             min_sessions=60,block_sessions=5,repetitions=500,
                             seed=protocol.seed)
        if not predictions.empty else pd.DataFrame()
    )
    rank_summary, rank_daily = evaluate_alpha_ranking(predictions) if not predictions.empty else (pd.DataFrame(),pd.DataFrame())
    return {'status':'RESEARCH_ONLY_NOT_ADMITTED_TO_PAPER',
            'model_variants':groups,'panel_contract':contract,
            'predictions':predictions,'folds':folds,'metrics':report,
            'alpha_ranking':rank_summary,'daily_alpha_rank_ic':rank_daily,
            'increment_vs_alpha_only':increments,
            'historical_decision_eligible':False,
            'real_orders_enabled':False,
            'requires':['PIT_HISTORY_SOURCE_ATTESTATION','INDEPENDENT_RESEARCH_ACCEPTANCE',
                        'TRADING_COST_BACKTEST','FORWARD_SIMULATION_EVIDENCE']}
