import pandas as pd

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
