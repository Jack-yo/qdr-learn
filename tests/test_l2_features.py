"""Verified L2 historical style-feature tests."""
import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.research.l2_features import (
    REQUIRED_FEATURE_PRICE_BASIS,
    build_verified_style_features_v1,
)
from quant_research.research.l2_style_rotation import REQUIRED_SYMBOLS, STYLE_REGISTRY


def _evidence(n=90):
    clock=TradingClock()
    sessions=clock.calendar.sessions_in_range("2025-01-02","2025-12-31")[:n]
    close=pd.DataFrame(index=sessions,columns=REQUIRED_SYMBOLS,dtype=float)
    availability=pd.DataFrame(index=sessions,columns=REQUIRED_SYMBOLS,dtype=object)
    actions=pd.DataFrame(True,index=sessions,columns=REQUIRED_SYMBOLS)
    for si,symbol in enumerate(REQUIRED_SYMBOLS):
        for i,day in enumerate(sessions):
            close.loc[day,symbol]=90+si*3+i*(0.15+si*.002)+np.sin(i*.07+si)*.2
            availability.loc[day,symbol]=(
                pd.Timestamp(clock.close(day))+pd.Timedelta(minutes=5)
            )
    return clock,sessions,close,availability,actions


def test_verified_features_cover_all_seven_styles_after_warmup():
    clock,sessions,close,availability,actions=_evidence()
    result=build_verified_style_features_v1(
        close,availability,actions,sessions,clock,
        price_basis=REQUIRED_FEATURE_PRICE_BASIS,
        action_evidence_version="actions-v1",
    )
    assert set(result.style_id)=={x.style_id for x in STYLE_REGISTRY}
    latest=result.loc[result.date.eq(sessions[-1])]
    assert len(latest)==7
    assert latest.feature_pit_eligible.all()
    assert set(latest.feature_status)=={"VERIFIED_PIT_FEATURE"}
    assert latest.historical_pit_attested.all()
    assert not latest.decision_eligible.any()
    assert not latest.real_orders_enabled.any()
    assert latest.available_at.le(latest.signal_time).all()


def test_source_arriving_after_signal_blocks_overlapping_feature_window():
    clock,sessions,close,availability,actions=_evidence()
    bad_day=sessions[-5]
    availability.loc[bad_day,"IWM"]=(
        pd.Timestamp(clock.signal(bad_day))+pd.Timedelta(minutes=1)
    )
    result=build_verified_style_features_v1(
        close,availability,actions,sessions,clock,
        price_basis=REQUIRED_FEATURE_PRICE_BASIS,
        action_evidence_version="actions-v1",
    )
    size=result.loc[result.style_id.eq("size")].set_index("date")
    assert size.loc[sessions[-1],"feature_pit_eligible"] == False
    assert size.loc[sessions[-1],"feature_block_reason"] == "FEATURE_AVAILABLE_AFTER_SIGNAL"
    quality=result.loc[result.style_id.eq("quality")].set_index("date")
    assert quality.loc[sessions[-1],"feature_pit_eligible"] == True


def test_missing_action_evidence_blocks_only_affected_style_windows():
    clock,sessions,close,availability,actions=_evidence()
    actions.loc[sessions[-10],"XLY"]=False
    result=build_verified_style_features_v1(
        close,availability,actions,sessions,clock,
        price_basis=REQUIRED_FEATURE_PRICE_BASIS,
        action_evidence_version="actions-v1",
    )
    current=result.loc[result.date.eq(sessions[-1])].set_index("style_id")
    assert current.loc["cyc_def","feature_pit_eligible"] == False
    assert current.loc["cyc_def","feature_block_reason"] == "INCOMPLETE_60D_OR_ACTION_COVERAGE_WINDOW"
    assert current.loc["size","feature_pit_eligible"] == True


def test_wrong_or_current_vintage_price_basis_is_rejected():
    clock,sessions,close,availability,actions=_evidence()
    with pytest.raises(ValueError,match="action-consistent"):
        build_verified_style_features_v1(
            close,availability,actions,sessions,clock,
            price_basis="yahoo_split_adjusted",
            action_evidence_version="actions-v1",
        )


def test_future_price_mutation_does_not_change_prior_verified_features():
    clock,sessions,close,availability,actions=_evidence()
    baseline=build_verified_style_features_v1(
        close,availability,actions,sessions,clock,
        price_basis=REQUIRED_FEATURE_PRICE_BASIS,
        action_evidence_version="actions-v1",
    )
    changed=close.copy()
    changed.loc[sessions[-1],:]*=10
    recomputed=build_verified_style_features_v1(
        changed,availability,actions,sessions,clock,
        price_basis=REQUIRED_FEATURE_PRICE_BASIS,
        action_evidence_version="actions-v1",
    )
    pd.testing.assert_frame_equal(
        baseline.loc[baseline.date.lt(sessions[-1])].reset_index(drop=True),
        recomputed.loc[recomputed.date.lt(sessions[-1])].reset_index(drop=True),
    )
