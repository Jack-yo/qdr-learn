"""Warehouse H3 outcome cohort tests use deterministic price rows, never market P&L."""
import pandas as pd
import pytest

from quant_research.workflow.v4_warehouse_outcomes import (
    assemble_warehouse_outcome_bars)


def _source():
    sessions=pd.DatetimeIndex(["2026-11-11","2026-11-12","2026-11-13"])
    rows=[]
    for day in sessions:
        rows.append({"date":day,"security_id":"SID-AAA","symbol":"AAA",
                     "open":100.,"high":105.,"low":97.,"close":102.,
                     "available_at":"2026-11-13T22:00:00Z",
                     "raw_sha256":"a"*64,"source":"ALPACA","feed":"sip",
                     "adjustment_basis":"raw"})
    review={"plans":[{"security_id":"SID-AAA","symbol":"AAA"}]}
    return pd.DataFrame(rows),review,sessions


def _assemble(prices,review,sessions,checker=None):
    return assemble_warehouse_outcome_bars(prices,review,sessions,
        cutoff="2026-11-14T12:00:00Z",
        action_checker=checker or (lambda row,cutoff:"b"*64))


def test_verified_raw_future_cohort_maps_to_nonexecuting_model_input():
    prices,review,sessions=_source()
    bars,actions=_assemble(prices,review,sessions)
    assert len(bars)==len(sessions)==3
    assert bars.corporate_action_status.eq("VERIFIED_NO_ACTION").all()
    assert set(bars.source_sha256)=={"a"*64}
    assert len(actions)==3 and all(x["action_receipt_sha256"]=="b"*64 for x in actions)


def test_missing_or_duplicate_future_session_fails_closed():
    prices,review,sessions=_source()
    with pytest.raises(ValueError,match="SESSION_COHORT_INCOMPLETE"):
        _assemble(prices.iloc[:-1],review,sessions)
    with pytest.raises(ValueError,match="SESSION_COHORT_INCOMPLETE"):
        _assemble(pd.concat([prices,prices.iloc[[0]]],ignore_index=True),
                  review,sessions)


def test_wrong_source_or_adjustment_basis_cannot_become_raw_fill():
    prices,review,sessions=_source()
    for field,wrong in (("source","YAHOO"),("feed","iex"),
                        ("adjustment_basis","yahoo_split_adjusted"),
                        ("symbol","OTHER")):
        altered=prices.copy()
        altered.loc[0,field]=wrong
        with pytest.raises(ValueError,match="SOURCE_BASIS_OR_IDENTITY_INVALID"):
            _assemble(altered,review,sessions)


def test_unverified_action_coverage_never_promotes_clean_outcome():
    prices,review,sessions=_source()
    with pytest.raises(ValueError,match="ACTION_RECEIPT_NOT_PROVEN"):
        _assemble(prices,review,sessions,lambda row,cutoff:None)


def test_future_price_vintage_and_ohlc_envelope_fail():
    prices,review,sessions=_source()
    prices.loc[0,"available_at"]="2027-01-01T00:00:00Z"
    with pytest.raises(ValueError,match="PRICE_NOT_AVAILABLE"):
        _assemble(prices,review,sessions)
    prices,review,sessions=_source()
    prices.loc[0,"low"]=150.
    with pytest.raises(ValueError,match="RAW_OHLC_ENVELOPE_INVALID"):
        _assemble(prices,review,sessions)


def test_symbol_collision_and_missing_horizon_session_fail():
    prices,review,sessions=_source()
    review["plans"].append({"security_id":"SID-BBB","symbol":"AAA"})
    with pytest.raises(ValueError,match="PLAN_IDENTITY_AMBIGUOUS"):
        _assemble(prices,review,sessions)
    prices,review,sessions=_source()
    with pytest.raises(ValueError,match="SESSION_COHORT_INCOMPLETE"):
        _assemble(prices,review,sessions[:-1])
