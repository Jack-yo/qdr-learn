"""Runnable V4 read-only daily observation orchestration.

Uses only currently archived real-source observations; does not fetch prices,
create fitted models, grant historical PIT, or place paper/broker trades.
The actual V4 model research runner is an independent source-gated workflow.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import yaml

from quant_research.workflow.v4_daily import run_v4_daily
from quant_research.workflow.research_readiness import research_readiness


def observed_v4_adapters(root: Path, readiness: dict):
    """Build server-side stage functions; no user-supplied eligibility flags."""
    stage=readiness.get('stages') or {}

    def data(day,history):
        item=stage.get('dataset') or {}
        evidence=item.get('evidence') or {}
        if item.get('status')!='OBSERVATION_ONLY' or evidence.get('asof_date_et')!=day:
            return {'status':'BLOCKED','code':'NO_ACCEPTED_CURRENT_SESSION_SOURCE'}
        return {'status':'RESEARCH_ONLY','code':'SOURCE_OBSERVATION_NOT_PIT_MODEL',
                'detail':{'date':day,'source':evidence.get('source'),
                          'rows':evidence.get('rows')}}

    def market(day,history):
        # Current historical-regime web research is not an attested forward
        # probability archive; do not promote it to model PASS.
        return {'status':'BLOCKED','code':'NO_APPROVED_V4_MARKET_PREDICTIONS'}

    def styles(day,history):
        try:
            from quant_research.workflow.l2_downstream import build_downstream_context
            context=build_downstream_context(root,asof=day)
            detail={
                'asof_date_et':context.get('asof_session') or day,
                'l2_status':context.get('status'),
                'l2_code':context.get('code'),
                'admitted_units':context.get('admitted_units',0),
                'l3_style_context_available':context.get('l3_style_context_available',False),
                'model_version':context.get('model_version'),
                'label_bundle_id':context.get('label_bundle_id'),
            }
            # French factors remain a separate descriptive stream. Their
            # availability never upgrades or downgrades L2 model qualification.
            try:
                from quant_research.workflow.styles import calculate as calculate_french
                _history,latest,_corr,meta=calculate_french(root,asof=day)
                detail['classic_french_observation']={
                    'status':'OBSERVATION_ONLY',
                    'asof_date_et':meta.get('asof_date_et'),
                    'observed_factors':len(latest),
                }
            except (OSError,ValueError,KeyError,TypeError):
                detail['classic_french_observation']={'status':'UNAVAILABLE'}

            if context.get('status')=='BLOCKED':
                return {'status':'BLOCKED',
                        'code':context.get('code','L2_DOWNSTREAM_CONTEXT_BLOCKED'),
                        'detail':detail}
            if context.get('status')=='MODEL_ADMITTED_CONTEXT':
                return {'status':'PASS','code':'L2_MODEL_ADMITTED_CONTEXT',
                        'detail':detail}
            return {'status':'RESEARCH_ONLY',
                    'code':context.get('code','L2_STYLE_RESEARCH_ONLY'),
                    'detail':detail}
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {'status':'BLOCKED','code':type(exc).__name__}

    def alpha(day,history):
        from quant_research.research.v4_forecast_archive import latest_forward_research
        from quant_research.research.v4_artifacts import list_research_runs
        expected=(stage.get('dataset') or {}).get('evidence',{}).get('source_snapshot_sha256')
        frozen=latest_forward_research(root,limit=20)
        matching=[x for x in frozen if x.get('session_date_et')==day
                  and x.get('source_snapshot_sha256')==expected
                  and x.get('status')=='VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY']
        if matching:
            return {'status':'RESEARCH_ONLY','code':'PROSPECTIVE_ALPHA_RESEARCH_FROZEN',
                    'detail':{'session_date_et':day,'forecast_identity':matching[0]['identity'],
                              'forecast_rows':matching[0]['forecast_rows'],
                              'paper_admission':False}}
        rows=list_research_runs(root,limit=20)
        actual=[r for r in rows if r.get('status')=='VERIFIED_LOCAL_RESEARCH_ARTIFACT_ONLY']
        if not actual:
            return {'status':'BLOCKED','code':'NO_DATED_V4_ALPHA_PREDICTION'}
        return {'status':'RESEARCH_ONLY','code':'OOS_RESEARCH_ONLY_NO_CURRENT_FORECAST',
                'detail':{'available_research_runs':len(actual),
                          'latest_run_id':actual[0]['run_id']}}

    def risk(day,history):
        from quant_research.workflow.v4_candidate_bridge import latest_indicative_reviews
        reviewed=latest_indicative_reviews(root,limit=20)
        source=(stage.get('dataset') or {}).get('evidence',{}).get('source_snapshot_sha256')
        latest=[x for x in reviewed['records'] if x.get('session_date_et')==day
                and x.get('source_snapshot_sha256')==source
                and x.get('status')!='CORRUPT_RESEARCH_PLAN']
        if latest:
            return {'status':'RESEARCH_ONLY','code':'INDICATIVE_RISK_PLANS_NO_PAPER_EXECUTION',
                    'detail':{'session_date_et':day,'research_plan_count':latest[0]['research_plan_count'],
                              'plan_identity':latest[0]['identity'],
                              'real_orders_enabled':False}}
        from quant_research.backtest.paper import account_summary
        from quant_research.models.settings import load_settings
        from quant_research.risk.portfolio import RiskPolicy,assess_paper_concentration
        config=load_settings(root/'configs/experiments/baseline.yaml')
        account=account_summary(root/'data/paper.sqlite3',config)
        result=assess_paper_concentration(account,RiskPolicy(
            max_stock_weight=config.max_stock_weight,
            max_sector_weight=config.max_sector_weight,
            max_gross_weight=config.max_total_weight))
        if result.get('status')!='CONCENTRATION_MEASURED':
            return {'status':'BLOCKED','code':result.get('code','PAPER_RISK_UNAVAILABLE')}
        return {'status':'RESEARCH_ONLY','code':'INTERNAL_PAPER_RISK_OBSERVATION',
                'detail':{'risk_alerts':len(result['alerts']),
                          'last_session':result.get('last_session')}}

    def freeze(day,history):
        return {'status':'BLOCKED','code':'V4_MODEL_AND_DATA_ADMISSION_NOT_ESTABLISHED'}

    return {'data':data,'market':market,'styles':styles,
            'alpha':alpha,'risk':risk,'freeze':freeze}


def run_observed_v4_daily(root: Path, session_date: str, *, symbols=None) -> dict:
    root=Path(root).resolve()
    readiness=(research_readiness(root,asof=session_date,symbols=symbols)
               if symbols is not None else research_readiness(root,asof=session_date))
    evidence=(readiness.get('stages') or {}).get('dataset',{}).get('evidence') or {}
    snapshot=evidence.get('source_snapshot_sha256')
    if not snapshot:
        return {'status':'BLOCKED','code':'NO_SOURCE_ATTESTED_DAILY_SNAPSHOT',
                'session_date_et':session_date,'real_orders_enabled':False}
    config=root/'configs/experiments/v4_research.yaml'
    if not config.is_file():
        return {'status':'BLOCKED','code':'V4_RESEARCH_CONFIG_MISSING',
                'session_date_et':session_date,'real_orders_enabled':False}
    parsed=yaml.safe_load(config.read_text(encoding='utf-8'))
    from quant_research.models.v4_oos import OOSProtocol
    OOSProtocol(**parsed['oos'])
    return run_v4_daily(root,session_date,source_snapshot_sha256=snapshot,
                        protocol_sha256=sha256(config.read_bytes()).hexdigest(),
                        adapters=observed_v4_adapters(root,readiness))


def run_v4_pipeline_day(root: Path, session_date: str, *,
                        bundle_id: str, research_budget: float | None = None) -> dict:
    """Single research command. Model inference + indicative plans + daily diary.

    Source/ledger qualification is never inferred from a model's own hash.
    The two independently recorded outputs are joined only when their real
    raw source snapshot digest matches.
    """
    from quant_research.workflow.v4_review_cli import run_v4_review_day
    from quant_research.workflow.v4_pipeline_preflight import preflight_v4_day
    from quant_research.policy import PolicyError
    root=Path(root).resolve()
    # Validate the exchange window and independently observed warehouse source
    # BEFORE run_managed_forward can create an immutable model archive.
    try:
        admitted=preflight_v4_day(root,session_date,bundle_id)
    except (PolicyError,OSError,ValueError,KeyError,TypeError) as exc:
        return {'status':'PREFLIGHT_BLOCKED_NO_ARCHIVE_WRITE',
                'code':getattr(exc,'code',None) or str(exc)[:160] or type(exc).__name__,
                'session_date_et':session_date,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    try:
        from quant_research.workflow.l3_daily import freeze_l3_daily
        l3_alpha=freeze_l3_daily(
            root,session_date=session_date,bundle_id=bundle_id,admitted=admitted)
    except (PolicyError,OSError,ValueError,KeyError,TypeError,FileNotFoundError) as exc:
        l3_alpha={'status':'L3_DAILY_ALPHA_NOT_FROZEN',
                  'code':getattr(exc,'code',None) or str(exc)[:160] or type(exc).__name__,
                  'session_date_et':session_date,
                  'real_orders_enabled':False}
    try:
        plan=run_v4_review_day(root,bundle_id=bundle_id,asof_session=session_date,
                               research_budget=research_budget)
    except (OSError,ValueError,TypeError,KeyError,FileNotFoundError) as exc:
        plan={'status':'RESEARCH_PLAN_BLOCKED',
              'code':type(exc).__name__,
              'session_date_et':session_date,
              'real_orders_enabled':False}
    # Never freeze a successful-looking daily diary if the forecast/plan
    # failed, changed source, or omitted its source receipt.
    if plan.get('status') not in ('RESEARCH_PLAN_FROZEN_NO_ORDER',
                                 'RESEARCH_PLAN_ALREADY_FROZEN'):
        return {'status':'RESEARCH_PLAN_BLOCKED_BEFORE_DAILY_FREEZE',
                'code':plan.get('code') or plan.get('status') or 'PLAN_NOT_ACCEPTED',
                'session_date_et':session_date,'research_plan':plan,
                'l3_alpha':l3_alpha,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if not plan.get('source_snapshot_sha256'):
        return {'status':'PLAN_SOURCE_NOT_VERIFIED',
                'code':'RESEARCH_PLAN_HAS_NO_SOURCE_DIGEST',
                'session_date_et':session_date,'research_plan':plan,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if plan['source_snapshot_sha256']!=admitted['source_snapshot_sha256']:
        return {'status':'SOURCE_SNAPSHOT_MISMATCH',
                'code':'POST_ADMISSION_PLAN_SOURCE_CHANGED',
                'session_date_et':session_date,'research_plan':plan,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    # Re-check the mutable warehouse AFTER expensive model fitting and risk
    # freezing but BEFORE the write-once daily diary. The source may have
    # changed since preflight; never bind such a diary to stale provenance.
    source_now=research_readiness(
        root,asof=session_date,symbols=admitted['source_symbols'])
    dataset=(source_now.get('stages') or {}).get('dataset') or {}
    evidence=dataset.get('evidence') or {}
    if (dataset.get('status')!='OBSERVATION_ONLY'
            or evidence.get('asof_date_et')!=session_date
            or evidence.get('symbols')!=admitted['source_symbols']
            or evidence.get('latest_session_complete') is not True
            or evidence.get('source_snapshot_sha256')!=admitted['source_snapshot_sha256']):
        return {'status':'SOURCE_SNAPSHOT_MISMATCH',
                'code':'POST_MODEL_WAREHOUSE_SOURCE_CHANGED_BEFORE_DAILY_FREEZE',
                'session_date_et':session_date,'research_plan':plan,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    diary=run_observed_v4_daily(root,session_date,
                                 symbols=admitted['source_symbols'])
    source=diary.get('source_snapshot_sha256')
    if not source:
        return {'status':'DAILY_SOURCE_NOT_VERIFIED',
                'code':'DAILY_DIARY_HAS_NO_VERIFIABLE_SOURCE_DIGEST',
                'session_date_et':session_date,'research_plan':plan,
                'daily_diary_status':diary.get('status'),
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if plan.get('source_snapshot_sha256') and plan['source_snapshot_sha256']!=admitted['source_snapshot_sha256']:
        return {'status':'SOURCE_SNAPSHOT_MISMATCH','code':'POST_ADMISSION_PLAN_SOURCE_CHANGED',
                'session_date_et':session_date,'research_plan':plan,
                'daily_diary_status':diary.get('status'),
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if source and source!=admitted['source_snapshot_sha256']:
        return {'status':'SOURCE_SNAPSHOT_MISMATCH','code':'POST_ADMISSION_WAREHOUSE_SOURCE_CHANGED',
                'session_date_et':session_date,'research_plan':plan,
                'daily_diary_status':diary.get('status'),
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if source and plan.get('source_snapshot_sha256') and source!=plan['source_snapshot_sha256']:
        return {'status':'SOURCE_SNAPSHOT_MISMATCH',
                'code':'FORECAST_SOURCE_DIFFERS_FROM_DAILY_WAREHOUSE',
                'session_date_et':session_date,
                'research_plan':plan,'daily_diary_status':diary.get('status'),
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    if not plan.get('source_snapshot_sha256'):
        return {'status':'PLAN_SOURCE_NOT_VERIFIED',
                'code':'RESEARCH_PLAN_HAS_NO_SOURCE_DIGEST',
                'session_date_et':session_date,'research_plan':plan,
                'daily_diary_status':diary.get('status'),
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    plan_ok=plan.get('status') in ('RESEARCH_PLAN_FROZEN_NO_ORDER',
                                   'RESEARCH_PLAN_ALREADY_FROZEN')
    diary_ok=diary.get('status') in ('RESEARCH_UPDATED_NO_TRADE',
                                      'STAGES_COMPLETE_ADMISSION_PENDING')
    return {'status':('RESEARCH_PLAN_AND_DIARY_SAVED' if plan_ok and diary_ok
                      else 'RESEARCH_PLAN_SAVED_DAILY_DATA_UNVERIFIED' if plan_ok
                      else 'RESEARCH_ONLY_PARTIALLY_BLOCKED'),
            'session_date_et':session_date,
            'l3_alpha':l3_alpha,
            'research_plan':plan,
            'daily_diary':diary,
            'real_orders_enabled':False,
            'paper_ledger_advanced':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Source-observed V4 daily research diary (not a trade runner)')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--date',required=True,help='Completed XNYS session YYYY-MM-DD')
    parser.add_argument('--bundle-id',default=None,
                        help='Optional strict source-hashed Alpha input bundle for full research review')
    parser.add_argument('--research-budget',type=float,default=None,
                        help='Explicit cash-only research scenario, not an actual paper account')
    parser.add_argument('--preflight-only',action='store_true',
                        help='Validate current T-day source/time/cohort without writing a forecast or daily diary')
    args=parser.parse_args(argv)
    if args.research_budget is not None and args.bundle_id is None:
        parser.error('--research-budget requires --bundle-id')
    if args.preflight_only and not args.bundle_id:
        parser.error('--preflight-only requires --bundle-id')
    if args.preflight_only:
        from quant_research.workflow.v4_pipeline_preflight import preflight_v4_day
        try:
            result=preflight_v4_day(args.root,args.date,args.bundle_id)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            result={'status':'PREFLIGHT_BLOCKED_NO_ARCHIVE_WRITE',
                    'code':getattr(exc,'code',None) or str(exc)[:160] or type(exc).__name__,
                    'session_date_et':args.date,'real_orders_enabled':False,
                    'paper_ledger_advanced':False}
    else:
        result=(run_v4_pipeline_day(args.root,args.date,bundle_id=args.bundle_id,
                                    research_budget=args.research_budget)
                if args.bundle_id else run_observed_v4_daily(args.root,args.date))
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['status'] in ('PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY',
                                      'RESEARCH_UPDATED_NO_TRADE',
                                      'STAGES_COMPLETE_ADMISSION_PENDING',
                                      'RESEARCH_PLAN_AND_DIARY_SAVED') else 4


if __name__=='__main__':
    raise SystemExit(main())
