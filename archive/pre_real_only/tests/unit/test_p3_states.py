import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.pipeline import fixture_records
from quant_research.features.context import make_context
from quant_research.features.states import frozen_states, observations


def test_state_formulas_threshold_freeze_and_availability():
    records,_ = fixture_records(TradingClock(),"2020-01-01","2021-03-01")
    context = make_context(pd.DataFrame([r.model_dump() for r in records]),TradingClock())
    observed = observations(context)
    states,thresholds = frozen_states(observed,"2020-12-31")
    ratio = context.close["SYNTH-IWM"]/context.close["SYNTH-SPY"]
    assert np.isclose(observed.style_small_relative_return_5d.iloc[-1],ratio.iloc[-1]/ratio.iloc[-6]-1)
    changed = observed.copy()
    changed.loc[changed.index>"2020-12-31","market_vol_20"] *= 100
    _,again = frozen_states(changed,"2020-12-31")
    assert thresholds==again
    assert states.threshold_available_at.iloc[0]>=pd.Timestamp("2020-12-31",tz="UTC")
    assert set(states.style_small_state.unique())<={"UNKNOWN","强势加速","强势减速","弱势改善","弱势恶化"}
    before = observed.loc[:"2020-12-31"].copy()
    for panel in context.panels.values():
        panel.loc[panel.index>"2020-12-31",:] *= 9
    pd.testing.assert_frame_equal(before,observations(context).loc[:"2020-12-31"])
