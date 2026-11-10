"""Capability tests use traceable local real snapshots, not generated prices."""
from datetime import datetime,timezone
from pathlib import Path
import shutil

import pytest

from quant_research.data.bundle import load_real_bundle,verify_lineage
from quant_research.policy import PolicyError


def real_bundle(**kw):
    if not Path('data/real_v21.duckdb').exists():pytest.skip('BLOCKED_REAL_SIP_DATABASE_UNAVAILABLE')
    return load_real_bundle(Path('data/real_v21.duckdb'),start='2026-11-02',symbols=['SPY'],**kw)


def test_real_raw_does_not_unlock_historical_or_forward_execution():
    bundle=real_bundle()
    bundle.require('observation');bundle.require('raw_prices')
    assert bundle.metadata['source_provenance']['verified_rows']==5
    assert bundle.metadata['feed']=='sip' and bundle.metadata['rows']==5
    for cap in ('historical_backtest','forward_shadow','historical_model','exploratory_price_factors','pit_fundamentals'):
        with pytest.raises(PolicyError,match='lacks'):bundle.require(cap)
    assert bundle.capabilities['historical_backtest']['missing_evidence']


def test_no_manual_capability_or_dataframe_override():
    bundle=real_bundle()
    caps=bundle.capabilities;caps['forward_shadow']['status']='PASS'
    with pytest.raises(PolicyError):bundle.require('forward_shadow')
    frame=bundle.prices;frame.loc[frame.index[0],'close']+=1
    assert frame.close.iloc[0]!=bundle.prices.close.iloc[0]
    with pytest.raises(PolicyError,match='differs'):verify_lineage(frame,Path('data/raw'))


def test_knowledge_cutoff_filters_before_vintage_selection():
    with pytest.raises(PolicyError,match='No real'):
        real_bundle(cutoff=datetime(2026,11,6,22,tzinfo=timezone.utc))


def test_missing_warehouse_cannot_fallback_to_other_provider(tmp_path):
    with pytest.raises(PolicyError,match='unavailable'):
        load_real_bundle(tmp_path/'absent.duckdb')


def test_receipt_and_response_both_required(tmp_path):
    bundle=real_bundle()
    frame=bundle.prices
    digest=frame.raw_sha256.iloc[0]
    root=tmp_path/'raw';(root/'objects').mkdir(parents=True)
    shutil.copyfile(Path('data/raw/objects')/digest,root/'objects'/digest)
    with pytest.raises(PolicyError,match='receipt'):verify_lineage(frame,root)
    (root/'objects'/digest).write_bytes(b'corrupted response')
    with pytest.raises(PolicyError,match='SHA256'):verify_lineage(frame,root)


def test_raw_model_loader_reports_missing_action_consistent_features():
    from quant_research.models.dataset import load_panel
    from quant_research.models.settings import load_settings
    settings=load_settings(Path('configs/experiments/baseline.yaml'))
    with pytest.raises(PolicyError) as error:load_panel('alpaca',Path('data/real_v21.duckdb'),settings)
    assert 'corporate-action-consistent feature price series' in error.value.missing


def test_ui_raw_observation_and_model_blockers_are_real():
    from quant_research.web import snapshot,Console,action_commands
    state=snapshot(Path.cwd())
    assert state['source']=='ALPACA' and len(state['prices'])==20
    assert all(p['return20'] is None and p['basis']=='raw' for p in state['prices'])
    assert state['capabilities']['observation']['status']=='PASS'
    with pytest.raises(PolicyError):Console(Path.cwd()).start('alpha-model')
    command=action_commands('refresh','alpaca')[0]
    assert command[command.index('--source')+1]=='alpaca' and command[command.index('--feed')+1]=='sip'


def test_factor_cli_does_not_silently_read_yahoo_for_alpaca(capsys,tmp_path):
    from quant_research.cli import main
    code=main(['factor-report','--source','alpaca','--db','data/real_v21.duckdb','--output',str(tmp_path)])
    assert code==4
    assert 'corporate-action-consistent feature price series' in capsys.readouterr().out
    assert not list(tmp_path.glob('*/report.html'))


@pytest.mark.parametrize("directory", ["pytest-tmp", "ops_backups", "ops_restore"])
def test_private_reports_never_appear_as_product_results(tmp_path, directory):
    import json
    from quant_research.web import allowed_artifact
    runs=list(Path('outputs/g4').glob('*/manifest.json'))
    if not runs:pytest.skip('BLOCKED_REAL_REPORT_UNAVAILABLE')
    run=runs[0].parent
    target=tmp_path/'outputs'/directory/'run'
    target.mkdir(parents=True)
    for name in ('manifest.json','report.html'):
        shutil.copyfile(run/name,target/name)
    assert not allowed_artifact(tmp_path,target/'report.html')


def test_strict_model_entry_requires_historical_evidence(capsys):
    from quant_research.cli import main
    code=main(['train','--source','alpaca','--mode','strict','--db','data/real_v21.duckdb'])
    output=capsys.readouterr().out
    assert code==4 and 'historical_model lacks accepted evidence' in output
    assert 'historical publication-time evidence' in output
