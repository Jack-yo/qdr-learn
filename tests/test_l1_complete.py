"""Deterministic synthetic contracts. No claim of real trading or model advantage."""
from datetime import timedelta
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from quant_research.research.l1_features import DOMAINS,REGISTRY,add_l1_features,domain_status,scan_all_l1_anomalies
from quant_research.research.l1_observatory import compute_l1_observations
from quant_research.research.l1_models import (L1Protocol,first_touch_label,make_l1_labels,
    run_l1_oos,score_l1_oos,forecast_l1_research)
from quant_research.workflow.l1_runtime import (build_l1_research,market_overview_for_api,
    observations_for_api,validation_for_api,replay_for_api,L1Blocked)


def fixture(n=390):
    dates=pd.bdate_range('2022-01-03',periods=n)
    rng=np.random.default_rng(44)
    daily=rng.normal(.0005,.012,n)
    daily[::11]=rng.normal(0,.025,len(daily[::11]))
    close=100*np.exp(np.cumsum(daily))
    opens=close*np.exp(-daily*.45)
    rows=[]
    for k,symbol in enumerate(['SPY','RSP','HYG','LQD','IWM','XLK','XLF','XLE','XLV','XLI','XLP','XLY']):
        for i,d in enumerate(dates):
            c=float(close[i]*(1+k*.001)+k*.01)
            o=float(opens[i]*(1+k*.001)+k*.01)
            rows.append({'date':d,'symbol':symbol,'security_id':symbol,'open':o,
                         'close':c,'high':max(o,c)*1.012,'low':min(o,c)*.988,
                         'volume':int(1_000_000+i*500+k),
                         'available_at':(d+pd.Timedelta(hours=21)).isoformat()+'Z'})
    clock=pd.DataFrame({'date':dates,'decision_cutoff_utc':[(d+pd.Timedelta(hours=22)).isoformat()+'Z' for d in dates]})
    return pd.DataFrame(rows),clock


def test_first_touch_labels_and_intrabar_ambiguity():
    bar=pd.DataFrame([{'open':100,'high':101,'low':99,'close':100},
                      {'open':100,'high':103,'low':97,'close':101},
                      {'open':101,'high':101.5,'low':100,'close':101}])
    assert first_touch_label(bar,0,2,.02,.02)=='AMBIGUOUS'
    bar.loc[1,'low']=99
    assert first_touch_label(bar,0,2,.02,.02)=='UP'
    bar.loc[1,'high']=101
    assert first_touch_label(bar,0,2,.02,.02)=='NEITHER'


def test_ewma_benchmark_is_recursive_daily_return_variance():
    from quant_research.research.l1_models import _ewma_rv
    values=pd.Series([.01,.02,0.0])
    expected=252*(.94*(.94*.01**2+.06*.02**2)+.06*0.0)
    assert _ewma_rv(values)==pytest.approx(expected**.5)


def test_l1_feature_registry_and_optional_lateness():
    bars,clock=fixture(50)
    base,_=compute_l1_observations(bars,clock)
    assert len(DOMAINS)==12 and len(REGISTRY)>45
    day=clock.date.iloc[-1]
    features=pd.DataFrame([{'feature_id':'vix_30d','date':day,'value':25,
       'available_at':(day+pd.Timedelta(hours=23)).isoformat()+'Z',
       'source':'licenced','source_snapshot_sha256':'a'*64,'source_attested':True}])
    out,audit=add_l1_features(base,bars,clock,optional=features)
    assert np.isnan(out.iloc[-1].vix_30d)
    assert audit.loc[(audit.feature=='vix_30d')&audit.date.eq(day),'status'].iloc[0]=='BLOCKED'
    d=domain_status(out,audit)
    assert len(d)==12
    assert next(x for x in d if x['id']=='options_positioning')['status']=='MISSING'
    features.loc[0,'available_at']=(day+pd.Timedelta(hours=20)).isoformat()+'Z'
    out,audit=add_l1_features(base,bars,clock,optional=features)
    assert out.iloc[-1].vix_30d==25


