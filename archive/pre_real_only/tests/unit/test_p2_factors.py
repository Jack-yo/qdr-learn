from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.features.context import FactorContext
from quant_research.features.engine import compute_features
from quant_research.features.factors import FunctionalFactor, builtin_factors


def context(length=300):
    clock = TradingClock()
    dates = clock.calendar.sessions_in_range("2020-01-01","2022-01-01")[:length]
    r = np.sin(np.arange(length)/7)*0.01+0.0005
    prices = pd.DataFrame({"SPY":100*np.cumprod(1+r),"STOCK":80*np.cumprod(1+2*r)},index=dates).sort_index(axis=1)
    panels = {"close":prices,"open":prices*0.99,"high":prices*1.02,"low":prices*0.98,"volume":prices*0+1000000}
    available = pd.DataFrame({sid:[clock.close(day)+timedelta(minutes=5) for day in dates] for sid in prices},index=dates)
    return FactorContext(panels,available,{"SPY":"SPY","STOCK":"STOCK"},"SPY"),clock


def test_factor_formula_oracles():
    c,_ = context()
    factors = {f.name:f for f in builtin_factors()}
    p = c.close.STOCK.to_numpy()
    returns = p[1:]/p[:-1]-1
    t = len(p)-1
    assert factors["reversal_5d"].compute(c).STOCK.iloc[-1] == pytest.approx(-(p[t]/p[t-5]-1))
    assert factors["momentum_12_1"].compute(c).STOCK.iloc[-1] == pytest.approx(p[t-21]/p[t-252]-1)
    assert factors["realized_vol_20"].compute(c).STOCK.iloc[-1] == pytest.approx(np.std(returns[-20:],ddof=1)*np.sqrt(252))
    assert factors["vol_ratio_5_20"].compute(c).STOCK.iloc[-1] == pytest.approx(np.std(returns[-5:],ddof=1)/np.std(returns[-20:],ddof=1))
    assert factors["adv20"].compute(c).STOCK.iloc[-1] == pytest.approx(sum(p[-20:])*1000000/20)
    assert factors["amihud20"].compute(c).STOCK.iloc[-1] == pytest.approx(np.mean(np.abs(returns[-20:])/(p[-20:]*1000000)))
    assert factors["close_location"].compute(c).STOCK.iloc[-1] == pytest.approx(0.5)
    assert factors["beta_60"].compute(c).STOCK.iloc[-1] == pytest.approx(2.0)
    assert factors["momentum_12_1"].compute(c).STOCK.iloc[:252].isna().all()


def test_sector_oracle_and_classification_availability():
    c,clock = context()
    c.sector_proxy = pd.DataFrame("SPY",index=c.close.index,columns=c.close.columns)
    c.sector_available_at = c.availability.copy()
    factors = {f.name:f for f in builtin_factors()}
    stock5 = c.close.STOCK.iloc[-1]/c.close.STOCK.iloc[-6]-1
    sector5 = c.close.SPY.iloc[-1]/c.close.SPY.iloc[-6]-1
    assert factors["sector_residual_5d"].compute(c).STOCK.iloc[-1] == pytest.approx(-(stock5-2*sector5))
    assert factors["rel_strength_sector_5d"].compute(c).STOCK.iloc[-1] == pytest.approx(stock5-sector5)
    c.sector_available_at.loc[:,:] = pd.Timestamp("2026-01-01",tz="UTC")
    rows = compute_features(c,clock,[factors["rel_strength_sector_5d"]])
    assert rows.value.isna().all()
    c.sector_available_at.loc[:,:] = pd.NaT
    assert factors["rel_strength_sector_5d"].compute(c).isna().all().all()


def test_zero_denominator_missing_windows_and_pit_gates():
    c,clock = context(80)
    c.panels["high"] = c.close.copy()
    c.panels["low"] = c.close.copy()
    c.panels["volume"].iloc[-20:,:] = 0
    factors = {f.name:f for f in builtin_factors()}
    assert factors["close_location"].compute(c).iloc[-1].isna().all()
    assert factors["amihud20"].compute(c).iloc[-1].isna().all()
    c.panels["close"].iloc[10,0] = np.nan
    rows = compute_features(c,clock,[factors["reversal_5d"],factors["size_pit"]])
    assert rows.loc[rows.feature_name.eq("reversal_5d")&rows.date.eq(c.close.index[12])&rows.security_id.eq(c.close.columns[0]),"value"].isna().all()
    assert set(rows.loc[rows.feature_name.eq("size_pit"),"missing_reason"]) == {"PIT_MARKET_CAP_UNAVAILABLE"}


def test_custom_factor_plugin_and_causal_prefix_guards():
    c,clock = context(80)
    custom = FunctionalFactor("custom_close",0,lambda x:x.close,"test close")
    assert set(compute_features(c,clock,[custom]).feature_name) == {"custom_close"}
    future = FunctionalFactor("future_close",0,lambda x:x.close.shift(-1),"intentionally broken")
    with pytest.raises(ValueError,match="Non-causal"):
        compute_features(c,clock,[future])
    full_sample = FunctionalFactor("global_normalize",0,lambda x:x.close/x.close.mean(),"intentionally broken full sample")
    with pytest.raises(ValueError,match="Non-causal"):
        compute_features(c,clock,[full_sample])


def test_future_price_and_availability_mutation_do_not_change_past():
    c,clock = context(300)
    before = compute_features(c,clock)
    cutoff = c.close.index[270]
    for panel in c.panels.values():
        panel.loc[panel.index>cutoff,:] *= 7
    c.availability.loc[c.availability.index>cutoff,:] = pd.Timestamp("2026-01-01",tz="UTC")
    after = compute_features(c,clock)
    pd.testing.assert_frame_equal(before.loc[before.date<=cutoff].reset_index(drop=True),after.loc[after.date<=cutoff].reset_index(drop=True))
