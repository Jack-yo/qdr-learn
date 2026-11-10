"""Cross-source case checks, not a blanket corporate-action approval."""
from collections import defaultdict
import hashlib
import html
import re


def review(events,external,raw_root):
    texts,hashes={},{}
    for item in external:
        digest=item.get('raw_sha256')
        if not digest:continue
        body=(raw_root/'objects'/digest).read_bytes()
        if hashlib.sha256(body).hexdigest()!=digest:raise ValueError('Independent source hash mismatch')
        plain=html.unescape(re.sub('<[^>]*>',' ',body.decode('utf-8',errors='replace')))
        texts[item['name']]=re.sub(r'\s+',' ',plain)
        hashes[item['name']]=digest
    checks=[]
    for event in events:
        p=event['payload'];kind=event['event_type'];symbol=event['symbol']
        ok=False;source=None
        if symbol=='AAPL' and kind=='forward_splits':
            source='APPLE';t=texts.get(source,'')
            ok='four-for-one' in t and 'August 31, 2020' in t and p['new_rate']/p['old_rate']==4 and p['ex_date']=='2020-08-31'
        elif symbol=='AAPL' and kind=='cash_dividends':
            source='APPLE';t=texts.get(source,'')
            ok='$0.82' in t and 'August 13, 2020' in t and p['rate']==.82 and p['payable_date']=='2020-08-13'
        elif symbol=='GE' and kind=='reverse_splits':
            source='GE';t=texts.get(source,'')
            ok='1-for-8' in t and 'August 2, 2021' in t and p['new_rate']/p['old_rate']==.125 and p['ex_date']=='2021-08-02'
        elif kind=='name_changes' and p.get('old_symbol')=='FB' and p.get('new_symbol')=='META':
            source='NASDAQ_META';t=texts.get(source,'')
            ok=all(x in t for x in ('30303M102','June 9, 2022','FB','META')) and p.get('old_cusip')==p.get('new_cusip')=='30303M102' and p['process_date']=='2022-06-09'
        checks.append({'event_id':event['provider_event_id'],'event_type':kind,'status':'CASE_FIELDS_MATCH' if ok else 'BLOCKED_NOT_RECONCILED',
                       'provider_sha256':event['raw_sha256'],'independent_source':source,'independent_sha256':hashes.get(source),
                       'historical_publication_time_verified':False,'execution_accepted':False})
    groups=defaultdict(list)
    for e in events:
        if e['event_type']=='cash_dividends':
            p=e['payload'];groups[(p.get('symbol'),p.get('ex_date'),p.get('payable_date'),str(p.get('rate')))].append(e)
    collisions=[{'symbol':key[0],'ex_date':key[1],'payable_date':key[2],
                 'event_ids':[e['provider_event_id'] for e in values],'cusips':[e['payload'].get('cusip') for e in values],
                 'status':'BLOCKED_POSSIBLE_DUPLICATE_ENTITLEMENT'} for key,values in groups.items() if len(values)>1]
    return {'case_checks':checks,'identity_collisions':collisions,
            'scope':'Fixed historical cases only; not complete master/universe/settlement coverage'}
