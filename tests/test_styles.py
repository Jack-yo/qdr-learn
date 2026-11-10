"""Actual French snapshots, causal-prefix checks, and no synthetic factor records."""
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
import shutil
import json
import os

import numpy as np
import pandas as pd
import pytest

from quant_research.data.bundle import frame_hash
from quant_research.data.french_bundle import load_french_bundle,verify_french_rows,FrenchBundle
from quant_research.policy import PolicyError
from quant_research.research.style_monitor import monitor


DB=Path('data/managed/classic_factors/factors.duckdb')
RAW=Path('data/raw')


@pytest.fixture(scope='module')
def actual():
    if not DB.is_file():pytest.skip('BLOCKED_REAL_FRENCH_STORE_MISSING')
    bundle=load_french_bundle(DB,RAW)
    return bundle,monitor(bundle)


def test_all_source_values_are_reconciled_and_not_decision_eligible(actual):
    bundle,(history,latest,corr,metadata)=actual
    assert bundle.metadata['rows']==19592 and len(latest)==8
    assert sum(s['verified_rows'] for s in metadata['source_provenance'])==19592
    assert len(corr)==64 and metadata['missing_factor_sessions']==0
    assert not history.decision_eligible.any() and not metadata['execution_ready']
    assert metadata['asof_date_et']=='2026-09-30'
    assert set(latest.state)<= {'强势加速','强势减速','弱势改善','弱势恶化','REFERENCE_ONLY'}
    assert latest.loc[latest.factor_name.eq('RF'),'state'].iloc[0]=='REFERENCE_ONLY'


def test_real_rolling_formula_matches_source_window_and_preserves_availability(actual):
    bundle,(_,latest,_,_)=actual
    source=bundle.frame.loc[bundle.frame.factor_name.eq('Mom')].sort_values('date')
    row=latest.loc[latest.factor_name.eq('Mom')].iloc[0]
    for window in (5,20,60):
        assert row[f'sum_{window}d']==pytest.approx(source.value_decimal.tail(window).sum())
        assert row[f'sum_{window}d_available_at']>=source.available_at.tail(window).max()
    assert row.volatility_20d_annualized==pytest.approx(source.value_decimal.tail(20).std(ddof=1)*np.sqrt(252))


def test_prefix_does_not_change_when_future_observations_are_added(actual):
    bundle,(full,_,_,_)=actual
    data=bundle.frame
    prefix=data.loc[pd.to_datetime(data.date).le('2024-12-31')].copy()
    metadata=deepcopy(bundle.metadata);metadata.update(asof_date_et='2024-12-31',snapshot_sha256=frame_hash(prefix),rows=len(prefix))
    shorter=FrenchBundle(prefix,metadata)
    computed,_,_,_=monitor(shorter)
    columns=[c for c in computed if c not in ('available_at','state_available_at')]
    expected=full.loc[pd.to_datetime(full.date).le('2024-12-31')]
    pd.testing.assert_frame_equal(computed[columns].reset_index(drop=True),expected[columns].reset_index(drop=True))


def test_missing_actual_session_is_not_filled_or_bridged(actual):
    bundle,_=actual;data=bundle.frame
    # Remove one actual observation as fault injection; never generate market values.
    date=data.date.max();data=data.loc[~(data.factor_name.eq('SMB')&data.date.eq(date))].copy()
    metadata=deepcopy(bundle.metadata);metadata['snapshot_sha256']=frame_hash(data)
    _,latest,_,result=monitor(FrenchBundle(data,metadata))
    row=latest.loc[latest.factor_name.eq('SMB')].iloc[0]
    assert pd.isna(row.sum_5d) and pd.isna(row.sum_60d) and row.state=='UNKNOWN'
    assert result['status']=='PARTIAL_DATA_BLOCKED' and row.missing_reason=='SOURCE_ROW_MISSING_OR_NULL'


def test_mutated_source_value_and_missing_receipt_are_rejected(actual,tmp_path):
    frame=actual[0].frame
    frame.loc[frame.index[0],'value_decimal']+=0.01  # Fault injection only.
    with pytest.raises(PolicyError,match='differs'):verify_french_rows(frame,RAW)
    root=tmp_path/'raw';(root/'objects').mkdir(parents=True)
    for digest in frame.version.unique():shutil.copyfile(RAW/'objects'/digest,root/'objects'/digest)
    with pytest.raises(PolicyError,match='receipt'):verify_french_rows(actual[0].frame,root)


def test_past_cutoff_unavailable_date_and_sealed_research_are_blocked():
    if not DB.is_file():pytest.skip('BLOCKED_REAL_FRENCH_STORE_MISSING')
    with pytest.raises(PolicyError,match='cutoff'):
        load_french_bundle(DB,RAW,cutoff=datetime(2024,12,31,tzinfo=timezone.utc))
    with pytest.raises(PolicyError,match='not covered'):
        load_french_bundle(DB,RAW,asof='2026-11-06')
    with pytest.raises(PolicyError,match='sealed'):
        load_french_bundle(DB,RAW,asof='2025-01-02',mode='research')
    research=load_french_bundle(DB,RAW,mode='research')
    assert pd.to_datetime(research.frame.date).max()<=pd.Timestamp('2024-12-31')


def test_french_monitor_does_not_depend_on_alpaca_price_capabilities():
    from quant_research.web import action_commands
    assert action_commands('style-report','alpaca')==[['style-report']]
    assert action_commands('style-report','yahoo')==[['style-report']]
    with pytest.raises(PolicyError,match='unavailable'):
        load_french_bundle(Path('data/does-not-exist.duckdb'),RAW)


def test_foreign_maintenance_lock_blocks_factor_reads_but_owner_can_derive(actual,tmp_path):
    db=tmp_path/'data/managed/classic_factors/factors.duckdb';db.parent.mkdir(parents=True)
    shutil.copyfile(DB,db)
    folder=tmp_path/'data/catalog';folder.mkdir(parents=True)
    lock=folder/'.maintenance.lock';lock.write_text(json.dumps({'pid':os.getpid()+1000000}))
    with pytest.raises(PolicyError,match='maintenance'):
        load_french_bundle(db,RAW)
    lock.write_text(json.dumps({'pid':os.getpid()}))
    owner=load_french_bundle(db,RAW)
    assert owner.metadata['rows']==19592 and not owner.metadata['execution_ready']


def test_http_styles_research_export_and_missing_date_are_real(actual):
    import csv,io,threading
    from urllib.request import urlopen
    from urllib.error import HTTPError
    from quant_research.web import Console,ThreadingHTTPServer,handler
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(Console(Path.cwd())))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/api/v1/styles?mode=research&asof=2024-12-31',timeout=60) as response:
            data=json.load(response)
        assert data['rows']==16096 and len(data['latest'])==8 and not data['historical_decision_eligible']
        assert 'FACTOR_PUBLICATION_LAG_UNVERIFIED' in data['data_quality_flags']
        assert data['asof_date_et']=='2024-12-31' and data['source']=='FRENCH'
        with urlopen(base+'/api/v1/styles/export.csv?mode=research',timeout=60) as response:
            rows=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))
        assert len(rows)==8 and all(r['source']=='FRENCH' and r['asof_date_et']=='2024-12-31' for r in rows)
        for query,code in [('asof=2026-11-06',409),('mode=research&asof=2025-01-02',409),('window=123',400)]:
            with pytest.raises(HTTPError) as error:urlopen(base+'/api/v1/styles?'+query,timeout=60)
            assert error.value.code==code
    finally:
        server.shutdown();server.server_close();thread.join()