def test_stock_dispersion_uses_daily_members_and_requires_consecutive_bars():
    bars, clock = fixture(30)
    stocks = []
    membership = []
    for i in range(30):
        symbol = f'STOCK{i}'
        for j, day in enumerate(clock.date):
            close = 100 * (1 + i * .0001) ** j
            stocks.append({'date': day, 'symbol': symbol, 'security_id': symbol,
                           'open': close, 'high': close, 'low': close, 'close': close,
                           'volume': 1000, 'available_at': (day + pd.Timedelta(hours=21)).isoformat()+'Z'})
            membership.append({'date': day, 'security_id': symbol, 'is_member': True,
                               'available_at': (day + pd.Timedelta(hours=20)).isoformat()+'Z'})
    bars = pd.concat([bars, pd.DataFrame(stocks)], ignore_index=True)
    universe = pd.DataFrame(membership)
    base, _ = compute_l1_observations(bars, clock, universe)
    features, _ = add_l1_features(base, bars, clock, universe=universe)
    assert features.stock_dispersion_1.iloc[-1] == pytest.approx(np.std(np.arange(30)*.0001))
    without_universe, _ = add_l1_features(base, bars, clock)
    assert without_universe.stock_dispersion_1.isna().all()


def test_sector_five_day_dispersion_does_not_require_twenty_days():
    bars, clock = fixture(10)
    base, _ = compute_l1_observations(bars, clock)
    features, _ = add_l1_features(base, bars, clock)
    assert features.sector_dispersion_5.iloc[:5].isna().all()
    assert features.sector_dispersion_5.iloc[5:].notna().all()
    assert features.sector_corr_20.isna().all()


def test_single_snapshot_audit_never_claims_history_or_model(tmp_path, monkeypatch):
    from quant_research.workflow import l1_snapshot_audit
    bars, clock = fixture(1)
    day = str(clock.date.iloc[0].date())
    snapshot = {'rows': bars.to_dict('records'), 'frozen_at_utc': clock.decision_cutoff_utc.iloc[0],
                'source': 'TEST', 'feed': 'TEST', 'source_snapshot_sha256': 'a'*64}
    monkeypatch.setattr(l1_snapshot_audit, 'read_snapshot', lambda root, asof: snapshot)
    result = l1_snapshot_audit.audit_snapshot(tmp_path, day, tmp_path/'audit')
    assert result['sessions'] == 1 and result['historical_pit_verified'] is False
    assert result['model_admitted'] is False
    coverage = pd.read_csv(tmp_path/'audit'/'feature_coverage.csv')
    assert len(coverage) == len(REGISTRY) and not coverage.research_eligible.any()


def test_l1_models_purge_forecast_and_metric_contract():
    bars,clock=fixture()
    base,_=compute_l1_observations(bars,clock)
    features,_=add_l1_features(base,bars,clock)
    protocol=L1Protocol(min_train_sessions=80,calibration_sessions=25,refit_every=40)
    panel=make_l1_labels(bars,features,clock,protocol)
    assert panel.loc[panel.horizon.eq(5),'gross_price_return'].notna().any()
    oos=run_l1_oos(bars,features,clock,protocol,evaluation_start='2023-01-03')
    assert not oos.empty and set(oos.horizon)=={1,3,5}
    assert (oos.train_last_date < oos.date).all()
    assert (oos.train_last_label_available_at <= oos.signal_cutoff_utc).all()
    assert oos.research_only.all()
    for q in oos.e03_quantiles:
        assert len(q)==5 and list(q)==sorted(q)
    metrics=score_l1_oos(oos,protocol)
    assert len(metrics)==3 and metrics.research_only.all()
    assert not metrics.model_admitted.any()
    f=forecast_l1_research(bars,features,clock,protocol)
    assert f['trade_eligible'] is False and len(f['horizons'])==3


def test_default_oos_evaluates_each_eligible_session():
    bars,clock=fixture(115)
    base,_=compute_l1_observations(bars,clock)
    features,_=add_l1_features(base,bars,clock)
    protocol=L1Protocol(min_train_sessions=80,calibration_sessions=25)
    result=run_l1_oos(bars,features,clock,protocol,evaluation_start=clock.date.iloc[-8])
    h1=result.loc[result.horizon.eq(1),'date']
    assert list(h1)==list(clock.date.iloc[-8:-1])


