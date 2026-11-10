"""Cross-sectional multi-factor research on independently verified REAL factor artifacts.

Not a point-in-time historical strategy, predicted return, backtest or tradable signal.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant_research.policy import PolicyError
from quant_research.research.strategy import StrategyRegistry
from quant_research.research.statistics import daily_rank_ic
from quant_research.workflow.factor_lab import result as checked_experiment


def _verified_parquet(root, experiment_id, name):
    """The factor result verifier checks every artifact digest before this read."""
    detail = checked_experiment(root, experiment_id)
    if detail['status'] != 'COMPLETED':
        raise PolicyError('FACTOR_EXPERIMENT_NOT_COMPLETE', 'Factor result is not complete')
    folder = root / 'outputs/factor_lab' / experiment_id
    path = (folder / name).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise PolicyError('FACTOR_ARTIFACT_PATH_REJECTED', 'Factor file escaped its output directory')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    expected = manifest.get('artifacts_sha256', {}).get(name)
    if not expected or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise PolicyError('FACTOR_ARTIFACT_CORRUPT', 'Factor artifact hash or file is missing', [name])
    return pd.read_parquet(path)


def _rank_frame(frame, identifier):
    required = {'date', 'security_id', 'value', 'decision_eligible', 'research_mode'}
    if required - set(frame):
        raise PolicyError('FACTOR_FEATURE_FIELDS_MISSING', 'Input feature columns are incomplete', sorted(required - set(frame)))
    if frame.empty or frame.duplicated(['date', 'security_id']).any():
        raise PolicyError('FACTOR_FEATURE_KEYS_INVALID', 'Empty or duplicate factor observations')
    if not frame.research_mode.eq('retrospective').all() or frame.decision_eligible.fillna(False).any():
        raise PolicyError('FACTOR_RESEARCH_SCOPE_INVALID', 'Composite accepts retrospective non-executable features only')
    frame = frame[['date', 'security_id', 'value']].copy()
    frame['value'] = pd.to_numeric(frame.value, errors='coerce').replace([np.inf, -np.inf], np.nan)
    # Keep raw factor values until all component nulls are removed. Rankings
    # must use the SAME surviving cross-section across every component.
    return frame.rename(columns={'value': identifier})


def compute_composite(root, strategy_id):
    """Calculate descriptive weighted ranking and validation IC from genuine saved experiment rows.

    All members must share source, data SHA, symbol universe and evaluation protocol.
    Missing factor rows are never filled. A result is never marked decision eligible.
    """
    root = Path(root).resolve()
    strategy = StrategyRegistry(root).validate(strategy_id)['strategy']
    mix = strategy['config'].get('factor_mix')
    if not mix:
        raise PolicyError('MULTIFACTOR_STRATEGY_REQUIRED', 'Choose a strategy with at least two verified factor experiments')
    allocations = mix['allocations']
    components, identifiers = [], []
    for allocation in allocations:
        identifier = allocation['factor_experiment_id']
        frame = _verified_parquet(root, identifier, 'features.parquet')
        components.append(_rank_frame(frame, identifier))
        identifiers.append(identifier)
    # The same date/security must have every input value. No implicit zero or forward fill.
    joined = components[0]
    for component in components[1:]:
        joined = joined.merge(component, on=['date', 'security_id'], how='inner', validate='one_to_one')
    joined = joined.dropna(subset=identifiers).copy()
    if joined.empty:
        raise PolicyError('NO_COMPLETE_FACTOR_INTERSECTION', 'No securities have all component factor values')
    for identifier in identifiers:
        joined[identifier] = joined.groupby('date')[identifier].rank(method='average', pct=True)
    joined['value'] = sum(joined[part] * a['weight'] for part, a in zip(identifiers, allocations))
    joined['date'] = pd.to_datetime(joined['date'])
    protocol = strategy['config']['protocol']
    cutoff = pd.Timestamp(protocol['validation_end'])
    start = pd.Timestamp(protocol['train_end']) + pd.Timedelta(days=1)
    validation = joined.loc[joined.date.between(start, cutoff)].copy()
    if validation.empty:
        raise PolicyError('NO_VALIDATION_COMPOSITE', 'No complete multivariate validation rows')
    labels = _verified_parquet(root, identifiers[0], 'labels.parquet')
    required = {'date', 'security_id', 'horizon', 'exit_date', 'proxy_forward_return'}
    if required - set(labels):
        raise PolicyError('FACTOR_LABEL_FIELDS_MISSING', 'Real price-proxy labels are incomplete', sorted(required - set(labels)))
    if labels.duplicated(['date','security_id','horizon']).any():
        raise PolicyError('FACTOR_LABEL_KEYS_INVALID','Duplicate label keys')
    labels = labels.loc[labels.horizon.eq(strategy['config']['strategy']['horizon'])].copy()
    labels['date'] = pd.to_datetime(labels.date)
    labels = labels.loc[labels.date.between(start, cutoff) & (pd.to_datetime(labels.exit_date) <= cutoff)]
    validation = validation.merge(labels[['date','security_id','proxy_forward_return']],
                                  on=['date','security_id'], how='left', validate='one_to_one')
    validation['target'] = pd.to_numeric(validation.proxy_forward_return, errors='coerce')
    min_count = int(checked_experiment(root, identifiers[0])['result']['experiment']['min_cross_section'])
    ic = daily_rank_ic(validation[['date','security_id','value','target']],min_count=min_count)
    usable = ic['rank_ic'].dropna()
    if usable.empty:
        raise PolicyError('COMPOSITE_VALIDATION_TOO_SPARSE','Insufficient paired real price-proxy labels for composite IC')
    last_day = validation.date.max()
    latest = validation.loc[validation.date.eq(last_day)].sort_values('value',ascending=False)
    return {
        'status':'RETROSPECTIVE_COMPOSITE_RESEARCH_ONLY',
        'strategy_version_id':strategy['id'], 'strategy_config_sha256':strategy['config_sha256'],
        'source':mix['research_scope']['source'],
        'data_snapshot_sha256':mix['research_scope']['snapshot_sha256'],
        'asof_date_et':last_day.date().isoformat(),
        'validation_window':{'start':start.date().isoformat(),'end':cutoff.date().isoformat()},
        'horizon':strategy['config']['strategy']['horizon'],
        'factors':[{'factor_name':a['dependency']['factor_name'],
                    'experiment_id':a['factor_experiment_id'],'weight':a['weight']}
                   for a in allocations],
        'matched_validation_rows':len(validation),
        'complete_case_count':int(validation[['value','target']].notna().all(axis=1).sum()),
        'validation_daily_ic_count':int(usable.count()),
        'validation_rank_ic_mean':float(usable.mean()),
        'latest_composite_ranking':[{'security_id':str(row.security_id),'score':float(row.value)}
                                    for row in latest.head(30).itertuples(index=False)],
        'factor_coverage_policy':'ALL_COMPONENTS_REQUIRED_NO_IMPUTATION',
        'label_basis':'REAL_CURRENT_VINTAGE_FORWARD_PRICE_PROXY_NOT_MODEL_FILL',
        'historical_decision_eligible':False,'research_grade':False,'execution_ready':False,
        'real_orders_enabled':False,'sealed_test_used':False,
        'limitations':['HISTORICAL_PIT_NOT_PROVEN','NOT_A_BACKTEST','NOT_TRADING_SIGNALS',
                       'NOT_MULTIPLE_TESTING_CORRECTED','PRICE_PROXY_NOT_NET_RETURN'],
    }
