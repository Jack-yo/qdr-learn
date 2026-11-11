"""One-command V4: verified-file input -> H1/H3/H5 model archive -> H3 research risk review.

Never advances PaperLedger. If the prospective window, account, candidate
provenance, or probability calibration is missing, return an explicit blocker.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from quant_research.backtest.paper import account_summary
from quant_research.models.settings import load_settings
from quant_research.workflow.v4_candidate_bridge import (
    freeze_indicative_review, make_indicative_review, read_indicative_review)
from quant_research.workflow.v4_forward_cli import run_managed_forward
from quant_research.workflow.v4_study_cli import _checked_inputs


def run_v4_review_day(root: Path, *, bundle_id: str, asof_session: str) -> dict:
    """Run only research-stage inference and freeze a non-executing decision."""
    root=Path(root).resolve()
    frames,manifest=_checked_inputs(root,bundle_id)
    forward=run_managed_forward(root,bundle_id=bundle_id,asof_session=asof_session)
    status=forward.get('status','BLOCKED')
    safe={'session_date_et':asof_session,
          'source_snapshot_sha256':manifest['source_snapshot_sha256'],
          'forecast_status':status,
          'real_orders_enabled':False,
          'paper_ledger_advanced':False,
          'execution_eligible':False}
    if status not in ('FORWARD_RESEARCH_FROZEN_ONLY','FORWARD_RESEARCH_ALREADY_FROZEN'):
        return {**safe,'status':'NO_PROSPECTIVE_TRADE_PLAN',
                'code':'FORECAST_NOT_PROSPECTIVE_OR_INSUFFICIENT_HISTORY',
                'research_plan_count':0}
    identity=forward['identity']
    # Idempotent: an already frozen plan is never silently revised.
    day_dir=root/'outputs/v4_research_plans'/asof_session
    if day_dir.is_dir():
        for child in sorted(day_dir.iterdir()):
            if not child.is_dir():
                continue
            recorded=read_indicative_review(root,asof_session,child.name)
            if recorded.get('source_forecast_identity')==identity:
                return {**safe,'status':'RESEARCH_PLAN_ALREADY_FROZEN',
                        'plan_identity':child.name,
                        'research_plan_count':len(recorded['plans']),
                        'rejected_count':sum(not x.get('accepted',False)
                                             for x in recorded['evaluated'])}
    if 'candidate_meta' not in frames:
        return {**safe,'status':'RESEARCH_PLAN_BLOCKED',
                'code':'SOURCE_HASHED_CANDIDATE_METADATA_MISSING',
                'research_plan_count':0}
    config=load_settings(root/'configs/experiments/baseline.yaml')
    account=account_summary(root/'data/paper.sqlite3',config)
    if account.get('status')!='INTERNALLY_RECONCILED_PAPER_ESTIMATE':
        return {**safe,'status':'RESEARCH_PLAN_BLOCKED',
                'code':account.get('code','NO_RECONCILED_ACCOUNT'),
                'research_plan_count':0}
    now=datetime.now(timezone.utc).isoformat()
    try:
        review=make_indicative_review(
            root,session_date=asof_session,forecast_identity=identity,
            securities=frames['candidate_meta'],account=account,
            frozen_at_utc=now)
        if review['status'] not in ('RESEARCH_PLANS_ONLY','NO_RESEARCH_CANDIDATES'):
            return {**safe,'status':'RESEARCH_PLAN_BLOCKED',
                    'code':review.get('status','NOT_ELIGIBLE'),
                    'research_plan_count':0}
        frozen=freeze_indicative_review(root,session_date=asof_session,review=review)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {**safe,'status':'RESEARCH_PLAN_BLOCKED',
                'code':str(exc)[:130],'research_plan_count':0}
    return {**safe,'status':'RESEARCH_PLAN_FROZEN_NO_ORDER',
            'plan_identity':frozen['content_sha256'][:16],
            'research_plan_count':len(frozen['plans']),
            'rejected_count':sum(not x.get('accepted',False)
                                 for x in frozen['evaluated'])}


def main(argv=None):
    parser=argparse.ArgumentParser(
        description='V4 close-to-next-open model→research plan, no paper or broker orders')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--bundle-id',required=True)
    parser.add_argument('--asof',required=True)
    args=parser.parse_args(argv)
    result=run_v4_review_day(args.root,bundle_id=args.bundle_id,
                             asof_session=args.asof)
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['status'] in ('RESEARCH_PLAN_FROZEN_NO_ORDER',
                                     'RESEARCH_PLAN_ALREADY_FROZEN') else 4


if __name__=='__main__':
    raise SystemExit(main())
