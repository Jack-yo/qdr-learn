"""V4 bridge: frozen Alpha forecasts -> source-matched candidate risk review.

A model prediction does not become a tradable signal merely because it was
archived. Both the account and security metadata must match the *same* T-day
source snapshot. This module only writes non-executing research plans.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import re
import tempfile

import pandas as pd

from quant_research.research.v4_forecast_archive import read_research_forecast
from quant_research.workflow.v4_decision import PlanPolicy, indicative_plans

_SHA=re.compile(r'[0-9a-f]{64}\Z')
_ID=re.compile(r'[0-9a-f]{16}\Z')
_COLUMNS={'date','security_id','symbol','sector','reference_close','atr20','adv20',
          'available_at','source_snapshot_sha256'}
_PARENT=Path('outputs/v4_research_plans')


def _canonical(obj):
    return json.dumps(obj,sort_keys=True,ensure_ascii=False,
                      separators=(',',':'),allow_nan=False)


def _account_holdings(account, asof, *, clock):
    if account.get('status')=='EXPLICIT_EMPTY_RESEARCH_BUDGET':
        # A capital scenario is useful for sizing research opportunities before
        # a real paper book exists; it is NOT a reconciled account or P&L.
        capital=account.get('budget')
        if (account.get('session_date_et')!=asof
                or account.get('has_actual_positions') is not False
                or not isinstance(capital,(float,int)) or isinstance(capital,bool)
                or not math.isfinite(capital) or not 1<=capital<=1_000_000_000):
            raise ValueError('RESEARCH_BUDGET_SCENARIO_UNVERIFIED')
        return pd.DataFrame(columns=['security_id','sector','weight']),float(capital),float(capital)
    if account.get('status')!='INTERNALLY_RECONCILED_PAPER_ESTIMATE':
        raise ValueError('ACCOUNT_NOT_RECONCILED')
    if str(account.get('last_session')) != str(asof):
        raise ValueError('ACCOUNT_MARKS_NOT_FROM_SIGNAL_DAY')
    equity,cash=account.get('equity'),account.get('cash')
    if (not isinstance(equity,(float,int)) or not math.isfinite(equity) or equity<=0
            or not isinstance(cash,(float,int)) or not math.isfinite(cash)
            or cash<0 or cash>equity):
        raise ValueError('PAPER_ACCOUNT_EQUITY_UNVERIFIED')
    positions=account.get('position_details')
    marks=account.get('last_prices')
    if not isinstance(positions,dict) or not isinstance(marks,dict):
        raise ValueError('PAPER_ACCOUNT_POSITIONS_UNVERIFIED')
    rows=[]
    for sid,item in positions.items():
        if not isinstance(item,dict):
            raise ValueError('PAPER_ACCOUNT_HOLDING_UNVERIFIED')
        sector=item.get('sector')
        quantity=item.get('quantity')
        mark=marks.get(sid)
        if (not isinstance(sector,str) or sector.upper() in ('','UNKNOWN','N/A','UNVERIFIED')
                or not isinstance(quantity,(int,float)) or not math.isfinite(quantity) or quantity<=0
                or not isinstance(mark,(float,int)) or not math.isfinite(mark) or mark<=0):
            raise ValueError('PAPER_ACCOUNT_HOLDING_UNVERIFIED')
        rows.append({'security_id':sid,'sector':sector,
                     'weight':float(quantity*mark/equity)})
    return pd.DataFrame(rows,columns=['security_id','sector','weight']),float(equity),float(cash)


def _merge_source_metadata(predictions, securities, snapshot, asof, freeze_time):
    if not isinstance(securities,pd.DataFrame) or _COLUMNS-set(securities):
        raise ValueError('CANDIDATE_SOURCE_METADATA_INCOMPLETE')
    if securities.duplicated('security_id').any():
        raise ValueError('CANDIDATE_IDENTITY_DUPLICATE')
    if not securities.date.astype(str).eq(str(asof)).all():
        raise ValueError('CANDIDATE_METADATA_WRONG_SESSION')
    if not securities.source_snapshot_sha256.eq(snapshot).all():
        raise ValueError('CANDIDATE_METADATA_SOURCE_MISMATCH')
    times=pd.to_datetime(securities.available_at,utc=True)
    if times.isna().any():
        raise ValueError('CANDIDATE_METADATA_TIMESTAMP_MISSING')
    if not times.le(freeze_time).all():
        raise ValueError('CANDIDATE_METADATA_AFTER_FREEZE')
    metadata=securities.drop(columns=['date','source_snapshot_sha256']).copy()
    metadata['metadata_available_at']=times
    predicted=predictions.loc[predictions.model_variant.eq('D')
                               & predictions.horizon.eq(3)].copy()
    if predicted.empty:
        raise ValueError('NO_D_CONDITIONAL_H3_FORECAST')
    if predicted.duplicated(['security_id','horizon']).any():
        raise ValueError('DUPLICATED_FROZEN_MODEL_CANDIDATE')
    if not predicted.security_id.isin(metadata.security_id).all():
        raise ValueError('CANDIDATE_SOURCE_METADATA_MISSING')
    result=predicted.merge(metadata,on='security_id',how='inner',validate='many_to_one')
    for col in ('reference_close','atr20','adv20'):
        numeric=pd.to_numeric(result[col],errors='coerce')
        if numeric.isna().any() or not numeric.map(math.isfinite).all():
            raise ValueError('CANDIDATE_PRICE_OR_LIQUIDITY_INVALID')
        result[col]=numeric
    if (pd.to_datetime(result.metadata_available_at,utc=True)
              .gt(pd.to_datetime(result.signal_time,utc=True))).any():
        raise ValueError('CANDIDATE_METADATA_AFTER_SIGNAL')
    return result


def make_indicative_review(root, *, session_date: str, forecast_identity: str,
                           securities: pd.DataFrame, account: dict,
                           frozen_at_utc: str, policy: PlanPolicy=PlanPolicy()) -> dict:
    """Link the four-layer Alpha output to cost-aware risk, never to paper fills."""
    freeze=pd.Timestamp(frozen_at_utc)
    if freeze.tzinfo is None:
        raise ValueError('REVIEW_FREEZE_REQUIRES_TIMEZONE')
    freeze=freeze.tz_convert('UTC')
    if not _ID.fullmatch(forecast_identity):
        raise ValueError('INVALID_FORECAST_IDENTITY')
    archived=read_research_forecast(root,session_date,forecast_identity,include_rows=True)
    manifest=archived['manifest']
    if not manifest.get('prospective_before_next_open'):
        return {'status':'RETROSPECTIVE_RECONSTRUCTION_NOT_A_LIVE_PLAN',
                'plans':[],'evaluated':[],
                'source_forecast_identity':forecast_identity,
                'execution_eligible':False,'real_orders_enabled':False}
    if manifest.get('session_date_et')!=session_date:
        raise ValueError('CROSS_SESSION_FORECAST_IDENTITY')
    source=manifest['source_snapshot_sha256']
    if not _SHA.fullmatch(source):
        raise ValueError('SOURCE_SNAPSHOT_MISSING')
    forecasts=archived['forecasts']
    if (not forecasts.source_snapshot_sha256.eq(source).all()
            or not forecasts.decision_eligible.eq(False).all()):
        raise ValueError('FORECAST_SOURCE_OR_ELIGIBILITY_MISMATCH')
    from quant_research.clock import TradingClock
    clock=TradingClock()
    planned=clock.window(session_date,policy.horizon)
    if not (pd.Timestamp(planned.signal_time)<=freeze<pd.Timestamp(planned.entry_time)):
        raise ValueError('REVIEW_NOT_BEFORE_NEXT_SESSION_ENTRY')
    holdings,equity,cash=_account_holdings(account,session_date,clock=clock)
    merged=_merge_source_metadata(forecasts,securities,source,session_date,freeze)
    # The forecast model must have been fitted no later than the review freeze.
    if 'model_fit_time' not in merged or pd.to_datetime(
            merged.model_fit_time,utc=True).gt(freeze).any():
        raise ValueError('MODEL_FITTED_AFTER_PLAN_FREEZE')
    candidates=pd.DataFrame({
        'security_id':merged.security_id.astype(str),
        'symbol':merged.symbol,
        'sector':merged.sector,
        'horizon':merged.horizon,
        'signal_time':merged.signal_time,
        'entry_time':merged.entry_time,
        'exit_time':merged.exit_time,
        'feature_available_at':merged.feature_available_at,
        'model_fit_time':merged.model_fit_time,
        'source_snapshot_sha256':merged.source_snapshot_sha256,
        'model_version':merged.model_version,
        'predicted_gross_return':merged.expected_gross_trade_return,
        'predicted_excess_return':merged.expected_excess_return,
        'p_up':merged.p_up,
        'p_downside':merged.p_downside,
        'up_calibration_status':merged.probability_status_up,
        'downside_calibration_status':merged.probability_status_downside,
        'reference_close':merged.reference_close,
        'atr20':merged.atr20,
        'adv20':merged.adv20,
    })
    review=indicative_plans(candidates,holdings,equity=equity,cash=cash,
                            frozen_at_utc=freeze.isoformat(),policy=policy)
    review.update({'source_forecast_identity':forecast_identity,
                   'source_forecast_manifest_sha256':archived['manifest_sha256'],
                   'source_snapshot_sha256':source,
                   'source_account_session':account.get('last_session',session_date),
                   'account_budget':float(equity) if account.get('status')=='EXPLICIT_EMPTY_RESEARCH_BUDGET' else None,
                   'account_evidence':('EXPLICIT_EMPTY_RESEARCH_BUDGET_NOT_A_PAPER_ACCOUNT'
                                       if account.get('status')=='EXPLICIT_EMPTY_RESEARCH_BUDGET'
                                       else 'INTERNALLY_RECONCILED_PAPER_ONLY'),
                   'admission':'RESEARCH_REVIEW_NOT_APPROVED_PAPER_ORDER',
                   'execution_eligible':False,'real_orders_enabled':False})
    review.pop('content_sha256',None)
    review['content_sha256']=sha256(_canonical(review).encode()).hexdigest()
    return review


def freeze_indicative_review(root, *, session_date: str, review: dict) -> dict:
    """Write-once digest log. A later replay cannot rewrite a prior decision."""
    if review.get('status') not in ('RESEARCH_PLANS_ONLY','NO_RESEARCH_CANDIDATES'):
        raise ValueError('Only qualified-timestamp research reviews can be frozen')
    if review.get('execution_eligible') is not False or review.get('real_orders_enabled') is not False:
        raise ValueError('Execution status cannot be elevated')
    sha=review.get('content_sha256')
    payload=dict(review)
    payload.pop('content_sha256',None)
    if not isinstance(sha,str) or sha!=sha256(_canonical(payload).encode()).hexdigest():
        raise ValueError('Research review digest mismatch')
    identity=sha[:16]
    base=Path(root).resolve()/_PARENT/session_date
    base.mkdir(parents=True,exist_ok=True)
    dest=(base/identity).resolve()
    if not dest.is_relative_to(base):
        raise ValueError('Unsafe plan archive')
    if dest.exists():
        recorded=read_indicative_review(root,session_date,identity)
        if recorded!=review:
            raise ValueError('Archived plan identity conflict')
        return recorded
    with tempfile.TemporaryDirectory(prefix='.writing-',dir=base) as tmp:
        target=Path(tmp)/'review.json'
        target.write_text(json.dumps(review,ensure_ascii=False,
                                    sort_keys=True,indent=2,allow_nan=False),encoding='utf-8')
        Path(tmp).rename(dest)
    return read_indicative_review(root,session_date,identity)


def read_indicative_review(root, session_date: str, identity: str) -> dict:
    if not re.fullmatch(r'\d{4}-\d\d-\d\d',session_date) or not _ID.fullmatch(identity):
        raise ValueError('Unsafe archived plan reference')
    file=Path(root).resolve()/_PARENT/session_date/identity/'review.json'
    if not file.is_file():
        raise FileNotFoundError('Research plan does not exist')
    data=json.loads(file.read_text(encoding='utf-8'))
    digest=data.pop('content_sha256',None)
    if not isinstance(digest,str) or digest[:16]!=identity or sha256(_canonical(data).encode()).hexdigest()!=digest:
        raise ValueError('Archived research plan has been modified')
    data['content_sha256']=digest
    if data.get('execution_eligible') is not False or data.get('real_orders_enabled') is not False:
        raise ValueError('Archive attempts to grant execution eligibility')
    return data



def latest_indicative_reviews(root, *, limit=10) -> dict:
    """Browse immutable, hash-verified research-only plans without paper trades."""
    if type(limit) is not int or not 1<=limit<=30:
        raise ValueError('Review index limit must be 1–30')
    base=Path(root).resolve()/_PARENT
    rows=[]
    if base.is_dir():
        for folder in sorted(base.iterdir(),reverse=True):
            if not folder.is_dir() or not re.fullmatch(r'\d{4}-\d\d-\d\d',folder.name):
                continue
            for child in sorted(folder.iterdir(),reverse=True):
                if not child.is_dir() or not _ID.fullmatch(child.name):
                    continue
                try:
                    review=read_indicative_review(root,folder.name,child.name)
                    rows.append({'session_date_et':folder.name,'identity':child.name,
                                 'status':review['status'],
                                 'research_plan_count':len(review['plans']),
                                 'rejected_count':sum(not x.get('accepted',False)
                                                      for x in review['evaluated']),
                                 'source_forecast_identity':review['source_forecast_identity'],
                                 'source_snapshot_sha256':review['source_snapshot_sha256'],
                                 'account_evidence':review.get('account_evidence'),
                                 'real_orders_enabled':False})
                except (ValueError,KeyError,OSError,TypeError):
                    rows.append({'session_date_et':folder.name,'identity':child.name,
                                 'status':'CORRUPT_RESEARCH_PLAN',
                                 'real_orders_enabled':False})
                if len(rows)>=limit:
                    break
            if len(rows)>=limit:
                break
    return {'status':'RESEARCH_PLANS_ONLY','records':rows,
            'real_orders_enabled':False}
