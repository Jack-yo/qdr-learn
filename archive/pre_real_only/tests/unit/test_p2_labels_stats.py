from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from quant_research.clock import TradingClock
from quant_research.features.context import FactorContext
from quant_research.research.labels import make_labels
from quant_research.research.statistics import circular_block_ci, daily_rank_ic, quintile_returns


def label_context():
    clock = TradingClock()
    dates = clock.calendar.sessions_in_range("2024-11-27","2024-12-06")
    close = pd.DataFrame({"SPY":np.arange(len(dates))+100.0,"STOCK":[10,55,60,65,70,75,80]},index=dates).sort_index(axis=1)
    opening = close.copy()
    opening.loc[dates[1],"STOCK"] = 50
    panels = {"close":close,"open":opening}
    available = pd.DataFrame({sid:[clock.close(d)+timedelta(minutes=5) for d in dates] for sid in close},index=dates)
    return FactorContext(panels,available,{"SPY":"SPY","STOCK":"STOCK"},"SPY"),clock


def test_label_horizons_holiday_raw_proxy_and_tail():
    c,clock = label_context()
    labels = make_labels(c,clock,exclude_symbols=["SPY"])
    first = labels.loc[labels.date.eq(pd.Timestamp("2024-11-27"))].set_index("horizon")
    assert first.loc[1,"forward_return"] == pytest.approx(0.1)
    assert first.loc[3,"forward_return"] == pytest.approx(0.3)
    assert first.loc[5,"forward_return"] == pytest.approx(0.5)
    assert str(first.loc[1,"entry_date"]) == "2024-11-29"
    assert first.loc[1,"exit_time"].hour == 18
    assert first.loc[1,"available_at"] > clock.signal("2024-11-27")
    assert labels.loc[labels.date.eq(c.close.index[-1]),"forward_return"].isna().all()
    proxy = make_labels(c,clock,adjustment_basis="yahoo_split_adjusted")
    assert proxy.forward_return.isna().all() and proxy.benchmark_return.isna().all()
    assert proxy.proxy_forward_return.notna().any() and proxy.net_return.isna().all()
    c.panels["close"].loc[c.close.index[2],"STOCK"] = np.nan
    gap = make_labels(c,clock)
    assert gap.loc[gap.date.eq(c.close.index[0])&gap.security_id.eq("STOCK")&gap.horizon.eq(3),"forward_return"].isna().all()


def test_rank_ic_ties_constant_and_minimum_count():
    date = pd.Timestamp("2024-01-02")
    pairs = pd.DataFrame({"date":date,"security_id":list("abcdef"),"value":[1,2,2,4,5,6],"target":[1,3,3,5,7,9]})
    assert daily_rank_ic(pairs,min_count=5).rank_ic.iloc[0] == pytest.approx(1)
    pairs["target"] *= -1
    assert daily_rank_ic(pairs,min_count=5).rank_ic.iloc[0] == pytest.approx(-1)
    pairs["value"] = 1
    assert daily_rank_ic(pairs,min_count=5).rank_ic.isna().all()
    assert daily_rank_ic(pairs.iloc[:3],min_count=5).rank_ic.isna().all()
    groups,turnover = quintile_returns(pairs,min_count=5)
    assert groups.empty and turnover is None


def test_quintile_forward_returns_and_membership_turnover():
    rows = []
    for day in pd.date_range("2024-01-01",periods=2):
        for i in range(10):
            rows.append({"date":day,"security_id":str(i),"value":i if day.day==1 else 9-i,"target":i/100})
    groups,turnover = quintile_returns(pd.DataFrame(rows),min_count=10)
    first = groups.loc[groups.date.eq(pd.Timestamp("2024-01-01"))].set_index("quintile")
    assert first.loc[1,"mean_forward_return"] == pytest.approx(0.005)
    assert first.loc[5,"mean_forward_return"] == pytest.approx(0.085)
    assert turnover == pytest.approx(1)


def test_block_bootstrap_reproducible_and_small_sample_missing():
    values = np.sin(np.arange(200)/10)
    a = circular_block_ci(values,20,500,42)
    assert a == circular_block_ci(values,20,500,42)
    assert a[0] < np.mean(values) < a[1]
    assert circular_block_ci([0.1]*10,20,500,42) == (None,None)
    assert circular_block_ci([0.5]*100,20,100,42) == pytest.approx((0.5,0.5))
