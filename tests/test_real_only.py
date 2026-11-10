"""Policy tests use literal metadata; market integration uses real local cache only."""
from pathlib import Path
import subprocess
import sys

import pytest

from quant_research.policy import PolicyError,require_real_source,execution_blocked
from quant_research.web import snapshot,allowed_artifact


@pytest.mark.parametrize('source',['fixture','mock','SYNTHETIC_FIXTURE','demo','',None])
def test_non_real_metadata_rejected(source):
    with pytest.raises(PolicyError) as exc: require_real_source(source)
    assert exc.value.payload()['code']=='NON_REAL_SOURCE_REJECTED'


def test_execution_not_unlocked_by_provider_name():
    with pytest.raises(PolicyError) as exc: execution_blocked()
    assert 'verified_raw_prices' in exc.value.payload()['missing_evidence']


def test_product_cli_has_no_legacy_market_generator():
    for args in [['demo','--fixture'],['train','--source','fixture']]:
        process=subprocess.run([sys.executable,'-m','quant_research.cli',*args],capture_output=True,text=True)
        assert process.returncode != 0


def test_empty_database_and_unmanifested_artifact(tmp_path):
    state=snapshot(tmp_path)
    assert state['status']=='NOT_READY' and state['prices']==[]
    folder=tmp_path/'outputs';folder.mkdir()
    page=folder/'report.html';page.write_text('legacy artifact')
    assert not allowed_artifact(tmp_path,page)


def test_real_yahoo_offline_cache_and_warehouse_agree():
    from quant_research.clock import TradingClock
    from quant_research.data.providers.yahoo import YahooProvider
    from quant_research.data.store import Warehouse
    root=Path.cwd()
    if not (root/'data/research.duckdb').exists():
        pytest.skip('BLOCKED_REAL_SNAPSHOT_UNAVAILABLE: ingest licensed real history first')
    provider=YahooProvider(TradingClock(),root/'data/raw',offline=True)
    from quant_research.data.http import DataUnavailable
    try:
        records=provider.bars(['SPY'],'2017-01-03','2026-11-06')
    except DataUnavailable as exc:
        pytest.skip('BLOCKED_REAL_CACHE: '+str(exc))
    assert records and all(r.source=='YAHOO' for r in records)
    with Warehouse(root/'data/research.duckdb') as db:
        actual=db.prices('YAHOO','yahoo',start='2017-01-03',end='2026-11-06').to_pandas()
    actual=actual.loc[actual.symbol.eq('SPY')].set_index('date')
    assert len(actual)==len(records)
    for row in records:
        value=actual.loc[__import__('pandas').Timestamp(row.date)]
        assert value.close==row.close and value.raw_sha256==row.raw_sha256


def test_no_generator_imports_in_shipped_package():
    root=Path('src/quant_research')
    for path in root.rglob('*.py'):
        text=path.read_text(encoding='utf-8')
        assert 'providers.fixture import' not in text,path
        assert 'from random import Random' not in text,path


def test_missing_credentials_probe_is_explicit(tmp_path,monkeypatch):
    from argparse import Namespace
    import json
    from quant_research.data.probe import execute
    monkeypatch.delenv('ALPACA_API_KEY',raising=False)
    monkeypatch.delenv('ALPACA_SECRET_KEY',raising=False)
    assert execute(Namespace(provider='alpaca',output=tmp_path/'proof',data_dir=tmp_path/'data',offline=False))==4
    proof=json.loads((tmp_path/'proof/alpaca_provider_proof.json').read_text(encoding='utf-8'))
    assert proof['error_code']=='MISSING_CREDENTIALS'
    assert not proof['plan_verified'] and proof['real_records_processed']==0


def test_real_cached_history_before_incomplete_latest_bar():
    from datetime import date
    from quant_research.clock import TradingClock
    from quant_research.data.providers.yahoo import YahooProvider,parse_chart
    root=Path.cwd()
    if not (root/'data/raw/yahoo').exists(): pytest.skip('BLOCKED_REAL_CACHE_UNAVAILABLE')
    clock=TradingClock()
    provider=YahooProvider(clock,root/'data/raw',offline=True)
    raw=provider._raw('SPY','2017-01-03','2026-11-06')
    records,_=parse_chart(raw,'SPY',date(2017,1,3),date(2026,11,5),clock)
    assert len(records)==2475
    assert all(r.raw_sha256==raw.sha256 and r.source=='YAHOO' for r in records)


def test_real_alpaca_month_cache():
    from quant_research.clock import TradingClock
    from quant_research.data.http import HttpCache,DataUnavailable
    from quant_research.data.providers.alpaca import AlpacaProvider
    from quant_research.policy import SYMBOLS
    clock=TradingClock()
    try:
        records=AlpacaProvider(clock,HttpCache(Path('data/raw'),offline=True),feed='sip').bars(SYMBOLS,'2017-01-03','2017-01-31')
    except (DataUnavailable,FileNotFoundError) as exc:
        pytest.skip('BLOCKED_ALPACA_REAL_CACHE_UNAVAILABLE: '+str(exc))
    assert len(records)==len(clock.calendar.sessions_in_range('2017-01-03','2017-01-31'))*len(SYMBOLS)
    assert all(r.source=='ALPACA' and r.feed=='sip' and r.adjustment_basis=='raw' for r in records)
    assert len({(r.security_id,r.date) for r in records})==len(records)


def test_real_corporate_action_response_hash():
    import json,hashlib
    digest='be59eda8ada62dca566596209a506dc1192ad46727c32b1327cc9f8d6396e3c1'
    path=Path('data/raw/objects')/digest
    if not path.exists(): pytest.skip('BLOCKED_REAL_ACTION_CACHE_UNAVAILABLE')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    payload=json.loads(path.read_text(encoding='utf-8'))['corporate_actions']
    split=payload['forward_splits'][0]
    assert split['symbol']=='AAPL' and split['ex_date']=='2020-08-31'
    assert split['new_rate']/split['old_rate']==4
    assert payload['cash_dividends'][0]['payable_date']=='2020-08-13'
