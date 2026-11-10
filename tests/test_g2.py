"""Real cached events, plus literal scalar accounting arithmetic; no invented market records."""
from decimal import Decimal
from pathlib import Path
import hashlib
import json

import pytest

from quant_research.backtest.action_accounting import ActionAccounting
from quant_research.data.http import HttpCache,DataUnavailable
from quant_research.data.providers.actions import ActionProvider
from quant_research.policy import PolicyError


def real_events(symbols,start,end):
    try:return ActionProvider(HttpCache(Path('data/raw'),offline=True),limit=1).events(symbols,start,end)
    except (DataUnavailable,FileNotFoundError) as exc:pytest.skip('BLOCKED_REAL_ACTION_SNAPSHOT: '+str(exc))


def test_split_scalar_arithmetic_is_idempotent_without_cash_profit():
    event=next(e for e in real_events(['AAPL'],'2020-08-01','2020-09-30') if e['event_type']=='forward_splits')
    # Literal arithmetic inputs, not an asserted historical position or trade.
    book=ActionAccounting('AAPL',shares=8,cash=100)
    assert book.apply(event,'2020-08-31')
    assert book.shares==32 and book.cash==100
    assert not book.apply(event,'2020-08-31')
    assert sum(j['share_delta'] for j in book.journal)==24


def test_dividend_receivable_survives_sale_and_pays_only_on_pay_date():
    event=next(e for e in real_events(['AAPL'],'2020-08-01','2020-09-30') if e['event_type']=='cash_dividends')
    book=ActionAccounting('AAPL',shares=10,cash=100)
    assert book.apply(event,'2020-08-07')
    assert book.cash==100 and sum(book.receivables.values())==Decimal('8.20')
    assert not book.apply(event,'2020-08-07')
    book.shares=Decimal(0)  # Scalar state change: no fictitious sale price/fill.
    with pytest.raises(ValueError):book.apply(event,'2020-08-12')
    assert book.cash==100
    assert book.apply(event,'2020-08-13')
    assert book.cash==Decimal('108.20') and not book.receivables
    assert not book.apply(event,'2020-08-13')
    assert sum(j['receivable_delta'] for j in book.journal)==0


def test_payment_without_entitlement_and_wrong_identity_blocked():
    event=next(e for e in real_events(['AAPL'],'2020-08-01','2020-09-30') if e['event_type']=='cash_dividends')
    with pytest.raises(PolicyError,match='entitlement'):ActionAccounting('AAPL').apply(event,'2020-08-13')
    with pytest.raises(PolicyError,match='different security'):ActionAccounting('GE').apply(event,'2020-08-07')


def test_real_reverse_split_and_fractional_settlement_block():
    event=next(e for e in real_events(['GE'],'2021-07-01','2021-08-31') if e['event_type']=='reverse_splits')
    book=ActionAccounting('GE',shares=16,cash=100)
    book.apply(event,'2021-08-02')
    assert book.shares==2 and book.cash==100
    fractional=ActionAccounting('GE',shares=1,cash=100)
    with pytest.raises(PolicyError,match='Fractional'):fractional.apply(event,'2021-08-02')
    assert fractional.shares==1 and not fractional.journal


def test_real_ge_duplicate_cusip_dividend_must_not_double_credit():
    events=[e for e in real_events(['GE'],'2021-07-01','2021-08-31') if e['event_type']=='cash_dividends']
    assert len(events)==2 and len({e['payload']['cusip'] for e in events})==2
    book=ActionAccounting('GE',shares=10)
    book.apply(events[0],events[0]['payload']['ex_date'])
    before=dict(book.receivables)
    with pytest.raises(PolicyError,match='duplicate'):book.apply(events[1],events[1]['payload']['ex_date'])
    assert book.receivables==before and book.cash==0


def test_real_event_storage_replay_no_duplicates(tmp_path):
    from quant_research.data.event_store import put_events
    events=real_events(['AAPL'],'2020-08-01','2020-09-30')
    target=tmp_path/'events.duckdb'
    assert put_events(target,events)==2
    assert put_events(target,events)==0
    for e in events:
        raw=(Path('data/raw/objects')/e['raw_sha256']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==e['raw_sha256']
        assert e['published_at_utc'] is None


def test_cash_merger_never_uses_zero_or_last_price_fallback():
    events=real_events(['TWTR'],'2022-10-01','2022-11-30')
    book=ActionAccounting(events[0]['symbol'],shares=10)
    with pytest.raises(PolicyError,match='Unsupported'):book.apply(events[0],'2022-10-28')
    assert book.cash==0 and book.shares==10


def test_official_field_matches_and_duplicate_identity_detection():
    from quant_research.data.event_review import review
    manifests=list(Path('outputs/g2').glob('*/manifest.json'))
    if not manifests:pytest.skip('BLOCKED_OFFICIAL_SOURCE_SNAPSHOT_UNAVAILABLE')
    manifest=json.loads(manifests[0].read_text(encoding='utf-8'))
    events=real_events(['AAPL'],'2020-08-01','2020-09-30')+real_events(['GE'],'2021-07-01','2021-08-31')+real_events(['FB','META'],'2022-05-01','2022-07-31')
    result=review(events,manifest['external_sources'],Path('data/raw'))
    assert sum(c['status']=='CASE_FIELDS_MATCH' for c in result['case_checks'])==4
    assert len(result['identity_collisions'])==1
    assert not any(c['execution_accepted'] for c in result['case_checks'])


def test_payload_mutation_rejected_by_real_source_hash():
    from copy import deepcopy
    from quant_research.data.event_store import verify_event
    event=deepcopy(real_events(['AAPL'],'2020-08-01','2020-09-30')[0])
    event['payload']['rate']='REJECTED_MUTATION'  # Fault injection, no fabricated market dataset.
    with pytest.raises(ValueError,match='does not match'):verify_event(event,Path('data/raw'))
