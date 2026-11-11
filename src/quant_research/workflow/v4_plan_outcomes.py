"""V4 prospective review outcomes from source-referenced actual future daily bars.

This is a read-only evaluation of previously frozen RESEARCH plans. It never
posts orders, creates broker fills, or claims a strategy won before future
sessions have actually closed. Round-trip costs are model assumptions, not
broker receipts; daily OHLC stops are approximations with explicit gap risk.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import tempfile

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.workflow.v4_candidate_bridge import read_indicative_review

_COLUMNS={'session_date','security_id','open','high','low','close','available_at',
          'source_sha256','corporate_action_status'}
_SHA=re.compile(r'[0-9a-f]{64}\Z')
_ID=re.compile(r'[0-9a-f]{16}\Z')


def _canonical(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False,
                      separators=(',',':'))


def evaluate_research_outcomes(root, session_date: str, plan_identity: str,
                               bars: pd.DataFrame, *,
                               observed_at_utc: str) -> dict:
    """Reconcile a frozen H3 research plan to later, supplied raw market bars.

    The receipt digest is validated structurally; source provenance must be
    independently attested elsewhere. Missing/corrupt bars always block.
    """
    review=read_indicative_review(root,session_date,plan_identity)
    asof=pd.Timestamp(observed_at_utc)
    if asof.tzinfo is None:
        raise ValueError('EVALUATION_ASOF_REQUIRES_UTC_OFFSET')
    asof=asof.tz_convert('UTC')
    if asof > pd.Timestamp.now(tz='UTC'):
        raise ValueError('EVALUATION_CUTOFF_CANNOT_BE_IN_THE_FUTURE')
    clock=TradingClock()
    horizon=int(review['horizon'])
    window=clock.window(session_date,horizon)
    if asof < pd.Timestamp(window.exit_time):
        return {'status':'FUTURE_OUTCOME_NOT_YET_OBSERVED',
                'session_date_et':session_date,'plan_identity':plan_identity,
                'evaluated':[],'real_orders_enabled':False}
    if not review['plans']:
        return {'status':'NO_TRADE_PLAN_TO_EVALUATE',
                'session_date_et':session_date,'plan_identity':plan_identity,
                'evaluated':[],'real_orders_enabled':False}
    if not isinstance(bars,pd.DataFrame) or _COLUMNS-set(bars):
        raise ValueError('FUTURE_RAW_BAR_RECEIPTS_INCOMPLETE')
    data=bars.copy()
    data['session_date']=pd.to_datetime(data['session_date'])
    if data.session_date.dt.tz is not None:
        raise ValueError('Future sessions must be market-local dates')
    data['available_at']=pd.to_datetime(data.available_at,utc=True)
    if data.available_at.isna().any() or data.available_at.gt(asof).any():
        raise ValueError('FUTURE_BAR_NOT_AVAILABLE_BY_EVALUATION_CUTOFF')
    if data.duplicated(['session_date','security_id']).any():
        raise ValueError('DUPLICATE_FUTURE_SECURITY_BARS')
    if not data.source_sha256.map(lambda x:isinstance(x,str) and bool(_SHA.fullmatch(x))).all():
        raise ValueError('FUTURE_BAR_SOURCE_RECEIPT_MISSING')
    if not data.corporate_action_status.eq('VERIFIED_NO_ACTION').all():
        raise ValueError('CORPORATE_ACTION_ACCOUNTING_NOT_SUPPORTED')
    for col in ('open','high','low','close'):
        data[col]=pd.to_numeric(data[col],errors='coerce')
    values=data[['open','high','low','close']].to_numpy(dtype=float)
    if (not pd.notna(values).all() or not all(math.isfinite(v) and v>0 for v in values.flat)
            or not ((data.high>=data[['open','close','low']].max(axis=1))
                    & (data.low<=data[['open','close','high']].min(axis=1))).all()):
        raise ValueError('INVALID_FUTURE_RAW_OHLC')
    sessions=clock.calendar.sessions
    pos=sessions.get_loc(clock.session(session_date))
    required=sessions[pos+1:pos+horizon+1]
    expected_end=pd.Timestamp(window.exit_time)
    results=[]
    for plan in review['plans']:
        sid=str(plan['security_id'])
        exact=data.loc[data.security_id.astype(str).eq(sid)].copy()
        if (len(exact)!=len(required) or
                set(exact.session_date)!=set(required)):
            raise ValueError('FUTURE_TRADE_SESSION_BAR_COVERAGE_INCOMPLETE')
        exact=exact.sort_values('session_date')
        for rec in exact.itertuples(index=False):
            cutoff=pd.Timestamp(clock.close(rec.session_date))
            observed=pd.Timestamp(rec.available_at)
            if observed<cutoff:
                raise ValueError('FUTURE_BAR_PUBLISHED_BEFORE_ITS_CLOSE')
        first=exact.iloc[0]
        entry=float(first['open'])
        atr=float(plan['decision_atr20'])
        distance=float(plan['initial_stop_distance'])
        if not (math.isfinite(atr) and atr>0
                and math.isfinite(distance) and distance>0 and distance<entry):
            raise ValueError('FROZEN_STOP_DISTANCE_UNVERIFIED')
        stop=entry-distance
        exit_price=float(exact.iloc[-1]['close'])
        exit_day=str(required[-1].date())
        exit_reason='HORIZON_CLOSE'
        for position,bar in exact.reset_index(drop=True).iterrows():
            if float(bar['low'])<=stop:
                # If the market gaps below stop on a later day, exit is at
                # the worse OPEN price. Intraday execution remains a scenario.
                exit_price=min(float(bar['open']),stop)
                exit_day=str(pd.Timestamp(bar['session_date']).date())
                exit_reason='INTRADAY_STOP_ASSUMED' if exit_price==stop else 'GAP_THROUGH_STOP'
                break
        gross=exit_price/entry-1
        assumed_cost=float(plan['estimated_round_trip_cost'])
        if not math.isfinite(assumed_cost) or assumed_cost<0 or assumed_cost>.2:
            raise ValueError('FROZEN_COST_ASSUMPTION_UNVERIFIED')
        results.append({'security_id':sid,'planned_entry_session':str(required[0].date()),
                        'modeled_entry_price':entry,'modeled_exit_price':exit_price,
                        'modeled_exit_session':exit_day,
                        'modeled_exit_reason':exit_reason,
                        'frozen_stop_distance':distance,
                        'expected_net_edge':float(plan['estimated_net_edge']),
                        'realized_gross_price_return':gross,
                        'assumed_round_trip_cost':assumed_cost,
                        'modeled_net_return':gross-assumed_cost,
                        'net_forecast_error':(gross-assumed_cost)-float(plan['estimated_net_edge']),
                        'price_source_sha256':[str(v) for v in exact.source_sha256],
                        'execution_is_modeled_not_broker_filled':True})
    output={'status':'PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY',
            'session_date_et':session_date,'plan_identity':plan_identity,
            'source_plan_sha256':review['content_sha256'],
            'observed_at_utc':asof.isoformat(),
            'evaluated':results,'real_orders_enabled':False,
            'paper_ledger_advanced':False,
            'source_independently_attested':False,
            'warning':'Raw OHLC and stop fills are scenarios; independent SIP/source/corporate-action receipts and real fills not established'}
    output['content_sha256']=sha256(_canonical(output).encode()).hexdigest()
    return output


def freeze_research_outcomes(root, result: dict) -> dict:
    """Append once and refuse updates to a historical modeled result."""
    if result.get('status')!='PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY':
        raise ValueError('Only completed prospective research outcomes may be archived')
    body=dict(result)
    digest=body.pop('content_sha256',None)
    if digest!=sha256(_canonical(body).encode()).hexdigest():
        raise ValueError('Outcome content digest invalid')
    day=result['session_date_et']
    identity=result['plan_identity']
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or not _ID.fullmatch(identity):
        raise ValueError('Invalid outcome archive identity')
    base=Path(root).resolve()/'outputs/v4_research_outcomes'/day
    base.mkdir(parents=True,exist_ok=True)
    dest=base/identity
    if dest.exists():
        current=read_research_outcomes(root,day,identity)
        if current!=result:
            raise ValueError('Frozen research outcomes cannot be revised')
        return current
    with tempfile.TemporaryDirectory(prefix='.writing-',dir=base) as tmp:
        (Path(tmp)/'outcomes.json').write_text(json.dumps(result,ensure_ascii=False,
                    sort_keys=True,indent=2,allow_nan=False),encoding='utf-8')
        Path(tmp).rename(dest)
    return read_research_outcomes(root,day,identity)


def read_research_outcomes(root, day, identity):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or not _ID.fullmatch(identity):
        raise ValueError('Invalid outcome path')
    file=Path(root).resolve()/'outputs/v4_research_outcomes'/day/identity/'outcomes.json'
    if not file.is_file():
        raise FileNotFoundError('Outcome archive absent')
    recorded=json.loads(file.read_text(encoding='utf-8'))
    digest=recorded.pop('content_sha256',None)
    if (not isinstance(digest,str) or digest!=sha256(_canonical(recorded).encode()).hexdigest()
            or recorded.get('plan_identity')!=identity
            or recorded.get('session_date_et')!=day
            or recorded.get('real_orders_enabled') is not False
            or recorded.get('paper_ledger_advanced') is not False):
        raise ValueError('Frozen outcome integrity or execution claim invalid')
    original=read_indicative_review(root,day,identity)
    if recorded.get('source_plan_sha256')!=original.get('content_sha256'):
        raise ValueError('Outcome does not correspond to frozen source plan')
    recorded['content_sha256']=digest
    return recorded
