"""Preflight tests use deterministic input shapes, not market-performance claims."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from quant_research.workflow.v4_pipeline_preflight import preflight_v4_day

DAY='2026-11-10'
SNAP='a'*64
NOW=datetime.fromisoformat('2026-11-10T22:00:00+00:00')


class Clock:
    def session(self,day):
        assert str(day)[:10]==DAY
        return pd.Timestamp(DAY)

    def window(self,day,horizon,now):
        assert horizon in (1,3,5)
        return SimpleNamespace(
            signal_time=pd.Timestamp('2026-11-10T21:15:00Z'),
            entry_time=pd.Timestamp('2026-11-11T14:30:00Z'),
            exit_time=pd.Timestamp('2026-11-13T21:00:00Z')+pd.Timedelta(days=horizon))


def _inputs():
    return ({
        'factors':pd.DataFrame([{'date':DAY,'available_at':'2026-11-10T21:10:00Z'}]),
        'labels':pd.DataFrame([
            {'date':DAY,'horizon':h,'label_kind':'FUTURE_UNOBSERVED',
             'gross_return':float('nan'),'excess_return':float('nan'),
             'entry_time':'2026-11-11T14:30:00Z',
             'exit_time':str(pd.Timestamp('2026-11-13T21:00:00Z')+pd.Timedelta(days=h))}
            for h in (1,3,5)]),
        'market_style':pd.DataFrame([
            {'date':DAY,'state_available_at':'2026-11-10T21:10:00Z'}]),
        'candidate_meta':pd.DataFrame([
            {'date':DAY,'security_id':'AAA','symbol':'AAA','sector':'TECH',
             'reference_close':100.,'atr20':3.,'adv20':1000000.,
             'available_at':'2026-11-10T21:14:00Z',
             'source_snapshot_sha256':SNAP}])
    },{'source_snapshot_sha256':SNAP})


def _readiness(root,asof):
    return {'stages':{'dataset':{'status':'OBSERVATION_ONLY',
        'evidence':{'asof_date_et':DAY,'source_snapshot_sha256':SNAP}}}}


def _check(frames=None,manifest=None,readiness=None,now=NOW):
    source,meta=_inputs()
    return preflight_v4_day(Path('/tmp'),DAY,'bundle',now_utc=now,
        checked_inputs=lambda root,bid:(source if frames is None else frames,
                                        meta if manifest is None else manifest),
        readiness_fn=readiness or _readiness,clock=Clock())


def test_observed_source_and_unknown_future_are_required():
    output=_check()
    assert output['status']=='PREFLIGHT_SOURCE_AND_TIME_MATCH_RESEARCH_ONLY'
    assert output['checked_candidate_rows']==1
    assert output['checked_forward_label_rows']==3
    assert output['real_orders_enabled'] is False
    assert output['historical_pit_attested'] is False


def test_t_date_future_return_does_not_enter_forecast():
    source,_=_inputs()
    source['labels'].loc[0,'gross_return']=.99
    with pytest.raises(ValueError,match='FUTURE_LABEL_LEAKAGE'):
        _check(frames=source)


def test_source_digest_must_match_current_real_warehouse():
    with pytest.raises(ValueError,match='BUNDLE_DIFFERS_FROM_LIVE_WAREHOUSE'):
        _check(manifest={'source_snapshot_sha256':'b'*64})


def test_premarket_and_post_entry_window_both_fail_before_archive():
    for stamp in ('2026-11-10T21:05:00+00:00','2026-11-11T14:31:00+00:00'):
        with pytest.raises(ValueError,match='NOT_IN_T_CLOSE_TO_NEXT_OPEN_WINDOW'):
            _check(now=datetime.fromisoformat(stamp))


def test_all_three_horizons_and_on_time_metadata_required():
    source,_=_inputs()
    source['labels']=source['labels'].iloc[:2]
    with pytest.raises(ValueError,match='MISSING_ALL_CURRENT_HORIZON'):
        _check(frames=source)
    source,_=_inputs()
    source['candidate_meta'].loc[0,'available_at']='2026-11-10T21:16:00Z'
    with pytest.raises(ValueError,match='NOT_KNOWN_AS_OF_T'):
        _check(frames=source)


def test_market_style_must_be_known_by_signal_cutoff():
    source,_=_inputs()
    source['market_style'].loc[0,'state_available_at']='2026-11-10T21:16:00Z'
    with pytest.raises(ValueError,match='MARKET_STYLE_NOT_KNOWN'):
        _check(frames=source)


def test_real_source_block_prevents_any_model_admission():
    def denied(root,asof):
        return {'stages':{'dataset':{'status':'BLOCKED','evidence':{}}}}
    with pytest.raises(ValueError,match='REAL_SOURCE_OBSERVATION_NOT_VERIFIED'):
        _check(readiness=denied)
