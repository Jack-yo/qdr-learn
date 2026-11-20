"""Immutable lab lifecycle and diagnostics computed from actual cached Yahoo/SIP rows."""
import json
from pathlib import Path
import shutil

import pandas as pd
import pytest

from quant_research.policy import PolicyError
from quant_research.research.factor_lab import Registry,FactorSpec
from quant_research.workflow.factor_lab import run,result,compare,preview


@pytest.fixture(scope='module')
def project(tmp_path_factory):
    root=tmp_path_factory.mktemp('real-factor-lab')
    config=root/'configs/experiments';config.mkdir(parents=True)
    shutil.copyfile('configs/experiments/p2_factors.yaml',config/'p2_factors.yaml')
    return root


@pytest.fixture(scope='module')
def real_runs(project):
    if not Path('data/research.duckdb').is_file():pytest.skip('BLOCKED_REAL_YAHOO_STORE_MISSING')
    registry=Registry(project)
    v1=registry.create_factor({'name':'real-reversal','template':'reversal','window':5,'direction':1})
    v2=registry.create_factor({**v1['config'],'window':10,'parent_version_id':v1['id']})
    experiments=[]
    for version in (v1,v2):
        exp=registry.create_experiment({'factor_version_id':version['id'],'source':'yahoo'})
        record=run(project,exp['id'],data_root=Path.cwd())
        assert record['status']=='COMPLETED',record.get('error')
        experiments.append(exp['id'])
    return registry,v1,v2,experiments


@pytest.mark.parametrize('body',[
    {'name':'x','template':'reversal','window':-1},
    {'name':'x','template':'reversal','window':True},
    {'name':'x','template':'volatility','window':1},
    {'name':'x','template':'reversal','window':5,'expression':'__import__("os")'},
    {'name':'x/../../escape','template':'reversal','window':5},
])
def test_unreviewed_code_negative_windows_and_bad_names_rejected(body):
    with pytest.raises(ValueError):FactorSpec.model_validate(body)


def test_versions_are_copied_and_old_definition_is_unchanged(real_runs):
    registry,v1,v2,_=real_runs
    assert registry.factor(v1['id'])['config']['window']==5 and v2['config']['window']==10
    assert v1['config_sha256']!=v2['config_sha256'] and v2['parent_id']==v1['id']
    assert (v1['version'],v2['version'])==(1,2)
    with pytest.raises(ValueError):registry.create_factor(v1['config'])


def test_real_experiment_has_only_proxy_labels_and_purged_diagnostics(project,real_runs):
    _,_,_,ids=real_runs
    data=result(project,ids[0]);manifest=data['result'];folder=project/'outputs/factor_lab'/ids[0]
    features=pd.read_parquet(folder/'features.parquet');labels=pd.read_parquet(folder/'labels.parquet')
    assert manifest['input_rows']==40240 and manifest['source']=='YAHOO'
    assert manifest['source_provenance']['verified_rows']==40240
    assert not features.decision_eligible.any() and labels.forward_return.isna().all() and labels.net_return.isna().all()
    assert labels.proxy_forward_return.notna().any() and not manifest['research_grade'] and not manifest['execution_ready']
    assert features.date.max()<=pd.Timestamp('2024-12-31') and set(labels.horizon)=={1,3,5}
    summary=pd.DataFrame(manifest['summary'])
    assert len(summary)==6 and set(summary.partition)=={'train','validation'}
    assert summary.rank_ic_mean.between(-1,1).all() and summary.daily_ic_count.gt(0).all()
    from quant_research.clock import TradingClock
    clock=TradingClock();days=clock.calendar.sessions_in_range('2017-01-01','2022-12-31')
    daily=pd.read_parquet(folder/'daily_ic.parquet')
    assert not daily.loc[daily.partition.eq('train'),'date'].isin(days[-5:]).any()
    expected=daily.loc[daily.partition.eq('validation') & daily.horizon.eq(3)].sort_values('date').reset_index(drop=True)
    actual=pd.DataFrame(data['rolling_ic_h3'])
    assert len(actual)==len(expected)
    expected_rolling=expected['rank_ic'].rolling(20,min_periods=20).mean().dropna()
    assert not expected_rolling.empty
    assert actual['rolling_ic_20'].iloc[expected_rolling.index[0]] == pytest.approx(expected_rolling.iloc[0])


def test_completed_experiment_is_idempotent_and_comparison_is_same_snapshot(project,real_runs):
    _,_,_,ids=real_runs
    record=run(project,ids[0],data_root=Path.cwd());assert record['status']=='COMPLETED'
    comparison=compare(project,*ids)
    assert comparison['status']=='DESCRIPTIVE_COMPARISON_ONLY' and len(comparison['rows'])==6
    assert not comparison['execution_ready'] and not comparison['multiple_testing_adjusted']


