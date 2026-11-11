"""V4 historical as-of universe structure checks.

Current asset catalogs and backfilled surviving symbols do not establish
historical stock universes. Every exchange session requires a full, dated
source snapshot whose actual observation preceded the signal timestamp.
"""
from __future__ import annotations

import re

import pandas as pd


_UNIVERSE = {'session_date','security_id','symbol','security_type','listed',
             'tradable','observed_at','source_sha256'}
_SESSIONS = {'session_date','capture_finished_at','source_sha256','full_snapshot'}
_SYMBOL = re.compile(r'[A-Z][A-Z0-9.\-]{0,19}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def reconstruct_asof_stock_universe(members: pd.DataFrame,
                                    session_receipts: pd.DataFrame,
                                    exchange_sessions, signal_by_session: dict) -> tuple[pd.DataFrame, dict]:
    """Check known-at-time membership and complete historical session coverage.

    Membership source receipts still need independent raw-hash verification.
    This function does not mint a PIT trading capability.
    """
    if _UNIVERSE - set(members) or _SESSIONS - set(session_receipts):
        raise ValueError('Missing historical universe or source-receipt columns')
    sessions=pd.DatetimeIndex(exchange_sessions)
    if (sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing
            or sessions.tz is not None or len(signal_by_session)!=len(sessions)):
        raise ValueError('Require ordered unique exchange dates with signal times')
    mem=members.copy()
    records=session_receipts.copy()
    mem['session_date']=pd.to_datetime(mem.session_date)
    records['session_date']=pd.to_datetime(records.session_date)
    if (mem.session_date.dt.tz is not None or records.session_date.dt.tz is not None
            or mem.duplicated(['session_date','security_id']).any()
            or records.session_date.duplicated().any()):
        raise ValueError('Ambiguous as-of historical security observations')
    if set(records.session_date)!=set(sessions):
        raise ValueError('Missing entire historical-universe snapshots')
    if not mem.session_date.isin(sessions).all() or set(mem.session_date)!=set(sessions):
        raise ValueError('Every full-session snapshot must include observed security membership')
    for col in ('observed_at',):
        mem[col]=pd.to_datetime(mem[col],utc=True)
    records['capture_finished_at']=pd.to_datetime(records.capture_finished_at,utc=True)
    if (mem.observed_at.isna().any() or records.capture_finished_at.isna().any()
            or not records.full_snapshot.map(lambda x:type(x) is bool or type(x).__name__=='bool').all()
            or not records.full_snapshot.all()):
        raise ValueError('Source must provide complete timestamped membership evidence')
    for source in (mem.source_sha256,records.source_sha256):
        if not source.map(lambda x:isinstance(x,str) and bool(_SHA.fullmatch(x))).all():
            raise ValueError('Invalid raw source digests')
    joined=mem.merge(records,on='session_date',how='left',validate='many_to_one',
                     suffixes=('_row','_session'))
    if not joined.source_sha256_row.eq(joined.source_sha256_session).all():
        raise ValueError('Security rows disagree with their archived full-session snapshot')
    if not joined.observed_at.le(joined.capture_finished_at).all():
        raise ValueError('Membership observations after snapshot completion')
    expected = {pd.Timestamp(day):pd.Timestamp(stamp).tz_convert('UTC')
                for day,stamp in signal_by_session.items()}
    if set(expected)!=set(sessions):
        raise ValueError('Missing known-at-time decision windows')
    joined['signal_time']=joined.session_date.map(expected)
    records['signal_time']=records.session_date.map(expected)
    if (joined.signal_time.isna().any() or not joined.capture_finished_at.le(joined.signal_time).all()
            or not records.capture_finished_at.le(records.signal_time).all()):
        raise ValueError('Historical stock membership was not known by signal cutoff')
    if joined.security_id.isna().any() or joined.symbol.isna().any():
        raise ValueError('Security identities cannot be blank')
    if not joined.symbol.map(lambda x:isinstance(x,str) and bool(_SYMBOL.fullmatch(x))).all():
        raise ValueError('Malformed historical security symbols')
    for col in ('listed','tradable'):
        if not joined[col].map(lambda x:type(x) is bool or type(x).__name__=='bool').all():
            raise ValueError('Membership statuses must be explicit booleans')
    selected=joined.loc[
        joined.security_type.eq('COMMON_STOCK') & joined.listed & joined.tradable
    ].copy()
    if selected.duplicated(['session_date','symbol']).any():
        raise ValueError('Ticker collision among historically active securities')
    return selected[['session_date','security_id','symbol','signal_time',
                     'source_sha256_row']].rename(columns={'source_sha256_row':'source_sha256'}), {
        'status':'HISTORICAL_STRUCTURE_VALID_SOURCE_AUDIT_REQUIRED',
        'requested_sessions':len(sessions),
        'distinct_security_ids':int(selected.security_id.nunique()),
        'qualified_member_rows':int(len(selected)),
        'source_independently_attested':False,
        'research_only':True,'real_orders_enabled':False,
    }
