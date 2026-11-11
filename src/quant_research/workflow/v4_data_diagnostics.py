"""Read-only V4 warehouse source inventory, never an eligibility approval.

Counts and schema shape cannot prove PIT identities, provider lineage, trade
costs, or alpha. This command only reports missing pieces for local testing.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re

EXPECTED={
    'prices_daily':{'security_id','symbol','date','open','high','low','close','volume',
                    'available_at','raw_sha256','adjustment_basis','source','feed'},
    'price_observations':{'security_id','date','available_at','raw_sha256'},
    'features_daily':{'date','security_id','feature_name','available_at','decision_eligible'},
    'labels':{'date','security_id','horizon','label_kind','forward_return',
              'benchmark_return','available_at'},
    'universe_daily':{'date','security_id','is_eligible','available_at','quality_flag'},
    'action_coverage_daily':{'date','security_id','quality_flag','available_at'},
    'corporate_actions':{'security_id','ex_date','action_type','available_at'},
    'sector_classification_pit':{'security_id','sector','available_at','source_sha256'},
}


def _columns(db,table):
    try:
        return {r[1] for r in db.execute(f"PRAGMA table_info('{table}')").fetchall()}
    except Exception:
        return set()


def _count(db,query,params=()):
    try:
        return int(db.execute(query,list(params)).fetchone()[0])
    except Exception:
        return None


def inspect_v4_warehouse(connection, *, asof: str, symbols: list[str]) -> dict:
    """Read-only structural and dated-row inventory against the source schema."""
    try:
        if not re.fullmatch(r'\d{4}-\d\d-\d\d',asof) or date.fromisoformat(asof).isoformat()!=asof:
            raise ValueError('Invalid as-of session')
    except (TypeError,ValueError):
        raise ValueError('Invalid as-of session') from None
    if (not isinstance(symbols,list) or not symbols
            or len(set(symbols))!=len(symbols)
            or any(not isinstance(x,str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,19}',x)
                   for x in symbols)):
        raise ValueError('Require unique uppercase source symbols')
    tables={}
    for name,required in EXPECTED.items():
        columns=_columns(connection,name)
        missing=sorted(required-columns)
        tables[name]={'status':('PRESENT_FOR_REVIEW' if columns and not missing
                                 else 'MISSING_TABLE' if not columns
                                 else 'MISSING_REQUIRED_COLUMNS'),
                      'missing_columns':missing}
    def exists(name):
        return tables[name]['status']=='PRESENT_FOR_REVIEW'
    checks=[]
    def check(code,table,sql=None,params=(),*,minimum=1,description=''):
        if not exists(table):
            checks.append({'code':code,'status':'BLOCKED','rows':None,
                           'reason':f'{table} missing required columns or table'})
            return
        rows=_count(connection,sql,params) if sql else None
        good=rows is not None and rows>=minimum
        checks.append({'code':code,'status':'OBSERVED_FOR_REVIEW' if good else 'BLOCKED',
                       'rows':rows,
                       'reason':description if good
                       else 'Insufficient dated observations or incompatible table'})
    placeholders=','.join('?' for _ in symbols)
    check('RAW_SIP_ASOF','prices_daily',
          f"""SELECT count(distinct symbol) FROM prices_daily
          WHERE date=? AND source='ALPACA' AND feed='sip' AND adjustment_basis='raw'
          AND symbol IN ({placeholders})""",
          [asof,*symbols],minimum=len(symbols),
          description='Raw SIP observations exist; source receipts need independent audit')
    check('PRICE_RECEIPTS_ASOF','price_observations',
          'SELECT count(distinct security_id) FROM price_observations WHERE date=?',
          [asof],minimum=len(symbols),description='Receipt rows exist; verify raw response lineage')
    check('KNOWN_ASOF_FACTORS','features_daily',
          'SELECT count(distinct security_id) FROM features_daily WHERE date=? AND decision_eligible=true',
          [asof],description='Eligible feature rows observed, not independently verified PIT')
    check('VERIFIED_RAW_HISTORICAL_LABELS','labels',
          "SELECT count(distinct date) FROM labels WHERE date<? AND label_kind='VERIFIED_RAW_TRADE_TOTAL_RETURN'",
          [asof],minimum=60,
          description='Declared raw historical labels exist; confirm corporate-action evidence')
    check('UNKNOWN_FUTURE_LABELS','labels',
          "SELECT count(distinct horizon) FROM labels WHERE date=? AND label_kind='FUTURE_UNOBSERVED'",
          [asof],minimum=3,description='H1/H3/H5 current-day future outcomes explicitly unknown')
    check('HISTORICAL_UNIVERSE','universe_daily',
          'SELECT count(distinct date) FROM universe_daily WHERE date<=? AND is_eligible=true',
          [asof],minimum=60,description='Membership rows exist; PIT identity still needs audit')
    check('ACTION_COVERAGE','action_coverage_daily',
          'SELECT count(distinct security_id) FROM action_coverage_daily WHERE date=?',
          [asof],minimum=len(symbols),
          description='Action coverage rows exist; check status and completeness')
    check('SECTOR_CLASSIFICATION','sector_classification_pit',
          'SELECT count(distinct security_id) FROM sector_classification_pit WHERE available_at IS NOT NULL',
          minimum=1,description='Dated sector records exist, PIT provenance still unverified')
    return {'status':'DATA_CONTRACT_INVENTORY_ONLY','asof_session':asof,
            'requested_symbols':symbols,'tables':tables,'checks':checks,
            'blocked_checks':sum(r['status']=='BLOCKED' for r in checks),
            'next_action':'Resolve blocked checks, then independently verify source lineage and V4 preflight',
            'source_independently_attested':False,'historical_pit_attested':False,
            'execution_eligible':False,'real_orders_enabled':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only local V4 source diagnostic')
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--asof',required=True)
    parser.add_argument('--symbols',required=True,help='Comma-separated research source symbols')
    args=parser.parse_args(argv)
    if not args.db.is_file():
        parser.error('Local DuckDB warehouse does not exist')
    import duckdb
    with duckdb.connect(str(args.db),read_only=True) as db:
        output=inspect_v4_warehouse(db,asof=args.asof,symbols=args.symbols.split(','))
    print(json.dumps(output,ensure_ascii=False,indent=2))
    return 0 if output['blocked_checks']==0 else 4


if __name__=='__main__':
    raise SystemExit(main())
