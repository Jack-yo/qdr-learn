"""Versioned corporate events: process dates are not publication timestamps."""
from datetime import date
import json
import os
import re

from quant_research.data.http import DataUnavailable


class ActionProvider:
    endpoint='https://data.alpaca.markets/v1/corporate-actions'

    def __init__(self,http,limit=1000):
        if not 1<=limit<=1000: raise ValueError('Invalid page size')
        self.http,self.limit,self.pages=http,limit,[]

    def events(self,symbols,start,end):
        if date.fromisoformat(start)>date.fromisoformat(end): raise ValueError('Invalid range')
        if not symbols or any(not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',s) for s in symbols): raise ValueError('Invalid symbols')
        headers={}
        if not self.http.offline:
            key,secret=os.environ.get('ALPACA_API_KEY'),os.environ.get('ALPACA_SECRET_KEY')
            if not key or not secret: raise DataUnavailable('Local Alpaca credentials required','MISSING_CREDENTIALS')
            headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
        params={'symbols':','.join(sorted(set(symbols))),'start':start,'end':end,'limit':self.limit,
                'sort':'asc','data_quality':'complete'}
        tokens,ids,result=set(),set(),[]
        self.pages=[]
        while True:
            raw=self.http.get(self.endpoint,params,headers)
            data=json.loads(raw.body)
            groups=data.get('corporate_actions')
            if not isinstance(groups,dict): raise DataUnavailable('Invalid corporate actions schema')
            self.pages.append({'raw_sha256':raw.sha256,'retrieved_at_utc':raw.fetched_at.isoformat(),'request_key':raw.request_key})
            for kind,events in groups.items():
                if not isinstance(events,list): raise DataUnavailable('Invalid event group')
                for event in events:
                    if not event.get('id') or event['id'] in ids: raise DataUnavailable('Missing or duplicate corporate event ID')
                    ids.add(event['id'])
                    for key,value in event.items():
                        if key.endswith('_date') and value: date.fromisoformat(value)
                    result.append({'provider':'ALPACA','provider_event_id':event['id'],'event_type':kind,
                        'symbol':event.get('symbol') or event.get('old_symbol') or event.get('acquiree_symbol'), 'source_endpoint':self.endpoint,
                        'raw_sha256':raw.sha256,'retrieved_at_utc':raw.fetched_at.isoformat(),
                        'published_at_utc':None,'available_at_utc':raw.fetched_at.isoformat(),
                        'source_version_kind':'current_revised_snapshot','identity_status':'UNVERIFIED',
                        'payload':event})
            token=data.get('next_page_token')
            if not token: break
            if token in tokens: raise DataUnavailable('Repeated corporate action page token')
            tokens.add(token);params={**params,'page_token':token}
        return result
