from datetime import timedelta

import numpy as np
import pandas as pd

from quant_research.clock import TradingClock
from quant_research.models.baselines import regression, probabilities
from quant_research.models.settings import load_settings
from quant_research.validation.walk_forward import training_mask


def test_purge_gap_and_label_availability():
    clock = TradingClock()
    dates = clock.calendar.sessions_in_range("2024-01-01","2024-04-01")
    test_start = dates[-1]
    signal = clock.signal(test_start)
    frame = pd.DataFrame({"date":dates,"exit_time":[clock.window(d,5).exit_time for d in dates],
        "feature_available_at":[clock.signal(d) for d in dates],"label_available_at":[clock.window(d,5).exit_time for d in dates]})
    mask = training_mask(frame,dates,test_start,signal,5,1260,True)
    assert frame.loc[mask,"date"].max()<=dates[-7]
    assert (frame.loc[mask,"exit_time"]<signal).all()
    frame.loc[0,"label_available_at"] = signal+timedelta(days=1)
    assert not training_mask(frame,dates,test_start,signal,5,1260,True).iloc[0]


def test_transform_fit_only_training_and_single_class():
    model = regression(1)
    train = pd.DataFrame({"x":[1,2,np.nan]})
    model.fit(train,[1,2,1.5])
    assert model[0].statistics_[0]==1.5
    before = model[1].mean_.copy()
    model.predict(pd.DataFrame({"x":[1e10]}))
    np.testing.assert_array_equal(model[1].mean_,before)
    config = load_settings("configs/experiments/baseline.yaml")
    p,naive,status = probabilities(train,[0,0,0],train,config)
    assert (p==0).all() and naive==0 and status=="CONSTANT_SINGLE_CLASS"
    from quant_research.models.walk_forward import evaluate_downside
    risk=pd.DataFrame({"horizon":[3,3,3],"actual_return":[-0.03,0.01,0.02],"p_downside":[0.8,0.1,0.1],"naive_p_downside":[1/3]*3})
    metrics=evaluate_downside(risk,-0.02)
    assert np.isclose(metrics.brier.iloc[0],0.02)
    assert metrics.log_loss.iloc[0]<metrics.naive_log_loss.iloc[0]
