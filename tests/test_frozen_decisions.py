"""Protocol and failure-closure tests; no historical market bars or profits generated."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from quant_research.policy import PolicyError
from quant_research.workflow.frozen_decisions import (
    _artifact, _candidate_rows, _session, _utc, inspect_frozen_decision,
)


def test_no_local_warehouse_returns_empty_blocked_and_writes_nothing(tmp_path):
    out=inspect_frozen_decision(tmp_path)
    assert out['status']=='BLOCKED' and out['code']=='NO_REAL_DATA'
    assert out['candidates']==[] and not out['execution_ready']
    assert out['real_orders_enabled'] is False
    assert not (tmp_path/'data').exists()


@pytest.mark.parametrize('bad',["2026-11-32", "2099-01-01", "2026-11-10T00:00:00Z", "2026-2-1", "", 3])
def test_invalid_cutoffs_fail_before_reading_files(tmp_path,bad):
    with pytest.raises(PolicyError) as error:
        inspect_frozen_decision(tmp_path,session=bad)
    assert error.value.code=='FROZEN_SESSION_INVALID'


def test_database_path_cannot_escape_project_data(tmp_path):
    with pytest.raises(PolicyError) as error:
        inspect_frozen_decision(tmp_path,db=Path('../secrets.sqlite3'))
    assert error.value.code=='FROZEN_DB_PATH_INVALID'


def test_utc_clock_requires_explicit_offset():
    for value in ('2026-11-06', '2026-11-06T21:00:00', None):
        with pytest.raises(PolicyError) as error:
            _utc(value)
        assert error.value.code=='FROZEN_TIME_UNVERIFIED'
    assert _utc('2026-11-06T21:00:00Z').tzinfo==timezone.utc


def test_only_content_addressed_managed_files_can_be_read(tmp_path):
    folder=tmp_path/'data/managed/decisions';folder.mkdir(parents=True)
    payload=b'{"protocol_only":true}'
    (folder/'review.json').write_bytes(payload)
    digest=sha256(payload).hexdigest()
    assert _artifact(tmp_path,'managed/decisions/review.json',digest,'decisions')==payload
    with pytest.raises(PolicyError) as error:
        _artifact(tmp_path,'managed/decisions/review.json','0'*64,'decisions')
    assert error.value.code=='FROZEN_ARCHIVE_CHANGED'
    (tmp_path/'data/managed/models').mkdir(parents=True)
    with pytest.raises(PolicyError) as error:
        _artifact(tmp_path,'managed/decisions/review.json',digest,'models')
    assert error.value.code=='FROZEN_ARCHIVE_UNAVAILABLE'


def test_empty_record_list_is_not_populated(tmp_path):
    from quant_research.clock import TradingClock
    clock=TradingClock()
    frozen=clock.window('2026-11-06',1).signal_time
    assert _candidate_rows([],session='2026-11-06',frozen_at=frozen,
                            clock=clock,source_ids={})==[]


def test_prohibited_future_outcomes_are_rejected_before_data_inspection():
    from quant_research.clock import TradingClock
    clock=TradingClock()
    frozen=clock.window('2026-11-06',1).signal_time
    for forbidden in ('actual_return','future_return','fill_price','label_available_at'):
        with pytest.raises(PolicyError) as error:
            _candidate_rows([{forbidden:1}],session='2026-11-06',frozen_at=frozen,
                            clock=clock,source_ids={})
        assert error.value.code=='FROZEN_DECISION_LOOKAHEAD'


def test_source_unknown_identity_cannot_appear_as_a_candidate():
    from quant_research.clock import TradingClock
    clock=TradingClock()
    day='2026-11-06'
    frozen=clock.window(day,1).signal_time
    row={k:'opaque' for k in ('sector','signal_time','feature_available_at','fit_time','exit_date')}
    row.update({'security_id':'SYMBOL-UNVERIFIED:TEST','symbol':'TEST',
                'adv20':1,'atr20':1,'decision_eligible':True,'adjustment_basis':'raw'})
    with pytest.raises(PolicyError) as error:
        _candidate_rows([row],session=day,frozen_at=frozen,clock=clock,
                        source_ids={'SYMBOL-UNVERIFIED:TEST':'TEST'})
    assert error.value.code=='FROZEN_SIGNAL_IDENTITY_INVALID'


def test_non_record_and_excessive_signal_payloads_rejected():
    from quant_research.clock import TradingClock
    clock=TradingClock()
    frozen=clock.window('2026-11-06',1).signal_time
    for items in (None,{},[None]*101):
        with pytest.raises(PolicyError) as error:
            _candidate_rows(items,session='2026-11-06',frozen_at=frozen,clock=clock,source_ids={})
        assert error.value.code=='FROZEN_SIGNAL_SCHEMA_INVALID'


def test_cli_propagates_blocked_status_without_any_sample_candidates(tmp_path,monkeypatch,capsys):
    monkeypatch.chdir(tmp_path)
    from quant_research.cli import main
    code=main(['frozen-candidates'])
    assert code==4
    output=capsys.readouterr().out
    assert 'NO_REAL_DATA' in output and '"candidates": []' in output
    assert not (tmp_path/'data').exists()


def test_signal_and_paper_pages_consume_separate_evidence_sources():
    root=Path(__file__).resolve().parents[1]
    js=(root/'src/quant_research/assets/studio.js').read_text(encoding='utf-8')
    web=(root/'src/quant_research/web.py').read_text(encoding='utf-8')
    assert "'/api/v1/signals/frozen'" in web
    assert 'async function signals()' in js and "'/api/v1/signals/frozen?'" in js
    assert 'const snapshots=observation.snapshots||[]' in js
    assert 'observation.missing_xnys_sessions||[]' in js
    assert 'inventory.records?.length' not in js
