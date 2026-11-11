"""Research cash-book accounting tests: not market-data or broker-fill validation."""
import pytest
from quant_research.workflow import v4_cash_scenario as book


def _patch(monkeypatch,plans,outcomes):
    monkeypatch.setattr(book,'read_indicative_review',
        lambda root,day,identity:plans[(day,identity)])
    monkeypatch.setattr(book,'read_research_outcomes',
        lambda root,day,identity:outcomes[(day,identity)])


def _record(day,identity,sid,entry,exit_date,weight=.4,exit_price=105.):
    p={'content_sha256':'a'*64,
       'account_evidence':'EXPLICIT_EMPTY_RESEARCH_BUDGET_NOT_A_PAPER_ACCOUNT',
       'plans':[{'security_id':sid,'indicative_weight':weight}]}
    o={'source_plan_sha256':'a'*64,'evaluated':[{
        'security_id':sid,'planned_entry_session':entry,
        'modeled_exit_session':exit_date,
        'modeled_entry_price':100.,'modeled_exit_price':exit_price,
        'assumed_round_trip_cost':.002}]}
    return p,o


def test_scenario_round_trip_cash_and_costs(monkeypatch,tmp_path):
    key=('2025-01-02','f'*16)
    p,o=_record(*key,'AAA','2025-01-03','2025-01-07')
    _patch(monkeypatch,{key:p},{key:o})
    result=book.replay_research_cash_book(tmp_path,[key],initial_cash=10000)
    assert result['final_cash']==pytest.approx(10192.)
    assert result['modeled_total_return']==pytest.approx(.0192)
    assert [t['event'] for t in result['transactions']]==['MODELED_ENTRY','MODELED_EXIT']
    assert result['paper_ledger_advanced'] is False
    assert result['broker_fills_observed'] is False


def test_overlapping_cash_exposure_cannot_exceed_available_cash(monkeypatch,tmp_path):
    a=('2025-01-02','f'*16)
    b=('2025-01-03','e'*16)
    p1,o1=_record(*a,'AAA','2025-01-03','2025-01-09',.7)
    p2,o2=_record(*b,'BBB','2025-01-06','2025-01-10',.5)
    _patch(monkeypatch,{a:p1,b:p2},{a:o1,b:o2})
    with pytest.raises(ValueError,match='OVERCOMMITTED'):
        book.replay_research_cash_book(tmp_path,[a,b],initial_cash=10000)


def test_same_day_exit_releases_cash_before_next_entry(monkeypatch,tmp_path):
    a=('2025-01-02','f'*16)
    b=('2025-01-06','e'*16)
    p1,o1=_record(*a,'AAA','2025-01-03','2025-01-07',.8)
    p2,o2=_record(*b,'BBB','2025-01-07','2025-01-09',.8)
    _patch(monkeypatch,{a:p1,b:p2},{a:o1,b:o2})
    result=book.replay_research_cash_book(tmp_path,[a,b],initial_cash=10000)
    assert result['final_cash']>10000
    assert len(result['transactions'])==4


def test_missing_security_outcome_and_duplicate_plan_refuse(monkeypatch,tmp_path):
    key=('2025-01-02','f'*16)
    p,o=_record(*key,'AAA','2025-01-03','2025-01-07')
    o['evaluated']=[]
    _patch(monkeypatch,{key:p},{key:o})
    with pytest.raises(ValueError,match='COVERAGE_INCOMPLETE'):
        book.replay_research_cash_book(tmp_path,[key],initial_cash=10000)
    with pytest.raises(ValueError,match='DUPLICATE'):
        book.replay_research_cash_book(tmp_path,[key,key],initial_cash=10000)
