"""Read-only chronological integrity audit of an actually recorded paper ledger.

This code never posts transactions, imputes missing sessions, fetches market
prices, or reconstructs hypothetical P&L. It checks only what local source-
linked PaperLedger has already persisted and reconciled internally.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3

from quant_research.policy import PolicyError

_SHA = re.compile(r'[0-9a-f]{64}\Z')
_ACCOUNT = 'forward-shadow-h3'
_LIMIT = 100


def _blocked(code, **extra):
    return {'status':'BLOCKED', 'code':code, 'sessions':[], 'recorded_sessions':0,
            'real_orders_enabled':False,'externally_verified_fills':False,**extra}


def _money(v):
    return isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)


def paper_timeline(root, *, limit=20):
    """Inspect a local, genuine source-linked paper account and its days/events.

    Returns BLOCKED if any ledger row is unverifiable. This is not an external
    broker reconciliation, even when the local cash/state accounting balances.
    """
    if type(limit) is not int or not 1 <= limit <= _LIMIT:
        raise PolicyError('PAPER_TIMELINE_QUERY_INVALID','Timeline limit must be 1–100')
    root = Path(root).resolve()
    path = root/'data/paper.sqlite3'
    config_file = root/'configs/experiments/baseline.yaml'
    if not path.is_file() or not config_file.is_file():
        return _blocked('NO_ACCEPTED_PAPER_LEDGER')
    from quant_research.backtest.paper import account_summary
    from quant_research.models.settings import load_settings
    settings=load_settings(config_file)
    summary=account_summary(path,settings,account=_ACCOUNT)
    if summary.get('status')!='INTERNALLY_RECONCILED_PAPER_ESTIMATE':
        return _blocked(summary.get('code','PAPER_ACCOUNT_NOT_RECONCILED'))
    try:
        uri=path.resolve().as_uri()+'?mode=ro'
        with sqlite3.connect(uri,uri=True) as db:
            days=db.execute('''SELECT date,input_hash,source_snapshot_sha256,decision_sha256,snapshot_json
                FROM days WHERE account=? ORDER BY date ASC''',[_ACCOUNT]).fetchall()
            events=db.execute('''SELECT date,kind,event_id,cash_change,body_json
                FROM events WHERE account=? ORDER BY date ASC,rowid ASC''',[_ACCOUNT]).fetchall()
    except (sqlite3.Error,OSError):
        return _blocked('PAPER_TIMELINE_DB_UNREADABLE')
    if not days or len(days)>10000:
        return _blocked('PAPER_TIMELINE_SESSION_COUNT_INVALID')
    from quant_research.clock import TradingClock
    clock=TradingClock()
    event_by_day={}
    for day,kind,event_id,cash_change,encoded in events:
        event_by_day.setdefault(day,[]).append((kind,event_id,cash_change,encoded))
    if set(event_by_day)-{d[0] for d in days}:
        return _blocked('PAPER_TIMELINE_ORPHAN_EVENTS')
    running_cash=float(settings.initial_cash)
    previous=None
    records=[]
    try:
        for day,input_sha,source_sha,decision_sha,encoded in days:
            clock.session(day)
            if previous and str(clock.calendar.next_session(previous).date())!=day:
                raise PolicyError('PAPER_TIMELINE_MISSING_SESSION','Paper account cannot skip exchange sessions')
            if not all(isinstance(v,str) and _SHA.fullmatch(v) for v in (input_sha,source_sha,decision_sha)):
                raise PolicyError('PAPER_TIMELINE_PROVENANCE_MISSING','Paper day lacks data, input or decision SHA256')
            payload=json.loads(encoded)
            if not isinstance(payload,dict) or payload.get('date')!=day:
                raise PolicyError('PAPER_TIMELINE_DAY_INVALID','Ledger snapshot does not match its session')
            if not all(_money(payload.get(k)) for k in ('cash','equity')):
                raise PolicyError('PAPER_TIMELINE_AMOUNTS_INVALID','Cannot inspect nonfinite portfolio values')
            if not isinstance(payload.get('positions'),dict) or not isinstance(payload.get('new_fills'),list):
                raise PolicyError('PAPER_TIMELINE_SNAPSHOT_INVALID','Missing persisted position/fill observations')
            cumulative_events=event_by_day.get(day,[])
            counters={'fill':0,'action':0}
            for kind,event_id,cash_change,body in cumulative_events:
                if kind not in counters or not _money(cash_change):
                    raise PolicyError('PAPER_TIMELINE_EVENT_INVALID','Unexpected paper account ledger event')
                expected_id=sha256(f'{_ACCOUNT}:{day}:{kind}:{counters[kind]}'.encode()).hexdigest()
                counters[kind]+=1
                if event_id!=expected_id:
                    raise PolicyError('PAPER_TIMELINE_EVENT_SEQUENCE_INVALID','Event ID differs from the actual ledger sequence')
                original=json.loads(body)
                if not isinstance(original,dict) or not _money(original.get('cash_change')) or abs(original['cash_change']-cash_change)>1e-6:
                    raise PolicyError('PAPER_TIMELINE_CASH_EVENT_MISMATCH','Event details disagree with recorded cash movement')
                running_cash+=cash_change
            if counters['fill']!=len(payload['new_fills']):
                raise PolicyError('PAPER_TIMELINE_FILL_COUNT_INVALID','Snapshot fills and durable fill entries do not reconcile')
            if abs(running_cash-payload['cash'])>1e-6:
                raise PolicyError('PAPER_TIMELINE_CASH_MISMATCH','Per-session cash does not reconcile with recorded events')
            records.append({'session_date_et':day,'cash':payload['cash'],'equity':payload['equity'],
                'positions':len(payload['positions']),'new_modeled_fills':counters['fill'],
                'corporate_action_entries':counters['action'],
                'source_snapshot_sha256':source_sha,'decision_sha256':decision_sha,
                'input_hash':input_sha})
            previous=day
    except (PolicyError,ValueError,KeyError,TypeError,sqlite3.Error,OverflowError) as error:
        return _blocked(error.code if isinstance(error,PolicyError) else 'PAPER_TIMELINE_UNVERIFIABLE')
    if (records[-1]['session_date_et']!=summary['last_session'] or
            abs(records[-1]['cash']-summary['cash'])>1e-6 or
            abs(records[-1]['equity']-summary['equity'])>1e-6):
        return _blocked('PAPER_TIMELINE_LAST_STATE_MISMATCH')
    return {'status':'INTERNALLY_RECONCILED_PAPER_ESTIMATE',
            'account':_ACCOUNT,'recorded_sessions':len(records),
            'latest_session':records[-1]['session_date_et'],
            'sessions':records[-limit:], 'shown_sessions':min(limit,len(records)),
            'real_orders_enabled':False,'externally_verified_fills':False,
            'source_receipts_rechecked_by_timeline':False,
            'notice':'Internal ledger sequence and cash verified. Historical raw-source and broker fills are not independently reverified here.'}
