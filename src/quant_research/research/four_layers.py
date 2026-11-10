"""G9 four-layer retrospective ETF research with immutable factor evidence.

Market, style, alpha and risk layers are evaluated on one authenticated Yahoo
current-vintage snapshot. This is *never* a PIT model, strategy backtest, or
forecast. The predeclared gates measure conditional IC and sample coverage;
there is no optimized threshold, cashflow, fill or fabricated trading signal.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
import pandas as pd

from quant_research.policy import PolicyError
from quant_research.research.statistics import circular_block_ci, daily_rank_ic


GATES = (
    ('ALPHA_ONLY', ()),
    ('MARKET_ALPHA', ('market',)),
    ('STYLE_ALPHA', ('style',)),
    ('MARKET_STYLE_ALPHA', ('market', 'style')),
    ('MARKET_STYLE_ALPHA_RISK', ('market', 'style', 'risk')),
)


def _price_regimes(prices):
    """Only past and contemporaneous daily closes. No bfill or future windows."""
    needed = {'date', 'security_id', 'symbol', 'close', 'source', 'adjustment_basis'}
    if needed - set(prices):
        raise PolicyError('G9_PRICE_FIELDS_MISSING', 'Verified prices lack required fields', sorted(needed - set(prices)))
    if prices.duplicated(['date', 'security_id']).any():
        raise PolicyError('G9_DUPLICATE_BARS', 'A security has multiple bars at the same session')
    if set(prices.source) != {'YAHOO'} or set(prices.adjustment_basis) != {'yahoo_split_adjusted'}:
        raise PolicyError('G9_PRICE_SCOPE_INVALID', 'G9 accepts only the reviewed Yahoo current-vintage research prices')
    needed_symbols = {'SPY', 'IWD', 'IWF'}
    if not needed_symbols <= set(prices.symbol):
        raise PolicyError('G9_PROXY_MISSING', 'Market and value/growth style proxies must be present', sorted(needed_symbols - set(prices.symbol)))
    subset = prices.loc[prices.symbol.isin(needed_symbols)]
    if subset.duplicated(['date', 'symbol']).any():
        raise PolicyError('G9_PROXY_AMBIGUOUS', 'Duplicate provider symbol records')
    daily = subset.pivot(index='date', columns='symbol', values='close').sort_index()
    if (daily <= 0).any().any():
        raise PolicyError('G9_PRICE_INVALID', 'Proxy closes must be positive')
    r = daily.pct_change(fill_method=None)
    spy_ret20 = daily['SPY'].div(daily['SPY'].shift(20)).sub(1)
    style20 = daily['IWD'].div(daily['IWD'].shift(20)).sub(
        daily['IWF'].div(daily['IWF'].shift(20)))
    vol20 = r['SPY'].rolling(20, min_periods=20).std()
    # Historical risk threshold uses only earlier volatility observations.
    past_risk_threshold = vol20.shift(1).rolling(126, min_periods=126).quantile(0.60)
    result = pd.DataFrame({
        'date': pd.to_datetime(daily.index),
        'market': spy_ret20.ge(0).to_numpy(),
        'style': style20.ge(0).to_numpy(),
        'risk': vol20.le(past_risk_threshold).to_numpy(),
    })
    # Comparisons to NaN would otherwise turn unknown history into False.
    result.loc[spy_ret20.isna().to_numpy(), 'market'] = pd.NA
    result.loc[style20.isna().to_numpy(), 'style'] = pd.NA
    result.loc[(vol20.isna() | past_risk_threshold.isna()).to_numpy(), 'risk'] = pd.NA
    return result


def _score_components(components, allocations):
    joined = None
    names = []
    for allocation, frame in zip(allocations, components):
        identifier = allocation['factor_experiment_id']
        needed = {'date','security_id','value','research_mode','decision_eligible'}
        if needed - set(frame):
            raise PolicyError('G9_FACTOR_FIELDS_MISSING', 'Required factor columns missing')
        if (frame.empty or frame.duplicated(['date','security_id']).any()
                or not frame.research_mode.eq('retrospective').all()
                or frame.decision_eligible.fillna(False).any()):
            raise PolicyError('G9_FACTOR_SCOPE_INVALID', 'Factor rows must be unique and strictly retrospective')
        part = frame[['date','security_id','value']].copy()
        part['date'] = pd.to_datetime(part.date)
        part[identifier] = pd.to_numeric(part.pop('value'), errors='coerce').replace([np.inf,-np.inf],np.nan)
        joined = part if joined is None else joined.merge(part,on=['date','security_id'],how='inner',validate='one_to_one')
        names.append(identifier)
    if joined is None:
        raise PolicyError('G9_FACTORS_EMPTY', 'No verifiable factors')
    joined.dropna(subset=names, inplace=True)
    if joined.empty:
        raise PolicyError('G9_NO_COMMON_FACTORS', 'No complete observations for all components')
    for identifier in names:
        joined[identifier] = joined.groupby('date')[identifier].rank(method='average',pct=True)
    joined['score'] = sum(joined[a['factor_experiment_id']] * a['weight'] for a in allocations)
    return joined[['date','security_id','score']]


def _evaluate(data, min_count):
    frame = daily_rank_ic(data, x='score',y='target', min_count=min_count)
    series = frame.rank_ic.dropna()
    if series.empty:
        return {'days':0,'rows':0,'rank_ic_mean':None,'rank_ic_ci95_low':None,'rank_ic_ci95_high':None}
    low, high = circular_block_ci(series.to_numpy(),block_length=20,replicates=500,seed=42)
    return {'days':int(series.size), 'rows':int(data[['score','target']].dropna().shape[0]),
            'rank_ic_mean':float(series.mean()),'rank_ic_ci95_low':low,'rank_ic_ci95_high':high}


def _ablation_table(combined, regimes, min_count):
    merged = combined.merge(regimes,on='date',how='inner',validate='many_to_one')
    if merged.empty:
        raise PolicyError('G9_NO_OVERLAP', 'No joint dates across actual factor values and proxy bars')
    total_dates = int(merged.date.nunique())
    records = []
    for label, gates in GATES:
        mask = pd.Series(True,index=merged.index)
        for gate in gates:
            mask &= merged[gate].fillna(False).astype(bool)
        subset = merged.loc[mask].copy()
        stats = _evaluate(subset, min_count)
        records.append({'layer_configuration':label, 'rule_gates':list(gates),
                        'observed_validation_days':int(subset.date.nunique()),
                        'total_validation_days':total_dates,
                        'covered_fraction':float(subset.date.nunique()/total_dates),
                        **stats})
    return records


def evaluate_four_layers(root, strategy_id):
    """Compute four-layer *descriptive* ablation with real frozen experiment bytes."""
    from pathlib import Path
    root = Path(root).resolve()
    if not (root/'data/managed/strategies/registry.sqlite3').is_file():
        raise PolicyError('STRATEGY_NOT_FOUND', 'No frozen real strategy versions are available')
    from quant_research.research.strategy import StrategyRegistry
    from quant_research.research.composite import _verified_parquet
    from quant_research.workflow.factor_lab import result as checked_result
    from quant_research.data.bundle import load_real_bundle
    root = Path(root).resolve()
    strategy = StrategyRegistry(root).validate(strategy_id)['strategy']
    if strategy['status'] != 'FROZEN':
        raise PolicyError('G9_STRATEGY_NOT_FROZEN', 'Freeze the strategy version before evaluating the layers')
    config = strategy['config']
    mix = config.get('factor_mix')
    if not mix or len(mix.get('allocations', [])) < 2:
        raise PolicyError('G9_MULTIFACTOR_REQUIRED', 'Four-layer study requires an immutable multi-factor strategy')
    if mix['research_scope']['source'] != 'YAHOO':
        raise PolicyError('G9_SOURCE_UNSUPPORTED', 'Only Yahoo retrospective research has a defined four-layer protocol')
    allocations = mix['allocations']
    components = [_verified_parquet(root,item['factor_experiment_id'],'features.parquet') for item in allocations]
    scores = _score_components(components,allocations)
    first = allocations[0]['factor_experiment_id']
    experiment = checked_result(root,first)['result']
    manifest_cutoff = datetime.fromisoformat(experiment['data_cutoff_utc'])
    if manifest_cutoff > datetime.now(timezone.utc):
        raise PolicyError('G9_FUTURE_SOURCE_CUTOFF', 'Original research snapshot claims a future source cutoff')
    bundle = load_real_bundle(root/'data/research.duckdb','yahoo',asof='2024-12-31',
                             cutoff=manifest_cutoff,start='2017-01-01',
                             symbols=experiment['symbols'],raw_root=root/'data/raw')
    bundle.require('exploratory_price_factors')
    if bundle.metadata['snapshot_sha256'] != mix['research_scope']['snapshot_sha256']:
        raise PolicyError('G9_SOURCE_SNAPSHOT_CHANGED', 'Research proxy prices differ from frozen factor experiments')
    regimes = _price_regimes(bundle.prices)
    labels = _verified_parquet(root,first,'labels.parquet')
    required = {'date','security_id','horizon','exit_date','proxy_forward_return'}
    if required - set(labels):
        raise PolicyError('G9_LABEL_FIELDS_MISSING','Verified labels lack required columns')
    if labels.duplicated(['date','security_id','horizon']).any():
        raise PolicyError('G9_LABEL_DUPLICATE','A horizon has duplicate label keys')
    horizon = config['strategy']['horizon']
    labels=labels.loc[labels.horizon.eq(horizon),['date','security_id','exit_date','proxy_forward_return']].copy()
    labels['date']=pd.to_datetime(labels.date)
    protocol=config['protocol']
    begin=pd.Timestamp(protocol['train_end'])+pd.Timedelta(days=1)
    end=pd.Timestamp(protocol['validation_end'])
    valid=scores.loc[scores.date.between(begin,end)].copy()
    labels=labels.loc[labels.date.between(begin,end) & (pd.to_datetime(labels.exit_date)<=end)]
    valid=valid.merge(labels[['date','security_id','proxy_forward_return']],on=['date','security_id'],how='left',validate='one_to_one')
    valid['target']=pd.to_numeric(valid.proxy_forward_return,errors='coerce').replace([np.inf,-np.inf],np.nan)
    min_count=int(experiment['experiment']['min_cross_section'])
    comparison=_ablation_table(valid,regimes,min_count)
    if not comparison[0]['days']:
        raise PolicyError('G9_NO_EVALUABLE_VALIDATION','No real paired validation labels pass minimum cross-section')
    return {
        'status':'RETROSPECTIVE_FOUR_LAYER_ABLATION_ONLY',
        'asof_date_et':end.date().isoformat(),
        'strategy_version_id':strategy['id'],'strategy_config_sha256':strategy['config_sha256'],
        'data_snapshot_sha256':bundle.metadata['snapshot_sha256'],
        'source_provenance':bundle.metadata['source_provenance'],
        'horizon':horizon, 'validation_start':begin.date().isoformat(),
        'validation_end':end.date().isoformat(),
        'protocol':{'market':'SPY_20D_TRAILING_RETURN_NONNEGATIVE',
                    'style':'IWD_MINUS_IWF_20D_TRAILING_RETURN_POSITIVE',
                    'risk':'SPY_20D_VOL_NOT_ABOVE_PRIOR_126D_60TH_PERCENTILE',
                    'alpha':'FROZEN_WEIGHTED_CROSS_SECTIONAL_RANK',
                    'gates_predeclared_no_parameter_search':True},
        'ablation':comparison, 'rank_ic_difference_is_not_incremental_pnl':True,
        'not_a_forward_model':True,'not_a_backtest':True,'model_probability_calibrated':False,
        'historical_decision_eligible':False,'research_grade':False,'execution_ready':False,
        'real_orders_enabled':False,'sealed_test_used':False,
        'limitations':['CURRENT_VINTAGE_NOT_PIT','ETF_PROXY_NOT_HISTORICAL_EQUITY_UNIVERSE',
                       'FILTERED_SAMPLE_IC_MUST_NOT_BE_INTERPRETED_AS_TRADING_ALPHA',
                       'NO_ESTIMATED_COST_OR_ORDER_FILLS','NO_MULTIPLE_TESTING_ADJUSTMENT'],
    }
