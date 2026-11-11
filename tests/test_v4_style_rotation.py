"""Style tests are causal arithmetic fixtures, not historical performance."""
import numpy as np
import pandas as pd
import pytest

from quant_research.research.v4_style_rotation import style_observations,style_lead_oos


def _fixture():
    sessions=pd.bdate_range('2024-01-02',periods=170)
    ix=np.arange(len(sessions),dtype=float)
    values=pd.DataFrame({'IWM':100+ix*.12+np.sin(ix*.23),
                         'SPY':120+ix*.10+np.sin(ix*.17),
                         'IWD':100+ix*.15,'IWF':110+ix*.10},index=sessions)
    availability=pd.DataFrame({
        s:pd.to_datetime(sessions,utc=True)+pd.Timedelta(hours=21)
        for s in values.columns},index=sessions)
    return sessions,values,availability


def test_style_features_require_21_known_sessions_and_use_no_future_prices():
    sessions,prices,availability=_fixture()
    features=style_observations(prices,availability)
    assert set(features.style_id)=={'small','value'}
    small=features.loc[features.style_id.eq('small')].reset_index(drop=True)
    assert small.relative_return_20d.iloc[:20].isna().all()
    assert small.relative_return_20d.iloc[21:].notna().all()
    changed=prices.copy()
    changed.iloc[-1,:]=changed.iloc[-1,:]*100
    recomputed=style_observations(changed,availability)
    pd.testing.assert_frame_equal(features.loc[features.date.lt(sessions[-1])].reset_index(drop=True),
                                  recomputed.loc[recomputed.date.lt(sessions[-1])].reset_index(drop=True))


def test_style_lead_predictions_stay_nonexecuting_and_pit_restricted():
    sessions,prices,availability=_fixture()
    features=style_observations(prices,availability)
    records=[]
    for day_i, day in enumerate(sessions):
        for style in ('small','value'):
            for h in (1,3,5):
                signal=pd.Timestamp(day).tz_localize('UTC')+pd.Timedelta(hours=22)
                records.append({'date':day,'style_id':style,'horizon':h,
                    'signal_time':signal,'forward_relative_return':[.008,-.006,.012][day_i%3],
                    'label_available_at':signal+pd.Timedelta(days=h+2),
                    'label_kind':'VERIFIED_RAW_RELATIVE_RETURN'})
    labels=pd.DataFrame(records)
    out=style_lead_oos(features,labels,sessions,sessions[-20:],min_training_sessions=35)
    assert not out.empty
    assert not out.decision_eligible.any()
    assert set(out.style_id)=={'small','value'}
    labels['label_kind']='EXPLORATORY_ETF_PRICE_PROXY'
    with pytest.raises(ValueError,match='proxy'):
        style_lead_oos(features,labels,sessions,sessions[-20:],min_training_sessions=35)