def test_archive_api_and_tamper_block(tmp_path):
    bars,clock=fixture()
    bars_file=tmp_path/'bars.csv';clock_file=tmp_path/'clock.csv'
    bars.to_csv(bars_file,index=False);clock.to_csv(clock_file,index=False)
    out=tmp_path/'outputs'/'l1_research'/'synthetic-01'
    proto=L1Protocol(min_train_sessions=80,calibration_sessions=25,refit_every=60)
    manifest=build_l1_research(bars=bars_file,cutoffs=clock_file,output=out,
                               protocol=proto,evaluation_start='2023-01-03')
    assert manifest['status']=='RETROSPECTIVE_RESEARCH_ONLY'
    coverage=pd.read_csv(out/'feature_coverage.csv')
    assert len(coverage)==len(REGISTRY)
    assert not coverage.research_eligible.any()
    assert set(coverage.PIT_status)=={'NOT_INDEPENDENTLY_VERIFIED'}
    response=market_overview_for_api(tmp_path,3)
    assert response['schema']=='qdr.l1.market.v1' and response['forecast'] is None
    assert len(response['domains'])==12 and response['status']=='OBSERVATION_ONLY'
    assert len(response['features'])==len(REGISTRY)
    assert all(x['research_only'] for x in response['features'])
    assert validation_for_api(tmp_path)['model_admitted'] is False
    assert replay_for_api(tmp_path,clock.date.iloc[-1],3)['status']=='NO_OOS_PREDICTION'
    (out/'features.csv').write_text('bad',encoding='utf8')
    with pytest.raises(L1Blocked,match='HASH_MISMATCH'):
        market_overview_for_api(tmp_path,3)


def test_replay_blocks_missing_outcome_instead_of_returning_nan(tmp_path, monkeypatch):
    from quant_research.workflow import l1_runtime
    day=pd.Timestamp('2024-01-03')
    pd.DataFrame([{'date':day,'horizon':3,'e03_expected_return':.01,
                   'target_return':None,'e01_rv_model':.2,
                   'target_forward_rv':.3,'target_first_touch':'NEITHER'}]).to_csv(
                       tmp_path/'oos_predictions.csv',index=False)
    monkeypatch.setattr(l1_runtime,'_recent_audit',lambda root,asof: (tmp_path,{},day,None,None))
    result=l1_runtime.replay_for_api(tmp_path,str(day.date()),3)
    assert result['status']=='INSUFFICIENT_OUTCOME_DATA' and result['prediction'] is None


def test_optional_raw_math_and_event_cutoff():
    from quant_research.research.l1_derived_sources import (
       derive_snapshot,option_interest_concentration,dealer_gamma_scenario,
       validate_event_calendar,raw_packets_to_optional)
    d=derive_snapshot({'vix_30d':25,'vix_90d':23,'put_25_delta_iv':.33,
                      'call_25_delta_iv':.25,'quoted_bid':100,'quoted_ask':100.1,
                      'book_bid_size':200,'book_ask_size':100},rv20=.20)
    assert d['vix_term_30_90']>0 and d['put_25d_iv_minus_call']==pytest.approx(.08)
    assert d['quoted_spread_bps']>0 and d['implied_minus_realized_var']==pytest.approx(.0225)
    opt=pd.DataFrame({'expiry':['a','a','b'],'strike':[100,100,110],'open_interest':[10,20,30]})
    assert option_interest_concentration(opt)['oi_expiry_concentration']==.5
    with pytest.raises(ValueError,match='signed contracts'):
        dealer_gamma_scenario(opt,spot=100)
    known=pd.DataFrame([{'event_id':'fomc','scheduled_at':'2024-03-05T20:00:00Z',
                         'schedule_known_at':'2024-01-01T00:00:00Z','event_type':'meeting'},
                        {'event_id':'future','scheduled_at':'2024-04-01T20:00:00Z',
                         'schedule_known_at':'2024-03-09T00:00:00Z','event_type':'meeting'}])
    assert len(validate_event_calendar(known,pd.Timestamp('2024-03-01T23:00:00Z')))==1
    bars,clock=fixture(30);obs,_=compute_l1_observations(bars,clock)
    day=clock.date.iloc[-1]
    raw=pd.DataFrame([{'date':day,'metric_name':name,'value':value,
       'available_at':(day+pd.Timedelta(hours=20)).isoformat()+'Z',
       'source':'example','source_snapshot_sha256':'a'*64,'source_attested':True}
       for name,value in [('vix_30d',25),('vix_90d',23)]])
    packet=raw_packets_to_optional(raw,clock,obs)
    assert set(packet.feature_id)>={'vix_30d','vix_term_30_90'}


