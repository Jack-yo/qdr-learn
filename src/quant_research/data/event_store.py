"""Append-only event vintages. Provider event ID never masquerades as security ID."""
import json
import hashlib
from pathlib import Path
from .store import duckdb


DDL='''CREATE TABLE IF NOT EXISTS corporate_event_versions(
 provider VARCHAR NOT NULL,event_id VARCHAR NOT NULL,raw_sha256 VARCHAR NOT NULL,
 event_type VARCHAR NOT NULL,symbol VARCHAR,observed_at TIMESTAMPTZ NOT NULL,
 published_at TIMESTAMPTZ,record_json VARCHAR NOT NULL,
 PRIMARY KEY(provider,event_id,raw_sha256));'''


def verify_event(event,raw_root):
    if event['source_endpoint']!='https://data.alpaca.markets/v1/corporate-actions':
        raise ValueError('Unverified corporate-event endpoint')
    digest=event['raw_sha256']
    import re
    if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('Invalid event source hash')
    body=(raw_root/'objects'/digest).read_bytes()
    if hashlib.sha256(body).hexdigest()!=digest: raise ValueError('Event source hash mismatch')
    source=json.loads(body).get('corporate_actions',{}).get(event['event_type'],[])
    matches=[x for x in source if x.get('id')==event['provider_event_id']]
    if len(matches)!=1 or matches[0]!=event['payload']:raise ValueError('Event payload does not match source response')
    if event['available_at_utc']!=event['retrieved_at_utc'] or event['published_at_utc'] is not None:
        raise ValueError('Current source snapshot cannot claim historical publication')


def put_events(path,events,raw_root=Path('data/raw')):
    from quant_research.policy import require_real_source
    path.parent.mkdir(parents=True,exist_ok=True)
    with duckdb.connect(str(path)) as db:
        db.execute(DDL)
        before=db.execute('SELECT count(*) FROM corporate_event_versions').fetchone()[0]
        db.execute('BEGIN')
        try:
            for item in events:
                require_real_source(item['provider'])
                verify_event(item,raw_root)
                db.execute('INSERT INTO corporate_event_versions VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING',[
                    item['provider'],item['provider_event_id'],item['raw_sha256'],item['event_type'],item['symbol'],
                    item['retrieved_at_utc'],item['published_at_utc'],json.dumps(item,sort_keys=True)])
            db.execute('COMMIT')
        except Exception:
            db.execute('ROLLBACK');raise
        return db.execute('SELECT count(*) FROM corporate_event_versions').fetchone()[0]-before
