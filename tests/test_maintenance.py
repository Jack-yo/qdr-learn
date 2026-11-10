"""Maintenance tests use real cached events/stores; failures are explicit fault injection."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import yaml

from quant_research.clock import TradingClock
from quant_research.data.catalog import build_catalog,write_catalog
from quant_research.data.bundle import load_real_bundle
from quant_research.data.http import DataUnavailable
from quant_research.policy import PolicyError
from quant_research.workflow.maintenance import price_start,execute


@pytest.fixture(scope='module')
def catalog():
    if not Path('data/managed/corporate_actions/events.duckdb').is_file():
        pytest.skip('BLOCKED_REAL_MANAGED_EVENT_STORE_MISSING')
    return build_catalog(Path.cwd())


def test_categories_preserve_versions_and_missing_evidence(catalog):
    datasets={d['dataset_id']:d for d in catalog['datasets']}
    assert datasets['market_prices']['latest_rows']==49520
    assert datasets['market_prices']['rows']>=49520  # Retained real source revisions, not extra sessions.
    assert datasets['corporate_actions']['latest_rows']==1042
    assert datasets['sec_candidates']['eligible_rows']==0
    assert datasets['yahoo_research_prices']['latest_rows']==40240
    assert datasets['yahoo_research_prices']['last_date']=='2024-12-31'
    assert datasets['yahoo_research_prices']['use_policy']=='EXPLORATORY_ONLY_NOT_RAW_NOT_PIT'
    assert datasets['historical_securities']['rows'] is None
    assert datasets['paper_ledger']['status']=='BLOCKED'
    assert not catalog['execution_ready'] and not catalog['historical_universe_available']
    assert any('fixture' in row['path'] for row in catalog['excluded_stores'])


def test_classic_french_name_is_accepted_only_as_attribution(catalog):
    factor=next(d for d in catalog['datasets'] if d['dataset_id']=='classic_factors')
    if factor['rows'] is None or factor['rows']==0:
        pytest.skip('BLOCKED_MANAGED_REAL_FRENCH_STORE_MISSING')
    assert factor['status']=='COLLECTED_RESTRICTED_USE' and factor['rows']>1000
    assert factor['use_policy']=='ATTRIBUTION_ONLY' and factor['source']=='KEN_FRENCH'


def test_cache_inventory_has_hashes_and_no_credential_headers(catalog):
    assert catalog['cache_hash_failures']==0 and catalog['cache_receipts']>100
    assert {'market_prices','corporate_actions','sec','classic_factors'}<=set(r['category'] for r in catalog['cache_index'])
    assert all('headers' not in r for r in catalog['cache_index'])


def test_incremental_market_update_uses_real_watermark_with_overlap():
    db=Path('data/real_v21.duckdb')
    if not db.is_file():pytest.skip('BLOCKED_REAL_SIP_STORE_MISSING')
    config=yaml.safe_load(Path('configs/data_maintenance.yaml').read_text())
    assert price_start(db,config['prices'],'2026-11-06',False,TradingClock())=='2026-11-02'
    assert price_start(db,config['prices'],'2026-11-06',True,TradingClock())=='2017-01-03'


def test_maintenance_lock_prevents_conflicting_reads_and_jobs(tmp_path):
    from quant_research.web import snapshot,Console
    folder=tmp_path/'data/catalog';folder.mkdir(parents=True)
    (folder/'.maintenance.lock').write_text('{"pid":1}')
    with pytest.raises(PolicyError,match='owns the warehouse'):
        load_real_bundle(tmp_path/'data/real_v21.duckdb')
    assert snapshot(tmp_path)['status']=='DATA_MAINTENANCE_RUNNING'
    with pytest.raises(PolicyError,match='maintenance is running'):
        Console(tmp_path).start('refresh')
    with pytest.raises(PolicyError,match='catalog writer'):
        write_catalog(tmp_path)


def test_catalog_exports_and_daily_command_have_fixed_scope(tmp_path):
    from quant_research.data.catalog import catalog_artifact
    from quant_research.web import action_commands
    output,_=write_catalog(tmp_path)
    assert catalog_artifact(tmp_path,'datasets.csv').startswith(b'\xef\xbb\xbf')
    assert action_commands('maintain-daily','alpaca')==[['maintain-data','--cadence','daily','--env-file','.env']]
    (output/'datasets.csv').write_text('tampered inventory')
    with pytest.raises(PolicyError,match='SHA256'):
        catalog_artifact(tmp_path)
    with pytest.raises(ValueError,match='Unknown catalog export'):
        catalog_artifact(tmp_path,'../../.env')


def test_one_source_failure_does_not_stop_real_action_maintenance_and_replay(tmp_path,monkeypatch):
    from quant_research.data.providers.alpaca import AlpacaProvider
    pages=Path('outputs/feature_prices/events_pages.json')
    if not pages.exists():pytest.skip('BLOCKED_REAL_EVENT_PAGE_RECEIPTS_MISSING')
    original=Path.cwd()
    config=original/'configs/data_maintenance.yaml'
    raw=tmp_path/'data/raw'
    for part in ('objects','requests','receipts'):(raw/part).mkdir(parents=True)
    wanted=json.loads(pages.read_text())
    for page in wanted:
        digest,key=page['raw_sha256'],page['request_key']
        shutil.copyfile(original/'data/raw/objects'/digest,raw/'objects'/digest)
        shutil.copyfile(original/'data/raw/requests'/(key+'.json'),raw/'requests'/(key+'.json'))
    for receipt in (original/'data/raw/receipts').glob('*.json'):
        if json.loads(receipt.read_text()).get('sha256') in {p['raw_sha256'] for p in wanted}:
            shutil.copyfile(receipt,raw/'receipts'/receipt.name)
    def unavailable(*args,**kw):raise DataUnavailable('Injected source outage','SOURCE_OUTAGE')
    monkeypatch.setattr(AlpacaProvider,'bars',unavailable);monkeypatch.chdir(tmp_path)
    args=SimpleNamespace(config=config,groups='prices,actions',cadence='daily',end='2026-11-06',full=True,offline=True)
    for expected in (1042,0):
        assert execute(args)==4
        latest=max((tmp_path/'outputs/maintenance').glob('*/manifest.json'),key=lambda p:p.stat().st_mtime)
        result=json.loads(latest.read_text())
        assert result['tasks'][0]['code']=='SOURCE_OUTAGE'
        assert result['tasks'][1]['status']=='UPDATED' and result['tasks'][1]['inserted_rows']==expected
        assert not (tmp_path/'data/catalog/.maintenance.lock').exists()
    pointer=json.loads((tmp_path/'data/catalog/latest.json').read_text())
    assert (tmp_path/pointer['snapshot_dir']/'datasets.csv').is_file()