def test_forward_freeze_is_research_only_and_tamper_evident(tmp_path):
    from types import SimpleNamespace
    from quant_research.workflow.l1_forward import freeze_l1_research,read_l1_frozen
    bars,clock=fixture();obs,_=compute_l1_observations(bars,clock)
    date=str(clock.date.iloc[-1].date())
    class Clock:
        def signal(self,day):return pd.Timestamp(day,tz='UTC')+pd.Timedelta(hours=22)
        def window(self,day,h):return SimpleNamespace(entry_time=pd.Timestamp(day,tz='UTC')+pd.Timedelta(days=1,hours=14))
    instant=pd.Timestamp(date,tz='UTC')+pd.Timedelta(hours=23)
    protocol=L1Protocol(min_train_sessions=80,calibration_sessions=25,refit_every=40)
    frozen=freeze_l1_research(bars=bars,observations=obs,cutoffs=clock,
        output_root=tmp_path,source_snapshot_sha256='a'*64,asof=date,
        now_utc=instant,clock=Clock(),protocol=protocol)
    assert frozen['status']=='FROZEN_FORWARD_RESEARCH_ONLY'
    assert len(frozen['forecasts'])==3 and frozen['model_admitted'] is False
    assert all(x['probability_calibration_status']=='NOT_CALIBRATED_RESEARCH_ONLY' for x in frozen['forecasts'])
    identities=list((tmp_path/'outputs/l1_frozen'/date).iterdir())
    assert len(identities)==1
    assert read_l1_frozen(tmp_path,date,identities[0].name)==frozen
    (identities[0]/'forecast.json').write_text('{}',encoding='utf8')
    with pytest.raises(ValueError,match='INVALID'):
        read_l1_frozen(tmp_path,date,identities[0].name)
    from hashlib import sha256
    manifest_path=identities[0]/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf8'))
    manifest['forecast_sha256']=sha256(b'{}').hexdigest()
    manifest_path.write_text(json.dumps(manifest),encoding='utf8')
    with pytest.raises(ValueError,match='IDENTITY_MISMATCH'):
        read_l1_frozen(tmp_path,date,identities[0].name)
    with pytest.raises(ValueError,match='OUTSIDE_REAL_FORWARD_FREEZE_WINDOW'):
        freeze_l1_research(bars=bars,observations=obs,cutoffs=clock,
           output_root=tmp_path,source_snapshot_sha256='a'*64,asof=date,
           now_utc=instant-pd.Timedelta(hours=2),clock=Clock(),protocol=protocol)
    late_clock=clock.copy()
    late_clock.loc[late_clock.index[-1], 'decision_cutoff_utc']=(instant+pd.Timedelta(minutes=30)).isoformat()
    with pytest.raises(ValueError,match='ASOF_CUTOFF_OUTSIDE_FREEZE_WINDOW'):
        freeze_l1_research(bars=bars,observations=obs,cutoffs=late_clock,
           output_root=tmp_path,source_snapshot_sha256='a'*64,asof=date,
           now_utc=instant,clock=Clock(),protocol=protocol)
    late_clock.loc[late_clock.index[-1], 'decision_cutoff_utc']=(instant-pd.Timedelta(minutes=10)).isoformat()
    delayed=freeze_l1_research(bars=bars,observations=obs,cutoffs=late_clock,
        output_root=tmp_path,source_snapshot_sha256='a'*64,asof=date,
        now_utc=instant,clock=Clock(),protocol=protocol)
    assert pd.Timestamp(delayed['knowledge_cutoff_utc'])==instant-pd.Timedelta(minutes=10)


def test_all_dimensions_anomaly_scan_past_only():
    bars,clock=fixture(125)
    base,_=compute_l1_observations(bars,clock)
    extra,_=add_l1_features(base,bars,clock)
    extra['market_vol_5']=0.20
    extra.loc[len(extra)-1,'market_vol_5']=2.0
    found=scan_all_l1_anomalies(extra,lookback=80,min_history=40,z_limit=3)
    # Constant historical values produce no finite z-score (std=0),
    # never a fabricated infinitely significant alert.
    assert not found.feature.eq('market_vol_5').any()
    # For a real, variable history, a final extreme must be detected,
    # while changing the final observation cannot alter earlier alerts.
    rng=np.random.default_rng(17)
    extra['market_vol_5']=rng.normal(.2,.02,len(extra))
    extra.loc[len(extra)-1,'market_vol_5']=2
    found=scan_all_l1_anomalies(extra,lookback=80,min_history=40,z_limit=3)
    assert found.feature.eq('market_vol_5').any()
    changed=extra.copy();changed.loc[len(extra)-1,'market_vol_5']=10
    other=scan_all_l1_anomalies(changed,lookback=80,min_history=40,z_limit=3)
    assert found.loc[found.date.lt(extra.date.max())].feature.tolist()==other.loc[other.date.lt(extra.date.max())].feature.tolist()
    assert set(found.status)=={'OBSERVATION_ONLY'}