def test_preview_is_real_and_source_selection_never_falls_back(project,real_runs):
    registry,v1,_,_=real_runs
    data=preview(project,v1['id'],'yahoo',data_root=Path.cwd())
    assert len(data['rows'])==10 and data['source']=='YAHOO' and all(not r['decision_eligible'] for r in data['rows'])
    if not Path('data/real_v21.duckdb').is_file():pytest.skip('BLOCKED_REAL_SIP_STORE_MISSING')
    exp=registry.create_experiment({'factor_version_id':v1['id'],'source':'alpaca'})
    blocked=run(project,exp['id'],data_root=Path.cwd())
    assert blocked['status']=='BLOCKED' and blocked['error']['code']=='CAPABILITY_BLOCKED'
    assert result(project,exp['id'])['status']=='BLOCKED'
    assert not list((project/'outputs/factor_lab'/exp['id']).glob('labels.parquet'))


def test_tampered_artifact_is_not_served_as_a_valid_result(project,real_runs):
    _,_,_,ids=real_runs
    path=project/'outputs/factor_lab'/ids[0]/'summary.csv';original=path.read_bytes()
    try:
        path.write_bytes(original+b'corrupted')
        with pytest.raises(PolicyError,match='SHA256'):result(project,ids[0])
    finally:path.write_bytes(original)


def test_custom_security_universe_is_not_mislabeled_as_etf_proxy(tmp_path):
    config=tmp_path/'configs/experiments'
    config.mkdir(parents=True)
    shutil.copyfile('configs/experiments/p2_factors.yaml',config/'p2_factors.yaml')
    registry=Registry(tmp_path)
    version=registry.create_factor(
        {'name':'equity-reversal','template':'reversal','window':5,'direction':1})
    symbols=['SPY','AAPL','MSFT','NVDA','AMZN','META','GOOGL','AVGO','AMD','TSLA','JPM','XOM']
    experiment=registry.create_experiment(
        {'factor_version_id':version['id'],'source':'yahoo','symbols':symbols})
    assert experiment['config']['symbols']==symbols
    assert experiment['config']['universe_version']=='EXPLICIT_CUSTOM_SECURITY_LIST_NOT_HISTORICAL_PIT'


def test_snapshot_and_protocol_are_frozen_at_creation(project,real_runs):
    registry,v1,_,_=real_runs
    exp=registry.create_experiment({'factor_version_id':v1['id'],'source':'yahoo'})
    assert exp['config']['research_protocol']['bootstrap_replicates']==500
    assert exp['config']['knowledge_cutoff_utc']==exp['created_at_utc']
    assert exp['config']['validation_end']=='2024-12-31'
    assert len(exp['config']['symbols'])==20 and exp['config']['universe_version']=='EXPLICIT_CURRENT_ETF_LIST_NOT_PIT'
    with pytest.raises(ValueError):registry.create_experiment({'factor_version_id':v1['id'],'source':'yahoo','validation_end':'2026-11-06'})


def test_lab_metadata_is_categorized_without_promoting_models(project,real_runs):
    from quant_research.data.catalog import build_catalog
    data=build_catalog(project);entry=next(row for row in data['datasets'] if row['dataset_id']=='factor_lab')
    assert entry['factor_versions']>=2 and entry['experiment_status_counts']['COMPLETED']>=2
    assert entry['use_policy']=='RETROSPECTIVE_EXPLORATORY_ONLY' and not data['execution_ready']


def test_http_registry_requires_csrf_and_rejects_extra_execution_parameters(project):
    import threading
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    from quant_research.web import Console,ThreadingHTTPServer,handler
    console=Console(project);server=ThreadingHTTPServer(('127.0.0.1',0),handler(console))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    body={'name':'http-factor','template':'momentum','window':20}
    def post(path,value,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Console-Token']=console.token
        return urlopen(Request(base+path,data=json.dumps(value).encode(),headers=headers,method='POST'),timeout=30)
    try:
        with pytest.raises(HTTPError) as rejected:post('/api/v1/factor-lab/factors',body,False)
        assert rejected.value.code==403
        with post('/api/v1/factor-lab/factors',body) as response:version=json.load(response);assert response.status==201
        with post('/api/v1/factor-lab/experiments',{'factor_version_id':version['id'],'source':'yahoo'}) as response:
            experiment=json.load(response)
        assert experiment['status']=='CREATED' and experiment['config']['horizons']==[1,3,5]
        with pytest.raises(HTTPError) as rejected:
            post('/api/v1/factor-lab/experiments',{'factor_version_id':version['id'],'source':'fixture'})
        assert rejected.value.code==400
        with pytest.raises(HTTPError) as rejected:
            post('/api/v1/factor-lab/experiments',{'factor_version_id':version['id'],'source':'yahoo','command':'paper-step'})
        assert rejected.value.code==400
        with urlopen(base+'/api/v1/factor-lab/library') as response:library=json.load(response)
        assert version['id'] in {row['id'] for row in library['factor_versions']}
    finally:server.shutdown();server.server_close();thread.join()
