"""Preflight tests use deterministic input shapes, not market-performance claims."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from quant_research.workflow.v4_pipeline_preflight import preflight_v4_day

DAY='2026-11-10'
SNAP='a'*64
SYMBOLS=['AAA','SPY','IWM','IWD','IWF','MTUM','QUAL']
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
        'factors':pd.DataFrame([{'date':DAY,'security_id':'AAA',
            'feature_name':'alpha','value':.12,'decision_eligible':True,
            'available_at':'2026-11-10T21:10:00Z'}]),
        'labels':pd.DataFrame([
            {'date':DAY,'security_id':'AAA','horizon':h,'label_kind':'FUTURE_UNOBSERVED',
             'gross_return':float('nan'),'excess_return':float('nan'),
             'available_at':None,
             'entry_time':'2026-11-11T14:30:00Z',
             'exit_time':str(pd.Timestamp('2026-11-13T21:00:00Z')+pd.Timedelta(days=h))}
            for h in (1,3,5)]),
        'market_style':pd.DataFrame([
            {'date':DAY,'state_available_at':'2026-11-10T21:10:00Z',
             'market_return_5':.01,'style_momentum_5':.02}]),
        'candidate_meta':pd.DataFrame([
            {'date':DAY,'security_id':'AAA','symbol':'AAA','sector':'TECH',
             'reference_close':100.,'atr20':3.,'adv20':1000000.,
             'available_at':'2026-11-10T21:14:00Z',
             'source_snapshot_sha256':SNAP}])
    },{'source_snapshot_sha256':SNAP,'source_symbols':SYMBOLS,
       'factor_names':['alpha']})


def _readiness(root,asof,*,symbols):
    # The warehouse's independently observed basket must remain fixed even
    # when a malformed bundle asks the source check to narrow its scope.
    return {'stages':{'dataset':{'status':'OBSERVATION_ONLY',
        'evidence':{'asof_date_et':DAY,'source_snapshot_sha256':SNAP,
                   'latest_session_complete':True,'symbols':SYMBOLS}}}}


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
        _check(manifest={'source_snapshot_sha256':'b'*64,'source_symbols':SYMBOLS})


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


def test_market_style_can_move_l3_signal_later_inside_close_to_open_window():
    source,_=_inputs()
    source['market_style'].loc[0,'state_available_at']='2026-11-10T21:16:00Z'
    output=_check(frames=source)
    assert output['base_signal_time']=='2026-11-10T21:15:00+00:00'
    assert output['layer_signal_time']=='2026-11-10T21:16:00+00:00'


def test_market_style_not_yet_available_at_preflight_time_is_rejected():
    source,_=_inputs()
    source['market_style'].loc[0,'state_available_at']='2026-11-10T22:01:00Z'
    with pytest.raises(ValueError,match='L3_LAYER_INPUT_NOT_YET_AVAILABLE'):
        _check(frames=source)


def test_real_source_block_prevents_any_model_admission():
    def denied(root,asof,*,symbols):
        return {'stages':{'dataset':{'status':'BLOCKED','evidence':{}}}}
    with pytest.raises(ValueError,match='REAL_SOURCE_OBSERVATION_NOT_VERIFIED'):
        _check(readiness=denied)



def test_mismatched_or_incomplete_stock_cohort_blocks(monkeypatch):
    def incomplete(root,asof,*,symbols):
        return {'stages':{'dataset':{'status':'OBSERVATION_ONLY',
            'evidence':{'asof_date_et':DAY,'source_snapshot_sha256':SNAP,
                        'latest_session_complete':False,'symbols':symbols}}}}
    with pytest.raises(ValueError,match='LATEST_SESSION_INCOMPLETE'):
        _check(readiness=incomplete)
    frames,_=_inputs()
    frames['candidate_meta'].loc[0,'symbol']='UNSEEN_STOCK'
    with pytest.raises(ValueError,match='CANDIDATE_NOT_IN_VERIFIED_SOURCE_BASKET'):
        _check(frames=frames)



def test_source_basket_must_be_verified_before_research():
    source,manifest=_inputs()
    manifest['source_symbols']=['OTHER']
    with pytest.raises(ValueError,match='SOURCE_BASKET_MISMATCH'):
        _check(manifest=manifest)
    source,manifest=_inputs()
    source['candidate_meta'].loc[0,'symbol']='OTHER'
    with pytest.raises(ValueError,match='CANDIDATE_NOT_IN_VERIFIED_SOURCE_BASKET'):
        _check(frames=source)



def test_duplicate_or_mismatched_horizon_universe_is_rejected():
    source,_=_inputs()
    source['labels']=pd.concat([source['labels'],source['labels'].iloc[[0]]],
                               ignore_index=True)
    with pytest.raises(ValueError,match='DUPLICATE_CURRENT_SECURITY_HORIZON_LABEL'):
        _check(frames=source)
    source,_=_inputs()
    source['labels'].loc[0,'security_id']='BBB'
    with pytest.raises(ValueError,match='HORIZON_SECURITY_UNIVERSE_MISMATCH'):
        _check(frames=source)


def test_candidate_must_have_matching_current_label_identity():
    source,_=_inputs()
    source['candidate_meta'].loc[0,'security_id']='UNRELATED'
    with pytest.raises(ValueError,match='CANDIDATE_MISSING_FROM_CURRENT_HORIZON_LABELS'):
        _check(frames=source)


def test_fails_closed_if_current_stock_has_missing_registered_factor():
    source,_=_inputs()
    source['factors'].loc[0,'feature_name']='different_factor'
    with pytest.raises(ValueError,match='CURRENT_FACTOR_COHORT'):
        _check(frames=source)


def test_fails_closed_if_current_factor_is_nan_or_retrospective():
    source,_=_inputs()
    source['factors'].loc[0,'value']=float('nan')
    with pytest.raises(ValueError,match='CURRENT_FACTOR_VALUE_INVALID'):
        _check(frames=source)
    source,_=_inputs()
    source['factors'].loc[0,'decision_eligible']=False
    with pytest.raises(ValueError,match='NOT_DECISION_ELIGIBLE'):
        _check(frames=source)


def test_fails_closed_if_future_label_has_leaked_availability():
    source,_=_inputs()
    source['labels'].loc[0,'available_at']='2026-11-11T21:00:00Z'
    with pytest.raises(ValueError,match='CURRENT_LABEL_OUTCOME_LEAKAGE'):
        _check(frames=source)


def test_unverified_sector_and_missing_market_style_block():
    source,_=_inputs()
    source['candidate_meta'].loc[0,'sector']='UNKNOWN'
    with pytest.raises(ValueError,match='SECTOR_UNVERIFIED'):
        _check(frames=source)
    source,_=_inputs()
    source['market_style'].loc[0,'market_return_5']=float('nan')
    with pytest.raises(ValueError,match='CONDITIONS_MISSING'):
        _check(frames=source)


def test_optional_l2_style_binding_is_reverified_before_model_fit(monkeypatch):
    from quant_research.workflow import l2_l3_binding

    source, manifest = _inputs()
    manifest["l2_style_context_receipt"] = {"placeholder": "receipt"}
    called = []

    def verify(root, market_style, receipt, *, clock=None):
        called.append((receipt, len(market_style)))
        return {
            "binding_verified": True,
            "historical_pit_attested": False,
            "context_identity_sha256": "9" * 64,
        }

    monkeypatch.setattr(l2_l3_binding, "verify_l2_style_history_binding", verify)
    output = _check(frames=source, manifest=manifest)
    assert called == [({"placeholder": "receipt"}, 1)]
    assert output["l2_style_binding_verified"] is True
    assert output["l2_style_historical_pit_attested"] is False
    assert output["l2_style_binding_context_sha256"] == "9" * 64
    assert output["real_orders_enabled"] is False


def test_invalid_l2_style_binding_blocks_preflight_before_archive(monkeypatch):
    from quant_research.workflow import l2_l3_binding

    source, manifest = _inputs()
    manifest["l2_style_context_receipt"] = {"placeholder": "forged"}

    monkeypatch.setattr(
        l2_l3_binding,
        "verify_l2_style_history_binding",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("L3_L2_STYLE_BINDING_RECEIPT_MISMATCH")
        ),
    )
    with pytest.raises(ValueError, match="STYLE_BINDING_RECEIPT_MISMATCH"):
        _check(frames=source, manifest=manifest)


def test_legacy_unbound_bundle_remains_research_only_without_binding_claim():
    output = _check()
    assert output["l2_style_binding_verified"] is False
    assert output["l2_style_historical_pit_attested"] is False
    assert output["l2_style_binding_context_sha256"] is None
