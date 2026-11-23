import pandas as pd
import pytest

from quant_research.workflow import l3_overview as l3


DAY="2026-11-10"


def _strategy():
    return {
        "id":"strategy","name":"Alpha Mix","version":1,"status":"FROZEN",
        "config_sha256":"a"*64,
        "config":{"factor_mix":{"allocations":[
            {"factor_experiment_id":"e1","weight":.6,
             "dependency":{"factor_name":"reversal","factor_version":1}},
            {"factor_experiment_id":"e2","weight":.4,
             "dependency":{"factor_name":"relative_strength","factor_version":1}},
        ]},"strategy":{"horizon":3}},
    }


def _frames():
    factors=[]
    values={
        "AAA":{"reversal":3.0,"relative_strength":1.0},
        "BBB":{"reversal":2.0,"relative_strength":3.0},
        "CCC":{"reversal":1.0,"relative_strength":2.0},
        "DDD":{"reversal":0.0,"relative_strength":0.0},
        "EEE":{"reversal":-1.0,"relative_strength":-1.0},
    }
    for sid,parts in values.items():
        for name,value in parts.items():
            factors.append({"date":DAY,"security_id":sid,"feature_name":name,
                            "value":value,"decision_eligible":True,
                            "available_at":"2026-11-10T21:10:00Z"})
    meta=pd.DataFrame([
        {"date":DAY,"security_id":sid,"symbol":sid,"sector":"TECH",
         "reference_close":100.,"atr20":2.,"adv20":30_000_000.}
        for sid in values
    ])
    return {"factors":pd.DataFrame(factors),"candidate_meta":meta}


def test_daily_alpha_score_is_weighted_cross_sectional_rank():
    scores,names=l3._daily_scores(_strategy(),_frames(),DAY)
    assert names==["reversal","relative_strength"]
    aaa=scores.loc[scores.security_id.eq("AAA")].iloc[0]
    bbb=scores.loc[scores.security_id.eq("BBB")].iloc[0]
    assert aaa.alpha_score > bbb.alpha_score
    assert aaa.alpha_rank_pct==1.0
    assert scores.alpha_score.between(0,1).all()


def test_daily_score_never_imputes_missing_active_factor():
    frames=_frames()
    frames["factors"]=frames["factors"].loc[
        ~((frames["factors"].security_id=="AAA")
          &(frames["factors"].feature_name=="relative_strength"))
    ]
    scores,_=l3._daily_scores(_strategy(),frames,DAY)
    assert "AAA" not in set(scores.security_id)


def test_candidates_do_not_invent_forecast_metrics():
    scores,names=l3._daily_scores(_strategy(),_frames(),DAY)
    meta=l3._candidate_metadata(_frames(),DAY)
    result=l3._build_candidates(scores,names,meta,pd.DataFrame(),"A",3,20)
    assert result
    assert all(row["expected_excess_return"] is None for row in result)
    assert all(row["p_up"] is None for row in result)
    assert all(row["research_only"] is True for row in result)


def test_only_top_cross_section_becomes_candidate():
    scores,names=l3._daily_scores(_strategy(),_frames(),DAY)
    result=l3._build_candidates(scores,names,l3._candidate_metadata(_frames(),DAY),
                                pd.DataFrame(),"A",3,20)
    assert 1 <= len(result) < len(scores)
    assert all(row["alpha_rank_pct"]>=.80 for row in result)


def test_signal_history_derives_alpha_rank_change_and_consecutive_persistence():
    current = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.90,"alpha_rank_pct":.95,"alpha_rank":1},
        {"security_id":"BBB","alpha_score":.85,"alpha_rank_pct":.85,"alpha_rank":2},
    ])
    prior_1 = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.82,"alpha_rank_pct":.90,"alpha_rank":2},
        {"security_id":"BBB","alpha_score":.87,"alpha_rank_pct":.87,"alpha_rank":1},
    ])
    prior_2 = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.80,"alpha_rank_pct":.86,"alpha_rank":2},
        {"security_id":"BBB","alpha_score":.83,"alpha_rank_pct":.78,"alpha_rank":3},
    ])
    candidates = [{"security_id":"AAA"},{"security_id":"BBB"}]

    result = l3._attach_signal_history(
        candidates, current,
        [("2026-11-19", prior_1), ("2026-11-18", prior_2)],
        threshold=.80,
    )
    by_symbol = {row["security_id"]: row for row in result}

    assert by_symbol["AAA"]["alpha_delta"] == pytest.approx(.08)
    assert by_symbol["AAA"]["rank_delta"] == 1
    assert by_symbol["AAA"]["signal_state"] == "STRENGTHENING"
    assert by_symbol["AAA"]["signal_age_sessions"] == 3

    assert by_symbol["BBB"]["alpha_delta"] == pytest.approx(-.02)
    assert by_symbol["BBB"]["rank_delta"] == -1
    assert by_symbol["BBB"]["signal_state"] == "WEAKENING"
    assert by_symbol["BBB"]["signal_age_sessions"] == 2


def test_signal_history_distinguishes_new_from_unavailable_history():
    current = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.90,"alpha_rank_pct":.95,"alpha_rank":1},
    ])
    prior = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.50,"alpha_rank_pct":.50,"alpha_rank":4},
    ])
    candidate = [{"security_id":"AAA"}]

    new = l3._attach_signal_history(
        candidate, current, [("2026-11-19", prior)], threshold=.80
    )[0]
    assert new["signal_state"] == "NEW"
    assert new["signal_age_sessions"] == 1
    assert new["alpha_delta"] == pytest.approx(.40)

    unavailable = l3._attach_signal_history(
        candidate, current, [], threshold=.80
    )[0]
    assert unavailable["signal_state"] == "HISTORY_UNAVAILABLE"
    assert unavailable["signal_age_sessions"] is None
    assert unavailable["alpha_delta"] is None


def test_signal_history_marks_security_missing_from_previous_cohort():
    current = pd.DataFrame([
        {"security_id":"AAA","alpha_score":.90,"alpha_rank_pct":.95,"alpha_rank":1},
    ])
    prior = pd.DataFrame([
        {"security_id":"BBB","alpha_score":.80,"alpha_rank_pct":.90,"alpha_rank":1},
    ])
    result = l3._attach_signal_history(
        [{"security_id":"AAA"}], current, [("2026-11-19", prior)]
    )[0]
    assert result["signal_state"] == "NEW_TO_COHORT"
    assert result["signal_age_sessions"] is None
    assert result["alpha_delta"] is None


def test_signal_history_uses_xnys_sessions_not_calendar_days():
    assert l3._previous_session_dates("2026-11-23", count=3) == [
        "2026-11-20", "2026-11-19", "2026-11-18"
    ]
