"""Evidence-gated real-data backtest entry point. No synthetic fixtures or fake results."""
import hashlib
import json
from pathlib import Path

import pandas as pd

from quant_research.backtest.simulation import simulate
from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.data.store import duckdb
from quant_research.models.settings import load_settings
from quant_research.policy import PolicyError
from .common import finish, line_svg, new_run, report, save_frame


def _frozen_predictions(root, path, dataset_sha):
    if path is None:
        raise PolicyError('FROZEN_SIGNAL_ARCHIVE_REQUIRED',
                          'Historical backtest requires previously frozen, PIT-validated model predictions')
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root):
        raise PolicyError('EXTERNAL_PREDICTIONS_NOT_ACCEPTED', 'Archive must belong to approved output storage')
    manifest_path = path / 'manifest.json'
    source = path / 'predictions.parquet'
    if not manifest_path.is_file() or not source.is_file():
        raise PolicyError('HISTORICAL_ARCHIVE_MISSING', 'Frozen prediction manifest/parquet not found')
    meta = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not (meta.get('historical_decision_eligible') is True
            and meta.get('source_snapshot_sha256') == dataset_sha
            and meta.get('status') == 'HISTORICAL_PIT_VALIDATED'
            and meta.get('research_grade') is True
            and meta.get('real_orders_enabled') is False):
        raise PolicyError('HISTORICAL_MODEL_NOT_VERIFIED', 'Model archive lacks PIT acceptance or exact data snapshot')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if meta.get('artifacts_sha256', {}).get('predictions.parquet') != digest:
        raise PolicyError('HISTORICAL_MODEL_HASH_MISMATCH', 'Frozen predictions were modified')
    return pd.read_parquet(source), meta


def _corporate_calendar(db_path, prices, clock):
    sessions = {pd.Timestamp(d).date().isoformat(): [] for d in prices.date.unique()}
    ids = sorted(set(prices.security_id))
    if not ids:
        raise PolicyError('ACTION_CALENDAR_EMPTY', 'No accepted securities to replay')
    with duckdb.connect(str(db_path), read_only=True) as db:
        q = ','.join('?' for _ in ids)
        rows = db.execute(f'''SELECT security_id,ex_date,action_type,factor_or_cash,quality_flag
                  FROM corporate_actions WHERE security_id IN ({q})
                  AND ex_date>=? AND ex_date<=?''',
                  [*ids, min(sessions), max(sessions)]).fetchall()
    for sid, date, kind, amount, quality in rows:
        if 'EVENT_RECONCILED' not in str(quality).split('|'):
            raise PolicyError('ACTION_UNRECONCILED','A real corporate action lacks cash/position reconciliation',[str(sid),str(date)])
        if kind not in ('split','delist'):
            # Dividends require pay-date, ex-date entitlement and corporate cash ledger.
            raise PolicyError('ACTION_ACCOUNTING_UNSUPPORTED',
                              'This corporate action needs accepted event-accounting support',[str(sid),str(date),str(kind)])
        day = str(pd.Timestamp(date).date())
        sessions[day].append({'security_id':str(sid),'action_type':str(kind),
                              'value':float(amount),'settlement_verified':True})
    return sessions


def execute(args):
    config = load_settings(args.experiment)
    # No backtest execution if historical PIT identity, universe or action calendar
    # cannot be proven. The model archive must also be independently frozen.
    bundle = load_real_bundle(args.db, args.source, asof=str(config.validation_end),
                              start=str(config.start), raw_root=Path(args.db).parent/'raw',
                              symbols=args.symbols.split(',') if getattr(args,'symbols',None) else None)
    bundle.require('historical_backtest')
    prices = bundle.prices
    root = Path.cwd()
    predictions, archive = _frozen_predictions(root, args.training_run, bundle.metadata['snapshot_sha256'])
    clock = TradingClock()
    from quant_research.validation.frozen_predictions import validate_frozen_predictions
    prediction_audit = validate_frozen_predictions(predictions, prices, clock, config)
    events = _corporate_calendar(args.db, prices, clock)
    output, manifest = new_run(args, config, 'P5', prices)
    costs = {}
    baseline = None
    for rate in config.cost_scenarios_bps_per_side:
        for horizon in config.horizons:
            outcome = simulate(prices, None, clock, config, predictions, 'D', horizon, rate,
                               baseline=baseline, bundle=bundle, corporate_events=events)
            label = f'h{horizon}_cost_{rate}bps'
            costs[label] = outcome['metrics']
            for key in ('curve','trades','fills','orders','positions','exposures','actions'):
                save_frame(outcome[key], output, f'{label}_{key}')
    metrics = pd.DataFrame([{'scenario':k, **v} for k,v in costs.items()])
    save_frame(metrics, output, 'backtest_metrics')
    manifest.update(status='MODELED_HISTORICAL_FILLS_NOT_BROKER_ORDERS',
        flags=['SOURCE_VERIFIED_RAW_OHLCV','HISTORICAL_PIT_ADMISSION_PASSED','MODELED_FILLS_NOT_BROKER_ORDERS'],
        universe_version='VERIFIED_EFFECTIVE_DATED_SOURCE_UNIVERSE',
        historical_decision_eligible=True, model_archive_sha256=hashlib.sha256(
            (Path(args.training_run)/'manifest.json').read_bytes()).hexdigest(),
        model_archive_status=archive['status'], frozen_prediction_row_audit=prediction_audit, costs_by_scenario=costs,
        data_snapshot_sha256=bundle.metadata['snapshot_sha256'],
        real_orders_enabled=False, research_grade=True)
    report(output, 'P5 合格真实历史数据回测', manifest,
           {'成本与持有期对比': metrics},
           note='真实来源行情、已验证历史信号；成交价为 next-open 模拟加成本估计，不是真实券商成交。')
    finish(args, output, manifest)
    return 0
