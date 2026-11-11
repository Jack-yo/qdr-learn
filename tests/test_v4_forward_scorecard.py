"""Forward scorecard fixtures are synthetic contract tests, not actual alpha results."""
import pandas as pd
import pytest

from quant_research.workflow.v4_forward_scorecard import score_frozen_horizon_records


def _records(count=70):
    sessions=pd.bdate_range("2025-01-02",periods=count+5)
    result=[]
    for i,day in enumerate(sessions[:count]):
        result.append({
            "session_date_et":day.date().isoformat(),
            "security_id":"AAA","source_forecast_identity":"f"*16,
            "horizon_close_session":sessions[i+3].date().isoformat(),
            "p_up":.60,"predicted_gross_return":.02,
            "horizon_gross_price_return":.05 if i%2==0 else -.03,
            "modeled_stop_net_return":.03 if i%2==0 else -.04})
    return result


def test_causal_h3_scorecard_distinguishes_model_and_historical_prior():
    report=score_frozen_horizon_records(_records(),minimum_sessions=10,
                                        baseline_sessions=5)
    assert report["status"]=="FORWARD_RESEARCH_SAMPLE_SUFFICIENT_FOR_DIAGNOSTICS_ONLY"
    assert report["sessions_with_outcomes"]==70
    assert report["comparable_sessions"]>=50
    assert report["paired_block_bootstrap_95ci"] is not None
    assert len(report["paired_block_bootstrap_95ci"])==2
    assert report["source_independently_attested"] is False
    assert report["broker_fills_observed"] is False
    assert report["paper_ledger_advanced"] is False


def test_later_unmatured_label_never_changes_earlier_baseline():
    original=_records(15)
    changed=[dict(x) for x in original]
    changed[7]["horizon_gross_price_return"]=.7
    before=score_frozen_horizon_records(original,minimum_sessions=10,
                                       baseline_sessions=5)
    after=score_frozen_horizon_records(changed,minimum_sessions=10,
                                      baseline_sessions=5)
    session=original[8]["session_date_et"]
    prior_a=next(x for x in before["daily_research_scores"]
                 if x["session_date_et"]==session)
    prior_b=next(x for x in after["daily_research_scores"]
                 if x["session_date_et"]==session)
    assert prior_a["causal_prior_p_up"]==prior_b["causal_prior_p_up"]


def test_stop_scenario_outcomes_do_not_become_probability_targets():
    rows=_records(15)
    adjusted=[dict(x,modeled_stop_net_return=-.8) for x in rows]
    a=score_frozen_horizon_records(rows,minimum_sessions=10,
                                  baseline_sessions=5)
    b=score_frozen_horizon_records(adjusted,minimum_sessions=10,
                                  baseline_sessions=5)
    assert a["model_mean_brier"]==b["model_mean_brier"]
    assert a["causal_baseline_mean_brier"]==b["causal_baseline_mean_brier"]


def test_small_forward_sample_must_not_be_called_verified_edge():
    result=score_frozen_horizon_records(_records(12),minimum_sessions=60,
                                        baseline_sessions=5)
    assert result["status"]=="INSUFFICIENT_PROSPECTIVE_RESEARCH_SESSIONS"
    assert result["paired_block_bootstrap_95ci"] is None


def test_duplicate_security_session_and_invalid_future_labels_fail():
    records=_records(15)
    with pytest.raises(ValueError,match="DUPLICATE"):
        score_frozen_horizon_records(records+[dict(records[0])],
                                    minimum_sessions=10,baseline_sessions=5)
    bad=_records(15)
    bad[0]["horizon_close_session"]=bad[0]["session_date_et"]
    with pytest.raises(ValueError,match="TIMING"):
        score_frozen_horizon_records(bad,minimum_sessions=10,baseline_sessions=5)
