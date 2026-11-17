"""Isolated deterministic tests, NEVER accepted as a market-data or prediction audit."""
from datetime import datetime,timezone,timedelta
import json
import numpy as np
import pandas as pd
import pytest
from quant_research.data.l1_light_sources import BoundedCache, LiveSources, SourceUnavailable
from quant_research.workflow.l1_v2 import analyze_market, _event_targets, build_scores


def market(seed=5,days=335):
    rng=np.random.default_rng(seed)
    dates=pd.bdate_range('2024-01-02', periods=days)
    raw={}
    symbols=list(LiveSources.ETF_SYMBOLS)
    common=rng.normal(.0002,.012,days)
    for j,sym in enumerate(symbols):
        prices=100*np.exp(np.cumsum(common*(.68 if sym in ['HYG','LQD','TLT','SHY'] else 1)+rng.normal(0,.004,days)))
        arr=[]
        for i,date in enumerate(dates):
            c=float(prices[i]);o=float(c*(1+rng.normal(0,.003)));h=max(o,c)*1.007;lo=min(o,c)*.993
            arr.append({'date':date.strftime('%Y-%m-%d'),'symbol':sym,'open':o,'high':h,'low':lo,
                        'close':c,'volume':float(100000+j*100)})
        raw[sym]=arr
    return pd.DataFrame([r for rows in raw.values() for r in rows])


def test_bounded_cache_expiration_and_corruption(tmp_path):
    moment=datetime(2026,11,14,tzinfo=timezone.utc)
    c=BoundedCache(tmp_path,now=lambda:moment,max_entries=2)
    k=c.identity('https://data.alpaca.markets/v2/stocks/bars',{'symbols':'SPY','api_key':'SHOULD_NOT_PERSIST'})
    c.put(k,b'{"hello":true}')
    assert c.get(k,60)[0]==b'{"hello":true}'
    assert c.get(k,0) is None
    p=c.root/(k+'.json');s=p.read_text().replace('68656c6c6f','68656c6c60');p.write_text(s)
    assert c.get(k,60) is None
    assert 'SHOULD_NOT_PERSIST' not in p.read_text()


def test_missing_credentials_fail_closed(tmp_path):
    s=LiveSources(tmp_path,env={})
    with pytest.raises(SourceUnavailable,match='MISSING_ALPACA_CREDENTIALS'):s.bars()


def test_live_provider_fetch_and_reuse_cache(tmp_path):
    calls=[]
    def get(url,headers):
        calls.append((url,headers))
        return json.dumps({'bars':{'SPY':[{'t':'2026-11-13T05:00:00Z','o':100,'h':103,'l':99,'c':102,'v':1}]},'next_page_token':None}).encode()
    source=LiveSources(tmp_path,fetch=get,env={'ALPACA_API_KEY':'test','ALPACA_SECRET_KEY':'private'})
    a,r=source.bars(symbols=['SPY']);b,r2=source.bars(symbols=['SPY'])
    assert a==b and len(calls)==1
    assert r[0]['sha256']==r2[0]['sha256']
    assert all('test' not in url and 'private' not in url for url,_ in calls)


@pytest.mark.parametrize('instant, expected_end',[
    (datetime(2026,11,14,12,tzinfo=timezone.utc),'2026-11-13T21:01:00+00:00'),
    (datetime(2026,11,27,19,tzinfo=timezone.utc),'2026-11-27T18:01:00+00:00'),
])
def test_delayed_snapshot_feed_uses_completed_sip_bars(tmp_path,instant,expected_end):
    from urllib.parse import urlsplit,parse_qs
    seen=[]
    def fetch(url,headers):
        seen.append(parse_qs(urlsplit(url).query))
        return json.dumps({'bars':{'SPY':[{'t':expected_end[:10]+'T05:00:00Z'}]},'next_page_token':None}).encode()
    source=LiveSources(tmp_path,fetch=fetch,now=lambda:instant,
        env={'ALPACA_API_KEY':'test','ALPACA_SECRET_KEY':'private','QDR_L1_FEED':'delayed_sip'})
    _,receipts=source.bars(symbols=['SPY'])
    assert seen[0]['feed']==['sip']
    assert seen[0]['end']==[expected_end]
    assert receipts[0]['feed']=='sip'


@pytest.mark.parametrize('wrapped',[False,True])
def test_alpaca_snapshots_accept_direct_and_wrapped_responses(tmp_path,wrapped):
    actual={'SPY':{'latestTrade':{'p':100.0},'latestQuote':{'bp':99.9,'ap':100.1}}}
    payload={'snapshots':actual} if wrapped else actual
    source=LiveSources(tmp_path,fetch=lambda url,headers:json.dumps(payload).encode(),
        env={'ALPACA_API_KEY':'test','ALPACA_SECRET_KEY':'private'})
    result,receipt=source.snapshots(symbols=('SPY',))
    assert result==actual and receipt['source']=='ALPACA_delayed_sip'


