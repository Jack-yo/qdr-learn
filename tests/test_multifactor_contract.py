"""No market-data fixture: schema, source-comparability and fail-closed checks only."""
from uuid import uuid4

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_research.policy import PolicyError
from quant_research.research import strategy
from quant_research.research.strategy import FactorAllocation, StrategySpec, research_mix
from quant_research.research.composite import _rank_frame


def _base():
    return {"name":"multi-factor research", "horizon":3,
            "max_stock_weight":0.10,"max_total_weight":0.50,
            "max_sector_weight":0.25,"minimum_adv20":20_000_000.0,
            "stop_atr_multiple":2.0}


def test_legacy_single_factor_spec_works():
    a=str(uuid4())
    item=StrategySpec.model_validate({**_base(),"factor_experiment_id":a})
    assert item.factor_experiment_id==a and item.factors is None


def test_multifactor_weights_and_unique_experiments_required():
    a,b=str(uuid4()),str(uuid4())
    valid={**_base(),"factors":[{"factor_experiment_id":a,"weight":0.4},
                                {"factor_experiment_id":b,"weight":0.6}]}
    assert len(StrategySpec.model_validate(valid).factors)==2
    invalid=[
        {**valid,"factor_experiment_id":a},
        {**valid,"factors":[valid['factors'][0]]},
        {**valid,"factors":[valid['factors'][0],valid['factors'][0]]},
        {**valid,"factors":[{**valid['factors'][0],"weight":0.7},valid['factors'][1]]},
        {**valid,"factors":[{**valid['factors'][0],"weight":-0.2},valid['factors'][1]]},
        {**valid,"factors":[{**valid['factors'][0],"weight":float('nan')},valid['factors'][1]]},
        {**valid,"factors":[{**valid['factors'][0],"weight":0.4,'ignore_time_gate':True},valid['factors'][1]]},
        {**_base()},
    ]
    for body in invalid:
        with pytest.raises(ValidationError): StrategySpec.model_validate(body)


def test_comparability_gate_rejects_different_source_snapshot(monkeypatch):
    a,b=str(uuid4()),str(uuid4())
    def dep(root,identifier,horizon):
        return {"factor_version_id":identifier,"snapshot_sha256":"a"*64 if identifier==a else "b"*64,
                "source":"YAHOO","adjustment_basis":"yahoo_split_adjusted"}
    monkeypatch.setattr(strategy,'research_dependency',dep)
    from quant_research.workflow import factor_lab
    def verified(root,identifier):
        return {"result":{"universe_version":"EXPLICIT_CURRENT_ETF_LIST_NOT_PIT",
                          "symbols":["SPY"],"experiment":{"horizons":[1,3,5]}}}
    monkeypatch.setattr(factor_lab,'result',verified)
    parts=[FactorAllocation(factor_experiment_id=a,weight=0.5),
           FactorAllocation(factor_experiment_id=b,weight=0.5)]
    with pytest.raises(PolicyError) as exc:research_mix('.',parts,3)
    assert exc.value.code=='INCOMPARABLE_FACTOR_EXPERIMENTS'
    assert 'snapshot_sha256' in exc.value.missing


def test_factor_ranking_requires_genuine_nonexecutable_rows():
    required=['date','security_id','value','decision_eligible','research_mode']
    with pytest.raises(PolicyError) as exc:_rank_frame(pd.DataFrame(columns=required),'any')
    assert exc.value.code=='FACTOR_FEATURE_KEYS_INVALID'
    with pytest.raises(PolicyError) as exc:_rank_frame(pd.DataFrame(columns=['date','value']),'any')
    assert exc.value.code=='FACTOR_FEATURE_FIELDS_MISSING'


def test_ui_and_service_route_do_not_claim_execution():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    ui=((root/'src/quant_research/assets/studio.js' if (root/'src').is_dir() else root/'quant_research/assets/studio.js')).read_text(encoding='utf-8')
    web=((root/'src/quant_research/web.py' if (root/'src').is_dir() else root/'quant_research/web.py')).read_text(encoding='utf-8')
    assert '/composite' in ui and "path.endswith('/composite')" in web
    assert 'MULTIFACTOR' not in ui or 'research' in ui.lower()
    assert '非交易信号' in ui



def test_three_group_hypotheses_are_checked_and_persisted_without_breaking_legacy(monkeypatch):
    a,b=str(uuid4()),str(uuid4())
    def dep(root,identifier,horizon):
        return {"factor_version_id":identifier,
                "snapshot_sha256":"c"*64,"source":"YAHOO",
                "adjustment_basis":"yahoo_split_adjusted"}
    monkeypatch.setattr(strategy,'research_dependency',dep)
    from quant_research.workflow import factor_lab
    monkeypatch.setattr(factor_lab,'result',
        lambda root,identifier:{"result":{
            "universe_version":"EXPLICIT_CURRENT_ETF_LIST_NOT_PIT",
            "symbols":["SPY"],"experiment":{"horizons":[1,3,5]}}})
    groups=[FactorAllocation(factor_experiment_id=a,weight=0.35,group="A"),
            FactorAllocation(factor_experiment_id=b,weight=0.65,group="C")]
    recorded=research_mix('.',groups,3)
    assert [x['group'] for x in recorded['allocations']]==['A','C']
    assert [x['weight'] for x in recorded['allocations']]==[0.35,0.65]
    legacy=research_mix('.',
        [FactorAllocation(factor_experiment_id=a,weight=0.35),
         FactorAllocation(factor_experiment_id=b,weight=0.65)],3)
    assert all('group' not in x for x in legacy['allocations'])
    with pytest.raises(ValidationError):
        FactorAllocation(factor_experiment_id=a,weight=0.35,group="D")
    with pytest.raises(ValidationError):
        FactorAllocation(factor_experiment_id=a,weight=0.35,group="a")
