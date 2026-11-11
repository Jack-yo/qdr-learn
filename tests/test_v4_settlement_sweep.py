"""Bulk outcome sweep has a safe read-only default and explicit archival opt-in."""
import pandas as pd

from quant_research.workflow import v4_settlement_sweep as sweep


DAY="2025-01-02"
ID="f"*16


def _archive_folder(tmp_path):
    (tmp_path/"outputs/v4_research_plans"/DAY/ID).mkdir(parents=True)


def _review(*args,**kwargs):
    return {"horizon":3,"plans":[{"security_id":"AAA","symbol":"AAA"}],
            "execution_eligible":False,"real_orders_enabled":False}


def _no_outcome(*args,**kwargs):
    raise FileNotFoundError("not settled")


def test_preview_never_invokes_warehouse_or_writes(monkeypatch,tmp_path):
    _archive_folder(tmp_path)
    monkeypatch.setattr(sweep,"read_indicative_review",_review)
    monkeypatch.setattr(sweep,"read_research_outcomes",_no_outcome)
    def forbidden(*args,**kwargs):
        raise AssertionError("Preview must never request raw source or write results")
    monkeypatch.setattr(sweep,"run_warehouse_outcome_review",forbidden)
    r=sweep.sweep_matured_research_plans(
        tmp_path,now_utc="2025-01-20T12:00:00Z")
    assert r["status"]=="READ_ONLY_SETTLEMENT_PREVIEW"
    assert r["records"][0]["status"]=="READY_TO_TRY_WAREHOUSE_RECEIPTS"
    assert not r["paper_ledger_advanced"] and not r["real_orders_enabled"]


def test_explicit_freeze_checks_existing_record_first(monkeypatch,tmp_path):
    _archive_folder(tmp_path)
    monkeypatch.setattr(sweep,"read_indicative_review",_review)
    monkeypatch.setattr(sweep,"read_research_outcomes",_no_outcome)
    calls=[]
    def execute(root,**kwargs):
        calls.append(kwargs)
        return {"status":"OBSERVED_RESEARCH_OUTCOMES_FROZEN_NO_ORDERS",
                "evaluated_trades":1,"real_orders_enabled":False}
    monkeypatch.setattr(sweep,"run_warehouse_outcome_review",execute)
    r=sweep.sweep_matured_research_plans(
        tmp_path,freeze_outcomes=True,now_utc="2025-01-20T12:00:00Z")
    assert calls==[{"session_date":DAY,"plan_identity":ID}]
    assert r["records"][0]["evaluated_trades"]==1
    assert r["records"][0]["status"]=="OBSERVED_RESEARCH_OUTCOMES_FROZEN_NO_ORDERS"


def test_maturing_horizon_is_not_frozen_early(monkeypatch,tmp_path):
    _archive_folder(tmp_path)
    monkeypatch.setattr(sweep,"read_indicative_review",_review)
    def forbidden(*args,**kwargs):
        raise AssertionError("No outcomes before the H3 exit close")
    monkeypatch.setattr(sweep,"run_warehouse_outcome_review",forbidden)
    r=sweep.sweep_matured_research_plans(
        tmp_path,freeze_outcomes=True,now_utc="2025-01-03T12:00:00Z")
    assert r["records"][0]["status"]=="PENDING_FUTURE_PRICE_WINDOW"


def test_unverifiable_plan_is_rejected_not_frozen(monkeypatch,tmp_path):
    _archive_folder(tmp_path)
    monkeypatch.setattr(sweep,"read_indicative_review",
        lambda *args,**kw:{"horizon":3,"plans":[{"security_id":"AAA"}],
                           "execution_eligible":True,"real_orders_enabled":False})
    r=sweep.sweep_matured_research_plans(
        tmp_path,freeze_outcomes=True,now_utc="2025-01-20T12:00:00Z")
    assert r["blocked_plans"]==1
    assert r["records"][0]["status"]=="BLOCKED_NO_OUTCOME_ARCHIVE_WRITE"
