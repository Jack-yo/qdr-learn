"""Source-hashed H3 follow-up CLI: frozen research plan -> observed future OHLC.

Does not infer a broker fill, does not update a paper ledger, and cannot
manufacture data from current adjusted prices. Requires separately supplied
dated raw bars and receipts; hash integrity alone is not independent attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd

from quant_research.workflow.v4_plan_outcomes import (
    evaluate_research_outcomes, freeze_research_outcomes,
    read_research_outcomes)


_ID=re.compile(r'[0-9a-f]{16}\Z')
_SHA=re.compile(r'[0-9a-f]{64}\Z')


def run_managed_outcome_review(root: Path, *, session_date: str,
                               plan_identity: str) -> dict:
    root=Path(root).resolve()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',session_date) or not _ID.fullmatch(plan_identity):
        raise ValueError('Invalid outcome key')
    try:
        prior=read_research_outcomes(root,session_date,plan_identity)
    except FileNotFoundError:
        prior=None
    if prior:
        return {'status':'OBSERVED_RESEARCH_OUTCOMES_ALREADY_FROZEN',
                'evaluated_trades':len(prior['evaluated']),
                'plan_identity':plan_identity,'session_date_et':session_date,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    folder=(root/'data/managed/v4_outcomes'/session_date/plan_identity).resolve()
    if not folder.is_relative_to((root/'data/managed/v4_outcomes').resolve()):
        raise ValueError('Raw follow-up evidence path escaped project data')
    manifest_file=folder/'manifest.json'
    if not manifest_file.is_file():
        raise FileNotFoundError('Raw follow-up session evidence manifest missing')
    manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
    expected=manifest.get('bars_parquet_sha256')
    if (manifest.get('kind')!='V4_OBSERVED_RAW_BAR_PATH'
            or not isinstance(expected,str) or not _SHA.fullmatch(expected)
            or manifest.get('session_date_et')!=session_date
            or manifest.get('plan_identity')!=plan_identity):
        raise ValueError('Incorrect frozen research outcome source contract')
    bar_file=folder/'bars.parquet'
    if not bar_file.is_file() or sha256(bar_file.read_bytes()).hexdigest()!=expected:
        raise ValueError('Raw outcome bars do not match their manifest digest')
    bars=pd.read_parquet(bar_file)
    result=evaluate_research_outcomes(
        root,session_date,plan_identity,bars,
        observed_at_utc=datetime.now(timezone.utc).isoformat())
    if result['status']!='PROSPECTIVE_RESEARCH_OUTCOME_REVIEW_ONLY':
        return {'status':result['status'],'session_date_et':session_date,
                'plan_identity':plan_identity,'evaluated_trades':0,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    frozen=freeze_research_outcomes(root,result)
    return {'status':'OBSERVED_RESEARCH_OUTCOMES_FROZEN_NO_ORDERS',
            'session_date_et':session_date,'plan_identity':plan_identity,
            'evaluated_trades':len(frozen['evaluated']),
            'content_sha256':frozen['content_sha256'],
            'real_orders_enabled':False,'paper_ledger_advanced':False,
            'warning':'Historical daily-bar stop execution is modeled; not a broker trade'}


def main(argv=None):
    parser=argparse.ArgumentParser(description='V4 modeled outcome follow-up; not a broker trade')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--session-date',required=True)
    parser.add_argument('--plan-id',required=True)
    parser.add_argument('--warehouse',action='store_true',
                        help='Build future raw-bar paths from verified local SIP and no-action receipts')
    args=parser.parse_args(argv)
    try:
        if args.warehouse:
            from quant_research.workflow.v4_warehouse_outcomes import run_warehouse_outcome_review
            result=run_warehouse_outcome_review(
                args.root,session_date=args.session_date,plan_identity=args.plan_id)
        else:
            result=run_managed_outcome_review(
                args.root,session_date=args.session_date,plan_identity=args.plan_id)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        result={'status':'OUTCOME_REVIEW_BLOCKED_NO_ARCHIVE_WRITE',
                'code':getattr(exc,'code',None) or str(exc)[:160] or type(exc).__name__,
                'session_date_et':args.session_date,'plan_identity':args.plan_id,
                'real_orders_enabled':False,'paper_ledger_advanced':False}
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['status'] in ('OBSERVED_RESEARCH_OUTCOMES_FROZEN_NO_ORDERS',
                                     'OBSERVED_RESEARCH_OUTCOMES_ALREADY_FROZEN') else 4


if __name__=='__main__':
    raise SystemExit(main())
