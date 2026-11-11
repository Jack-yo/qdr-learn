"""Read-only data diagnostics tests use sqlite structure fixtures, not market."""
import sqlite3
import pytest
from quant_research.workflow.v4_data_diagnostics import inspect_v4_warehouse


def test_missing_source_tables_are_specific_blockers():
    db=sqlite3.connect(':memory:')
    out=inspect_v4_warehouse(db,asof='2026-11-10',symbols=['AAA','SPY'])
    assert out['status']=='DATA_CONTRACT_INVENTORY_ONLY'
    assert out['blocked_checks']==8
    assert out['source_independently_attested'] is False
    assert out['real_orders_enabled'] is False
    assert all(x['status']=='BLOCKED' for x in out['checks'])


def test_dated_raw_prices_are_observation_not_future_model_approval():
    db=sqlite3.connect(':memory:')
    db.execute('''CREATE TABLE prices_daily(
         security_id TEXT,symbol TEXT,date TEXT,open REAL,high REAL,low REAL,
         close REAL,volume INTEGER,available_at TEXT,raw_sha256 TEXT,
         adjustment_basis TEXT,source TEXT,feed TEXT)''')
    db.executemany('INSERT INTO prices_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',[
        ('1','AAA','2026-11-10',10,11,9,10,5000,'2026-11-10T21:10Z',
         'a'*64,'raw','ALPACA','sip'),
        ('2','SPY','2026-11-10',500,501,499,500,5000,
         '2026-11-10T21:10Z','a'*64,'raw','ALPACA','sip')])
    out=inspect_v4_warehouse(db,asof='2026-11-10',symbols=['AAA','SPY'])
    assert out['blocked_checks']==7
    assert out['checks'][0]['status']=='OBSERVED_FOR_REVIEW'
    assert out['checks'][0]['rows']==2
    assert out['tables']['sector_classification_pit']['status']=='MISSING_TABLE'
    assert out['historical_pit_attested'] is False


def test_invalid_session_and_symbols_are_rejected():
    db=sqlite3.connect(':memory:')
    with pytest.raises(ValueError,match='uppercase'):
        inspect_v4_warehouse(db,asof='2026-11-10',symbols=['spy'])
    with pytest.raises(ValueError,match='as-of'):
        inspect_v4_warehouse(db,asof='2026-11-31',symbols=['SPY'])
