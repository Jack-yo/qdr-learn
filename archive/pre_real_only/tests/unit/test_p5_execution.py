from dataclasses import replace

import pytest

from quant_research.backtest.costs import CostModel
from quant_research.backtest.engine import PortfolioEngine,Position
from quant_research.clock import TradingClock
from quant_research.models.settings import load_settings
from quant_research.risk.limits import stop_or_target


def setup(cost=10,risk=True):
    config=load_settings("configs/experiments/baseline.yaml")
    clock=TradingClock()
    engine=PortfolioEngine(config,clock,cost,risk)
    signal={"security_id":"A","symbol":"A","sector":"UNKNOWN","signal_time":str(clock.signal("2024-11-27")),
        "feature_available_at":str(clock.close("2024-11-27")),"exit_date":"2024-12-05","adv20":100000000.0,
        "atr20":1.0,"decision_eligible":True,"adjustment_basis":"raw"}
    return engine,signal


def bar(price=100,low=None,high=None,volume=1000000):
    return {"open":price,"close":price,"low":price-1 if low is None else low,"high":price+1 if high is None else high,"volume":volume}


def test_next_open_gap_stop_cash_and_horizon():
    engine,signal=setup()
    engine.step("2024-11-27",{"A":bar()},[signal])
    assert not engine.fills
    engine.step("2024-11-29",{"A":bar()})
    assert engine.fills[0]["fill_time"].startswith("2024-11-29 14:30")
    engine.step("2024-12-02",{"A":bar(90)})
    assert engine.fills[-1]["raw_price"]==90 and engine.fills[-1]["reason"]=="GAP_STOP"
    assert engine.fills[-1]["fill_price"]<90
    engine.reconcile()
    assert engine.cash<engine.config.initial_cash
    assert engine.curve[-1]["equity"]-engine.config.initial_cash==pytest.approx(sum(t["net_pnl"] for t in engine.trades))
    assert stop_or_target({"open":100,"low":90,"high":110},95,105)==(95.0,"STOP_FIRST_UNKNOWN_PATH")


def test_costs_zero_and_high_sensitivity_and_bad_values():
    outcomes=[]
    for cost in (0,5,10,20,50):
        engine,signal=setup(cost,risk=False)
        signal["exit_date"]="2024-11-29"
        engine.step("2024-11-27",{"A":bar()},[signal])
        engine.step("2024-11-29",{"A":bar()})
        engine.reconcile()
        outcomes.append(engine.cash)
    assert outcomes==sorted(outcomes,reverse=True)
    with pytest.raises(ValueError): CostModel(-1)
    with pytest.raises(ValueError): CostModel(20000).fill("BUY",100,1,100000)
    with pytest.raises(ValueError): CostModel(10).fill("BUY",100,1,float("nan"))


def test_constraints_future_data_and_halt():
    engine,signal=setup(risk=True)
    signals=[{**signal,"security_id":str(i),"symbol":str(i)} for i in range(6)]
    bars={str(i):bar() for i in range(6)}
    engine.step("2024-11-27",bars,signals)
    engine.step("2024-11-29",bars)
    assert sum(p.quantity*100 for p in engine.positions.values())/engine.equity()<=0.25+1e-8
    assert all(p.quantity*2/engine.config.initial_cash<=0.003 for p in engine.positions.values())
    engine.step("2024-12-02",{})
    assert "STALE_VALUATION_UNRESOLVED_POSITION" in engine.flags
    assert engine.positions
    bad,signal=setup()
    signal["feature_available_at"]="2030-01-01T00:00:00+00:00"
    with pytest.raises(ValueError,match="Future feature"):
        bad.step("2024-11-27",{"A":bar()},[signal])


def test_split_dividend_delisting_economic_accounting():
    engine,_=setup(risk=False)
    engine.cash-=1000
    engine.positions["A"]=Position("A","A","UNKNOWN",10,"2024-11-27T14:30:00+00:00",1000,100,"2024-12-06",None,100000000)
    engine.last_prices["A"]=100
    engine.last_date="2024-11-27"
    engine.step("2024-11-29",{"A":bar(50)},events=[{"security_id":"A","action_type":"split","value":2}])
    assert engine.positions["A"].quantity==20
    assert engine.equity()==pytest.approx(100000)
    engine.step("2024-12-02",{"A":bar(49)},events=[{"security_id":"A","action_type":"dividend","value":1,"payment_policy":"VERIFIED_EFFECTIVE_DATE"}])
    assert engine.equity()==pytest.approx(100000)
    with pytest.raises(ValueError,match="verified"):
        engine.step("2024-12-03",{},events=[{"security_id":"A","action_type":"delist","value":0}])


def test_kill_switch_cancels_pending_entries_and_persists():
    engine,signal=setup()
    engine.step("2024-11-27",{"A":bar()},[signal])
    engine.kill_switch("manual engineering test")
    engine.step("2024-11-29",{"A":bar()})
    assert not engine.fills and not engine.positions
    assert engine.state()["kill_switch_reason"]=="manual engineering test"


def test_invalid_corporate_cash_never_changes_account():
    engine,_=setup(risk=False)
    cash=engine.cash
    with pytest.raises(ValueError,match="finite and nonnegative"):
        engine.step("2024-11-27",{},events=[{"security_id":"A","action_type":"dividend","value":float("nan"),"payment_policy":"VERIFIED_EFFECTIVE_DATE"}])
    assert engine.cash==cash and not engine.actions
