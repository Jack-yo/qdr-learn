"""Bounded on-demand public/reference and credentialed read-only market data.

Never persists a historical price warehouse or secrets. This is a research data
transport: receipt time does not establish point-in-time historical availability.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
import csv
import io
import json
import os
import re
import threading
from uuid import uuid4


class SourceUnavailable(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BoundedCache:
    """TTL, size & count capped cache; no credential URLs or secret headers stored."""
    def __init__(self, root, *, max_bytes=32_000_000, max_entries=32, entry_cap=5_000_000, now=None):
        self.root = Path(root) / 'data' / 'cache' / 'l1_on_demand'
        self.max_bytes, self.max_entries, self.entry_cap = max_bytes, max_entries, entry_cap
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()

    @staticmethod
    def identity(endpoint, params, *, feed=''):
        safe = {str(k): str(v) for k, v in params.items() if str(k).lower() not in {'api_key','secret','token','authorization'}}
        return sha256(json.dumps([endpoint, safe, feed], sort_keys=True).encode()).hexdigest()

    def get(self, key, ttl_seconds):
        if not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('Invalid cache identity')
        path = self.root / (key+'.json')
        with self._lock:
            if not path.is_file() or path.stat().st_size > self.entry_cap*2:
                return None
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                fetched = datetime.fromisoformat(item['fetched_at'])
                if fetched.tzinfo is None or not 0 <= (self._now()-fetched).total_seconds() < ttl_seconds:
                    return None
                body = bytes.fromhex(item['body_hex'])
                if len(body)>self.entry_cap or sha256(body).hexdigest()!=item['sha256']:
                    return None
                return body, item['fetched_at'], item['sha256']
            except (ValueError, OSError, KeyError, TypeError):
                return None

    def put(self, key, body):
        if len(body)>self.entry_cap:
            raise SourceUnavailable('RESPONSE_TOO_LARGE')
        if not re.fullmatch('[a-f0-9]{64}', key):
            raise ValueError('Invalid cache identity')
        stamp=self._now().isoformat()
        content=json.dumps({'fetched_at':stamp,'sha256':sha256(body).hexdigest(),
                            'body_hex':body.hex()},separators=(',',':'))
        with self._lock:
            self.root.mkdir(parents=True,exist_ok=True)
            tmp=self.root/(key+'.'+uuid4().hex+'.tmp')
            try:
                tmp.write_text(content,encoding='utf-8')
                tmp.replace(self.root/(key+'.json'))
                files=sorted(self.root.glob('*.json'),key=lambda p:p.stat().st_mtime)
                size=sum(p.stat().st_size for p in files)
                while files and (len(files)>self.max_entries or size>self.max_bytes):
                    old=files.pop(0); size-=old.stat().st_size; old.unlink(missing_ok=True)
            finally:
                tmp.unlink(missing_ok=True)
        return body, stamp, sha256(body).hexdigest()


def _network(url, headers, *, max_bytes=5_000_000):
    if urlsplit(url).scheme!='https':
        raise SourceUnavailable('HTTPS_REQUIRED')
    try:
        with build_opener(_NoRedirect).open(Request(url,headers=headers),timeout=14) as response:
            body=response.read(max_bytes+1)
            if len(body)>max_bytes:
                raise SourceUnavailable('RESPONSE_TOO_LARGE')
            return body
    except HTTPError as exc:
        raise SourceUnavailable('HTTP_'+str(exc.code)) from exc
    except (URLError,TimeoutError,OSError) as exc:
        raise SourceUnavailable('PROVIDER_UNAVAILABLE') from exc


class LiveSources:
    ETF_SYMBOLS=('SPY','QQQ','IWM','RSP','HYG','LQD','TLT','SHY',
                 'XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY')
    CBOE_VIX='https://cdn-api.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv'
    def __init__(self, root, *, cache=None, fetch=None, env=None, now=None):
        self.cache=cache or BoundedCache(root, now=now)
        self.fetch=fetch or _network
        self.env=os.environ if env is None else env
        self._now=now or (lambda:datetime.now(timezone.utc))

    def request(self, endpoint, params=None, headers=None, *, ttl=1800, refresh=False, feed=''):
        params=params or {}
        host=urlsplit(endpoint).hostname
        allowed_static = {
            self.CBOE_VIX,
            'https://data.alpaca.markets/v2/stocks/bars',
            'https://data.alpaca.markets/v2/stocks/snapshots',
            'https://api.stlouisfed.org/fred/series/observations',
            'https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml',
            'https://markets.newyorkfed.org/api/rates/secured/sofr/last/10.json',
            'https://markets.newyorkfed.org/api/rates/unsecured/effr/last/10.json',
            'https://publicreporting.cftc.gov/resource/gpe5-46if.json',
            'https://publicreporting.cftc.gov/resource/72hh-3qpy.json',
            'https://www.financialresearch.gov/financial-stress-index/data/fsi.csv',
            'https://www.bls.gov/schedule/news_release/bls.ics',
            'https://www.ici.org/research/stats/etf_flows',
        }
        cboe_date = re.fullmatch(
            r'https://cdn[.]cboe[.]com/data/us/options/market_statistics/daily/[0-9]{4}-[0-9]{2}-[0-9]{2}_daily_options',
            endpoint,
        )
        cboe_volume = re.fullmatch(
            r'https://cdn[.]cboe[.]com/resources/us/equities/market-statistics/historical-market-volume/market_history_20[0-9]{2}[.]csv',
            endpoint,
        )
        finra_daily = re.fullmatch(
            r'https://cdn[.]finra[.]org/equity/regsho/daily/CNMSshvol20[0-9]{6}[.]txt',
            endpoint,
        )
        if endpoint not in allowed_static and not cboe_date and not cboe_volume and not finra_daily:
            raise SourceUnavailable('UNAPPROVED_SOURCE')
        key=self.cache.identity(endpoint,params,feed=feed)
        if not refresh:
            cached=self.cache.get(key,ttl)
            if cached:return cached
        url=endpoint+('?' + urlencode(params) if params else '')
        result=self.fetch(url,headers or {})
        return self.cache.put(key,result)

    def bars(self, *, days=530, refresh=False, symbols=None,
             start_date=None, end_date=None, adjustment='raw',
             history_feed=None):
        """Historical 1Day stock bars: SIP/IEX only; never delayed_sip.

        end_date is inclusive. Feed, adjustment, window, and page SHA are
        explicit source receipts, and all requests are size/row bounded.
        """
        key=self.env.get('ALPACA_API_KEY'); secret=self.env.get('ALPACA_SECRET_KEY')
        if not key or not secret:
            raise SourceUnavailable('MISSING_ALPACA_CREDENTIALS')
        feed=(history_feed or self.env.get('QDR_L1_HISTORY_FEED','sip')).lower()
        if feed not in {'sip','iex'}:
            raise SourceUnavailable('INVALID_HISTORICAL_FEED')
        if adjustment not in {'raw','split'}:
            raise SourceUnavailable('INVALID_HISTORICAL_ADJUSTMENT')
        if type(days) is not int or not 10<=days<=5000:
            raise SourceUnavailable('INVALID_HISTORY_WINDOW')
        query_end=None
        try:
            if end_date:
                end=datetime.fromisoformat(str(end_date)).date()
            else:
                from quant_research.clock import TradingClock
                clock=TradingClock()
                now=self._now()
                if now.tzinfo is None:raise SourceUnavailable('NAIVE_CLOCK')
                session=clock.calendar.date_to_session(now.date(),direction='previous')
                while clock.close(session)+timedelta(minutes=20)>now:
                    session=clock.calendar.previous_session(session)
                end=session.date()
                query_end=(clock.close(session)+timedelta(minutes=1)).isoformat()
            start=(datetime.fromisoformat(str(start_date)).date() if start_date
                   else end-timedelta(days=days-1))
            if start>end or (end-start).days>5000:
                raise ValueError('Bad history date window')
        except (TypeError,ValueError,OverflowError):
            raise SourceUnavailable('INVALID_HISTORY_DATES')
        symbols=tuple(symbols or self.ETF_SYMBOLS)
        if (not symbols or len(symbols)>50 or
                any(not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,13}',x) for x in symbols)):
            raise SourceUnavailable('INVALID_SYMBOLS')
        headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret}
        query={'symbols':','.join(sorted(set(symbols))),
               'start':start.isoformat(),
               'end':query_end or (end+timedelta(days=1)).isoformat(),
               'timeframe':'1Day','adjustment':adjustment,
               'feed':feed,'sort':'asc','limit':10000}
        merged={sym:[] for sym in symbols}
        receipts=[]; known_tokens=set(); count=0
        for page in range(15):
            body,stamp,digest=self.request('https://data.alpaca.markets/v2/stocks/bars',
                                          query,headers,ttl=900,
                                          refresh=refresh,feed=feed)
            try:
                doc=json.loads(body)
            except (ValueError,TypeError) as exc:
                raise SourceUnavailable('INVALID_ALPACA_JSON') from exc
            if not isinstance(doc,dict) or not isinstance(doc.get('bars'),dict):
                raise SourceUnavailable('INVALID_ALPACA_RESPONSE')
            for symbol,rows in doc['bars'].items():
                if symbol not in merged or not isinstance(rows,list):
                    raise SourceUnavailable('INVALID_ALPACA_SYMBOL')
                for record in rows:
                    if not isinstance(record,dict) or not isinstance(record.get('t'),str):
                        raise SourceUnavailable('INVALID_ALPACA_BAR')
                    day=record['t'][:10]
                    if len(day)!=10 or not start.isoformat()<=day<=end.isoformat():
                        raise SourceUnavailable('BAR_OUTSIDE_REQUEST_WINDOW')
                    merged[symbol].append(record)
                    count+=1
                    if count>150_000:
                        raise SourceUnavailable('HISTORY_ROW_CAP')
            receipts.append({'fetched_at':stamp,'sha256':digest,'feed':feed,
                             'adjustment':adjustment,'start':start.isoformat(),
                             'end':end.isoformat(),'page':page+1})
            token=doc.get('next_page_token')
            if not token:
                break
            if not isinstance(token,str) or len(token)>1024 or token in known_tokens:
                raise SourceUnavailable('ALPACA_PAGINATION_INVALID')
            known_tokens.add(token)
            query['page_token']=token
        else:
            raise SourceUnavailable('ALPACA_PAGINATION_LIMIT')
        if not count:
            raise SourceUnavailable('HISTORICAL_BARS_EMPTY')
        for symbol,rows in merged.items():
            markers=[r['t'] for r in rows]
            if len(markers)!=len(set(markers)):
                raise SourceUnavailable('DUPLICATE_ALPACA_BARS')
            if markers!=sorted(markers):
                raise SourceUnavailable('UNSORTED_ALPACA_BARS')
        return merged,receipts

    def snapshots(self, *, refresh=False, symbols=('SPY','QQQ','IWM','RSP','HYG','LQD')):
        key=self.env.get('ALPACA_API_KEY');secret=self.env.get('ALPACA_SECRET_KEY')
        if not key or not secret:raise SourceUnavailable('MISSING_ALPACA_CREDENTIALS')
        feed=self.env.get('QDR_L1_FEED','delayed_sip').lower()
        if feed not in {'delayed_sip','sip','iex'}:raise SourceUnavailable('INVALID_FEED')
        params={'symbols':','.join(sorted(set(symbols))),'feed':feed}
        body,stamp,digest=self.request('https://data.alpaca.markets/v2/stocks/snapshots',params,
            {'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret},ttl=60,refresh=refresh,feed=feed)
        try:
            doc=json.loads(body)
            if not isinstance(doc,dict):raise ValueError('Invalid snapshots')
            snapshots=doc.get('snapshots',doc)
            if (not isinstance(snapshots,dict) or not set(snapshots)<=set(symbols)
                    or any(not isinstance(value,dict) for value in snapshots.values())):
                raise ValueError('Invalid snapshots')
        except (ValueError,TypeError) as exc:raise SourceUnavailable('INVALID_ALPACA_SNAPSHOTS') from exc
        return snapshots,{'fetched_at':stamp,'sha256':digest,'source':'ALPACA_'+feed,
                                 'scope':'LAST_TRADE_LEVEL1_QUOTE_NOT_FULL_DEPTH'}

    def cboe_vix(self, *, refresh=False):
        body, stamp,digest=self.request(self.CBOE_VIX,ttl=7200,refresh=refresh)
        try:
            rows=list(csv.DictReader(io.StringIO(body.decode('utf-8-sig'))))
            out={}
            for row in rows:
                datekey=next((v for k,v in row.items() if k and k.strip().upper()=='DATE'),None)
                close=next((v for k,v in row.items() if k and k.strip().upper()=='CLOSE'),None)
                if datekey and close:
                    from datetime import date
                    for fmt in ('%m/%d/%Y','%Y-%m-%d'):
                        try: d=datetime.strptime(datekey.strip(),fmt).date().isoformat();break
                        except ValueError:continue
                    else:continue
                    out[d]=float(close)
            if not out:raise ValueError('No Cboe dates')
            return out, {'fetched_at':stamp,'sha256':digest,'source':'CBOE_VIX','pit':'CURRENT_VINTAGE'}
        except (ValueError,TypeError,UnicodeError) as exc:raise SourceUnavailable('INVALID_CBOE_DATA') from exc

    def fred(self, series_id, *, refresh=False, days=530):
        if not re.fullmatch('[A-Z0-9_]{3,24}',series_id):raise SourceUnavailable('INVALID_FRED_SERIES')
        key=self.env.get('FRED_API_KEY')
        if not key:raise SourceUnavailable('MISSING_FRED_CREDENTIALS')
        today=self._now().date(); params={'series_id':series_id,'file_type':'json',
            'api_key':key,'observation_start':(today-timedelta(days=days)).isoformat(),
            'realtime_start':today.isoformat(),'realtime_end':today.isoformat()}
        body,stamp,digest=self.request('https://api.stlouisfed.org/fred/series/observations',params,
                                        ttl=7200,refresh=refresh,feed=series_id)
        try:
            observations=json.loads(body)['observations']
            values={r['date']:float(r['value']) for r in observations if r.get('value') not in (None,'.')}
        except (ValueError,TypeError,KeyError) as exc:raise SourceUnavailable('INVALID_FRED_RESPONSE') from exc
        return values, {'fetched_at':stamp,'sha256':digest,'source':'FRED_'+series_id,
                        'pit':'CURRENT_VINTAGE_NOT_HISTORICALLY_PIT'}
