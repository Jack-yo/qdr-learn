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
            from quant_research.workflow.styles import calculate
            _history,latest,_corr,meta=calculate(root,asof=day)
            return {'status':'RESEARCH_ONLY','code':'CLASSIC_FACTOR_OBSERVATION',
                    'detail':{'asof_date_et':meta.get('asof_date_et'),
                              'observed_factors':len(latest)}}
        except (OSError,ValueError,KeyError) as exc:
            return {'status':'BLOCKED','code':type(exc).__name__}

    def alpha(day,history):
        from quant_research.research.v4_artifacts import list_research_runs
        rows=list_research_runs(root,limit=20)
        actual=[r for r in rows if r.get('status')=='VERIFIED_LOCAL_RESEARCH_ARTIFACT_ONLY']
        if not actual:
            return {'status':'BLOCKED','code':'NO_V4_OOS_RESEARCH_ARCHIVE'}
        return {'status':'RESEARCH_ONLY','code':'OOS_ARCHIVE_NOT_EXECUTION_APPROVED',
                'detail':{'available_research_runs':len(actual),
                          'latest_run_id':actual[0]['run_id']}}

    def risk(day,history):
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


def run_observed_v4_daily(root: Path, session_date: str) -> dict:
    root=Path(root).resolve()
    readiness=research_readiness(root,asof=session_date)
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


def main(argv=None):
    parser=argparse.ArgumentParser(description='Source-observed V4 daily research diary (not a trade runner)')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--date',required=True,help='Completed XNYS session YYYY-MM-DD')
    args=parser.parse_args(argv)
    result=run_observed_v4_daily(args.root,args.date)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['status']=='STAGES_COMPLETE_ADMISSION_PENDING' else 4


if __name__=='__main__':
    raise SystemExit(main())