def test_cboe_current_canonical_csv_source(tmp_path):
    calls=[]
    def fetch(url,headers):
        calls.append(url)
        return b'DATE,OPEN,HIGH,LOW,CLOSE\n11/13/2026,20,22,19,21\n'
    values,receipt=LiveSources(tmp_path,fetch=fetch,env={}).cboe_vix()
    assert calls==['https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv']
    assert values['2026-11-13']==21 and receipt['pit']=='CURRENT_VINTAGE'


def test_web_startup_loads_local_credentials_without_printing_them(tmp_path,monkeypatch,capsys):
    import os
    from quant_research import web
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs'/'sources.yaml').write_text('{}',encoding='utf-8')
    env_file=tmp_path/'local.env'
    env_file.write_text('ALPACA_API_KEY=test-key\nALPACA_SECRET_KEY=test-secret\n',encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('ALPACA_API_KEY',raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY',raising=False)
    seen={}
    def make_console(*args):
        seen['key']=os.environ.get('ALPACA_API_KEY')
        seen['secret']=os.environ.get('ALPACA_SECRET_KEY')
        return object()
    class Server:
        def __init__(self,*args):self.server_port=8766
        def serve_forever(self):pass
        def server_close(self):pass
    monkeypatch.setattr(web,'Console',make_console)
    monkeypatch.setattr(web,'handler',lambda console:object())
    monkeypatch.setattr(web,'LocalConsoleServer',Server)
    web.main(['--env-file',str(env_file),'--port','8766'])
    assert seen=={'key':'test-key','secret':'test-secret'}
    output=capsys.readouterr().out
    assert 'test-key' not in output and 'test-secret' not in output


def test_twelve_domains_important_proxy_names():
    result=analyze_market(market(),receipts=[{'feed':'delayed_sip','fetched_at':'2026-11-14T03:00:00Z'}])
    assert len(result['domains'])==12
    assert result['schema']=='qdr.l1.v2'
    assert result['scores']['sell_pressure'] is not None
    assert result['historical_pit_verified'] is False
    names={x['id']:x for x in result['domains']}
    assert names['breadth']['status']=='PARTIAL'
    assert 'ETF代理' in names['breadth']['reason']
    assert names['options_positioning']['status']=='MISSING'
    assert names['price']['status']=='OBSERVED'


def test_conditional_is_past_only_and_no_false_admission():
    b=market()
    orig=analyze_market(b,receipts=[])
    maxdate=b.date.max()
    changed=b.copy();changed.loc[changed.date==maxdate,'high']*=1.3
    changed.loc[changed.date==maxdate,'low']*=.5
    result=analyze_market(changed,receipts=[])
    assert orig['status']=='OBSERVATION_ONLY'
    assert all(x['validation']['status'] in {'INSUFFICIENT_OOS','RETROSPECTIVE_EXPLORATORY'} for x in result['horizons'].values())
    assert all(x['reliability']=='NOT_CALIBRATED_NOT_PIT_VALIDATED' for x in result['horizons'].values())
    assert all(x['validation'].get('qualified',False) is False for x in orig['horizons'].values())


def test_double_touch_is_ambiguous():
    b=market()
    features,cl,op,hi,lo=build_scores(b)
    current=len(cl)-5
    hi.loc[cl.index[current+1],'SPY']=op['SPY'].iloc[current+1]*1.04
    lo.loc[cl.index[current+1],'SPY']=op['SPY'].iloc[current+1]*.94
    assert _event_targets(cl,op,hi,lo,current,3)[1]=='AMBIGUOUS'


def test_history_cutoff_cannot_see_future():
    b=market();cut=b.date.unique()[-9]
    old=analyze_market(b[b.date<=cut],receipts=[],asof_limit=cut)
    new=analyze_market(b,receipts=[],asof_limit=cut)
    assert old['scores']==new['scores']
    assert old['horizons']==new['horizons']


def test_missing_important_etf_blocks():
    b=market();b=b[b.symbol!='HYG']
    with pytest.raises(SourceUnavailable,match='MARKET_CORE_SYMBOLS_MISSING'):
        analyze_market(b,receipts=[])


def test_daily_monitor_marks_stale_bars_without_changing_frozen_research(tmp_path):
    """A previously valid batch must not be presented as the newest closed session."""
    from quant_research.workflow.l1_v2 import current_l1_v2

    table=market()
    rows={}
    for item in table.itertuples(index=False):
        rows.setdefault(item.symbol,[]).append({
            "t":item.date+"T05:00:00Z","o":item.open,"h":item.high,
            "l":item.low,"c":item.close,"v":item.volume
        })

    class StubSources:
        env={}
        def bars(self, **kwargs):
            return rows,[{"feed":"sip","fetched_at":"2025-04-15T22:00:00Z"}]
        def snapshots(self, **kwargs):
            raise SourceUnavailable("SNAPSHOT_UNAVAILABLE")
        def cboe_vix(self, **kwargs):
            raise SourceUnavailable("CBOE_UNAVAILABLE")

    result=current_l1_v2(tmp_path,sources=StubSources(),
                         now=datetime(2025,5,10,22,tzinfo=timezone.utc))
    assert result["asof_session"] < result["expected_asof_session"]
    assert result["data_freshness"]=="STALE_COMPLETED_SESSION"
