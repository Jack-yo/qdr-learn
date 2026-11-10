"""Candidate evidence storage is separate from decision-eligible PIT fundamentals."""
import json
import hashlib
import re
from pathlib import Path

from .store import duckdb

DDL='''
CREATE TABLE IF NOT EXISTS filing_index_versions(
 cik VARCHAR,accession VARCHAR,source_hash VARCHAR,record_json VARCHAR NOT NULL,
 PRIMARY KEY(cik,accession,source_hash));
CREATE TABLE IF NOT EXISTS financial_candidates(
 candidate_id VARCHAR PRIMARY KEY,cik VARCHAR,accession VARCHAR,filing_index_hash VARCHAR,
 decision_eligible BOOLEAN NOT NULL CHECK(decision_eligible=false),record_json VARCHAR NOT NULL,
 FOREIGN KEY(cik,accession,filing_index_hash) REFERENCES filing_index_versions(cik,accession,source_hash));
'''


def put_candidates(path,filings,facts,raw_root=Path('data/raw')):
    if any(f['decision_eligible'] or f['available_at_historical_utc'] is not None for f in facts):
        raise ValueError('Candidate store cannot promote historical eligibility')
    cache={}
    def source(digest):
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Invalid source hash')
        if digest not in cache:
            body=(raw_root/'objects'/digest).read_bytes()
            if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('SEC raw source hash mismatch')
            cache[digest]=json.loads(body)
        return cache[digest]
    for filing in filings:
        raw=source(filing['source_hash'])
        table=raw.get('filings',{}).get('recent',raw)
        matches=[i for i,a in enumerate(table['accessionNumber']) if a==filing['accession']]
        if len(matches)!=1:raise ValueError('Accession does not match raw source')
        i=matches[0]
        for field,original in [('filed_date','filingDate'),('form','form'),('accepted_time_source_text','acceptanceDateTime')]:
            if filing[field]!=table[original][i]:raise ValueError('Filing metadata does not match raw source')
    for fact in facts:
        raw=source(fact['facts_source_hash'])
        record=raw['facts']['us-gaap'][fact['concept']]['units'][fact['unit']][fact['source_record_index']]
        if (record['val'],record['accn'],record['end'])!=(fact['value'],fact['accession'],fact['period_end']):
            raise ValueError('Financial candidate does not match raw source')
        expected=hashlib.sha256(f"{fact['facts_source_hash']}:{fact['concept']}:{fact['unit']}:{fact['source_record_index']}".encode()).hexdigest()
        if fact['candidate_id']!=expected or int(fact['cik'])!=int(raw['cik']):raise ValueError('Candidate identity mismatch')
    path.parent.mkdir(parents=True,exist_ok=True)
    with duckdb.connect(str(path)) as db:
        db.execute(DDL)
        before=[db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('filing_index_versions','financial_candidates')]
        db.execute('BEGIN')
        try:
            for f in filings:
                db.execute('INSERT INTO filing_index_versions VALUES (?,?,?,?) ON CONFLICT DO NOTHING',
                    [f['cik'],f['accession'],f['source_hash'],json.dumps(f,sort_keys=True)])
            for f in facts:
                db.execute('INSERT INTO financial_candidates VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING',
                    [f['candidate_id'],str(f['cik']).zfill(10),f['accession'],f['filing_index_hash'],False,json.dumps(f,sort_keys=True)])
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
        after=[db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('filing_index_versions','financial_candidates')]
    return {'new_filing_versions':after[0]-before[0],'new_financial_candidates':after[1]-before[1]}
