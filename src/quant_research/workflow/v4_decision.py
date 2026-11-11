"""V4 research candidate-to-plan engine with explicit non-execution boundary.

Research projections may support an indicative *next-session* plan. Neither a
backtest fill nor a broker/paper order is produced. A separately audited
immutable decision and real-data execution source are required for admission.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import floor, isfinite

import pandas as pd


@dataclass(frozen=True)
class PlanPolicy:
    horizon: int = 3
    top_n: int = 5
    min_probability_up: float = 0.53
    max_downside_probability: float = 0.20
    min_net_edge: float = 0.005
    risk_budget: float = 0.003
    max_stock_weight: float = 0.10
    max_total_weight: float = 0.50
    max_sector_weight: float = 0.25
    max_participation: float = 0.01
    min_price: float = 5.0
    min_adv20: float = 20_000_000.0
    stop_atr_multiple: float = 2.0
    cost_bps_per_side: float = 10.0
    impact_bps_per_full_adv: float = 100.0

    def __post_init__(self):
        if self.horizon not in (1, 3, 5) or not 1 <= self.top_n <= 50:
            raise ValueError('Only 1/3/5 session horizons and top_n 1–50 are allowed')
        if not (0 <= self.min_probability_up <= 1 and 0 <= self.max_downside_probability <= 1):
            raise ValueError('Probability thresholds must be in [0,1]')
        limits = ('risk_budget','max_stock_weight','max_total_weight','max_sector_weight',
                  'max_participation','min_price','min_adv20','stop_atr_multiple')
        if any(not isfinite(getattr(self,k)) or getattr(self,k) <= 0 for k in limits):
            raise ValueError('Risk, price and volume limits must be positive finite values')
        if not (0 < self.max_stock_weight <= self.max_total_weight <= 1
                and self.max_sector_weight <= self.max_total_weight):
            raise ValueError('Portfolio allocation limits conflict')
        if (self.cost_bps_per_side < 0 or self.impact_bps_per_full_adv < 0
                or not isfinite(self.min_net_edge) or self.min_net_edge < 0):
            raise ValueError('Cost/edge parameters must be nonnegative')


_FIELDS = {'security_id','symbol','sector','horizon','signal_time','entry_time','exit_time',
           'feature_available_at','model_fit_time','source_snapshot_sha256','model_version',
           'predicted_gross_return','predicted_excess_return','p_up','p_downside',
           'up_calibration_status','downside_calibration_status','reference_close','atr20','adv20'}


def _finite(row, key):
    value = row.get(key)
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if isfinite(output) else None


def _cost_fraction(notional, adv20, policy):
    # Per-side linear impact is a deliberately simple scenario assumption;
    # real execution conditions must be independently validated.
    participation = notional / adv20
    per_side_bps = policy.cost_bps_per_side + policy.impact_bps_per_full_adv * participation
    return 2 * per_side_bps / 10000


def indicative_plans(projections: pd.DataFrame, existing_holdings: pd.DataFrame,
                     *, equity: float, cash: float, frozen_at_utc: str,
                     policy: PlanPolicy = PlanPolicy()) -> dict:
    """Research-only ranked plans; never writes a trade, ledger or qualification.

    Historical/actual forecasts cannot be manufactured by this function.
    Results require independent OOS model approval and real feed admission
    before an audited execution workflow can consume them.
    """
    if not isfinite(equity) or equity <= 0 or not isfinite(cash) or not 0 <= cash <= equity:
        raise ValueError('Equity and cash must be real finite account amounts')
    frozen_at = pd.Timestamp(frozen_at_utc)
    if frozen_at.tzinfo is None:
        raise ValueError('Freeze time must include UTC offset')
    frozen_at = frozen_at.tz_convert('UTC')
    if not isinstance(projections, pd.DataFrame) or _FIELDS - set(projections):
        raise ValueError(f'Incomplete model projections: {sorted(_FIELDS - set(projections))}')
    if not isinstance(existing_holdings, pd.DataFrame) or {'security_id','sector','weight'} - set(existing_holdings):
        raise ValueError('Existing holdings need security_id, sector and NAV weight')
    if existing_holdings.security_id.duplicated().any():
        raise ValueError('Duplicate existing security identities')
    weights = pd.to_numeric(existing_holdings.weight, errors='coerce')
    if weights.isna().any() or (weights < 0).any() or (~weights.map(isfinite)).any():
        raise ValueError('Invalid existing NAV exposures')
    held = {str(row.security_id):float(row.weight) for row in existing_holdings.itertuples(index=False)}
    sector_exposure = {}
    for row in existing_holdings.itertuples(index=False):
        sector_exposure[str(row.sector)] = sector_exposure.get(str(row.sector),0.) + float(row.weight)
    total_exposure = float(weights.sum())
    if total_exposure > 1 + 1e-9:
        raise ValueError('Existing exposures exceed total NAV')
    chosen = projections.loc[projections.horizon.eq(policy.horizon)].copy()
    if chosen.duplicated(['security_id','horizon']).any():
        raise ValueError('Duplicate projections for the same security and horizon')
    evaluated, accepted = [], []
    for row in chosen.to_dict('records'):
        sid, sector = str(row['security_id']), str(row['sector'])
        reason = None
        try:
            signal = pd.Timestamp(row['signal_time']).tz_convert('UTC')
            available = pd.Timestamp(row['feature_available_at']).tz_convert('UTC')
            model_fit = pd.Timestamp(row['model_fit_time']).tz_convert('UTC')
            entry = pd.Timestamp(row['entry_time']).tz_convert('UTC')
            exit_time = pd.Timestamp(row['exit_time']).tz_convert('UTC')
        except (TypeError, ValueError, AttributeError):
            reason = 'INVALID_FORECAST_TIMESTAMPS'
        if reason is None and not (available <= signal <= frozen_at < entry < exit_time
                                   and model_fit <= signal):
            reason = 'FUTURE_INPUT_OR_INVALID_ENTRY_WINDOW'
        digest = row.get('source_snapshot_sha256')
        if reason is None and not (isinstance(digest,str) and len(digest)==64
                                   and all(c in '0123456789abcdef' for c in digest)):
            reason = 'SOURCE_DIGEST_MISSING'
        if reason is None and (row.get('up_calibration_status')!='CALIBRATED_CHRONOLOGICAL_HOLDOUT'
                               or row.get('downside_calibration_status')!='CALIBRATED_CHRONOLOGICAL_HOLDOUT'):
            reason = 'MODEL_PROBABILITY_NOT_CALIBRATED'
        ret, p_up, p_down = (_finite(row,k) for k in ('predicted_gross_return','p_up','p_downside'))
        price,atr,adv = (_finite(row,k) for k in ('reference_close','atr20','adv20'))
        if reason is None and (ret is None or p_up is None or p_down is None
                               or not 0 <= p_up <= 1 or not 0 <= p_down <= 1):
            reason = 'PREDICTION_MISSING'
        if reason is None and (price is None or atr is None or adv is None
                               or price < policy.min_price or atr <= 0 or adv < policy.min_adv20):
            reason = 'PRICE_LIQUIDITY_OR_ATR_INVALID'
        if reason is None and sid in held:
            reason = 'ALREADY_HELD_NO_DUPLICATE_ENTRY'
        if reason is None and (not sector or sector.upper() in ('UNKNOWN','N/A')):
            reason = 'SECTOR_UNKNOWN'
        if reason is None and (p_up < policy.min_probability_up or p_down > policy.max_downside_probability):
            reason = 'PROBABILITY_RISK_FILTER'
        if reason:
            evaluated.append({'security_id':sid,'symbol':str(row.get('symbol','')),
                              'accepted':False,'reason':reason})
            continue
        stop_distance_pct = policy.stop_atr_multiple * atr / price
        if not 0 < stop_distance_pct < 1:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'STOP_DISTANCE_INVALID'})
            continue
        room = min(policy.max_stock_weight,
                   policy.max_total_weight-total_exposure,
                   policy.max_sector_weight-sector_exposure.get(sector,0.),
                   policy.risk_budget/stop_distance_pct,
                   policy.max_participation*adv/equity,
                   cash/equity)
        if room <= 0:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'NO_POSITION_CAPACITY'})
            continue
        notional = room*equity
        cost = _cost_fraction(notional,adv,policy)
        net_edge = ret-cost
        if net_edge <= policy.min_net_edge:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'INSUFFICIENT_NET_EDGE',
                              'estimated_net_edge':net_edge})
            continue
        accepted.append({'security_id':sid,'symbol':str(row['symbol']), 'sector':sector,
                         'horizon':policy.horizon,'model_version':str(row['model_version']),
                         'source_snapshot_sha256':digest,'signal_time':signal.isoformat(),
                         'entry_time':entry.isoformat(),'exit_time':exit_time.isoformat(),
                         'expected_gross_return':ret,
                         'expected_excess_return':_finite(row,'predicted_excess_return'),
                         'probability_up':p_up,'probability_downside':p_down,
                         'estimated_round_trip_cost':cost,'estimated_net_edge':net_edge,
                         'reference_price':price,'adv20':adv,
                         'indicative_weight':room,'indicative_shares':floor(notional/price),
                         'entry_rule':'NEXT_SESSION_OPEN_IF_FROZEN_CONDITIONS_REMAIN_VALID',
                         'stop_rule':f'{policy.stop_atr_multiple}xATR_FROM_ACTUAL_ENTRY_FILL',
                         'exit_rule':'STOP_OR_PREDECLARED_HORIZON_END',
                         'research_only':True,'execution_eligible':False})
    # Choose a consistent one-pass portfolio capacity ranking (highest net edge).
    accepted.sort(key=lambda x:(-x['estimated_net_edge'],x['security_id']))
    plans, allocated = [], 0.
    for row in accepted:
        sid,sector=row['security_id'],row['sector']
        if len(plans)>=policy.top_n:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'TOP_N_LIMIT'})
            continue
        space = min(row['indicative_weight'],policy.max_total_weight-total_exposure,
                    policy.max_sector_weight-sector_exposure.get(sector,0.),
                    cash/equity-allocated)
        if space <= 0:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'FINAL_PORTFOLIO_CAPACITY'})
            continue
        row['indicative_weight'] = space
        row['indicative_shares'] = floor(space*equity/row['reference_price'])
        if row['indicative_shares'] < 1:
            evaluated.append({'security_id':sid,'accepted':False,'reason':'LESS_THAN_ONE_SHARE'})
            continue
        row['estimated_round_trip_cost'] = _cost_fraction(space*equity,row['adv20'],policy)
        row['estimated_net_edge'] = row['expected_gross_return']-row['estimated_round_trip_cost']
        row.pop('reference_price')
        row.pop('adv20')
        plans.append(row)
        total_exposure += space
        allocated += space
        sector_exposure[sector] = sector_exposure.get(sector,0.)+space
        evaluated.append({'security_id':sid,'accepted':True,'reason':'INDICATIVE_RESEARCH_PLAN'})
    payload = {'status':'RESEARCH_PLANS_ONLY' if plans else 'NO_RESEARCH_CANDIDATES',
               'asof_frozen_utc':frozen_at.isoformat(),
               'horizon':policy.horizon,'plans':plans,
               'evaluated':evaluated, 'real_orders_enabled':False,
               'execution_eligible':False,'requires_independent_model_and_source_admission':True}
    payload['content_sha256']=sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()
    return payload
