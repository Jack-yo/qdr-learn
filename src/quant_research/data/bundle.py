"""Read-only real dataset snapshots and derived, non-user-editable capability decisions."""
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from copy import deepcopy

import pandas as pd

from quant_research.clock import TradingClock,utc
from quant_research.policy import PolicyError,require_real_source,require_real_frame,SYMBOLS
from .store import duckdb


def frame_hash(frame):
    return hashlib.sha256(frame.to_json(orient='records',date_format='iso').encode()).hexdigest()


def verify_lineage(prices,raw_root):
    """Check each selected numeric row against its content-addressed response."""
    receipts={}
    wanted=set(prices.raw_sha256)
    for folder in (raw_root/'receipts',raw_root/'yahoo'/'receipts'):
        for path in folder.glob('*.json'):
            try:data=json.loads(path.read_text(encoding='utf-8'))
            except (ValueError,OSError):continue
            if data.get('sha256') in wanted:receipts.setdefault(data['sha256'],[]).append(data)
    for digest,group in prices.groupby('raw_sha256'):
        path=raw_root/'objects'/digest
        if not path.is_file():raise PolicyError('RAW_RESPONSE_MISSING','Source response unavailable',[digest])
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=digest:raise PolicyError('RAW_RESPONSE_CORRUPT','Source response SHA256 mismatch',[digest])
        data=json.loads(body)
        accepted=[]
        for receipt in receipts.get(digest,[]):
            q=receipt.get('params',{})
            if set(group.source)=={'ALPACA'} and receipt.get('url')=='https://data.alpaca.markets/v2/stocks/bars' and q.get('adjustment')=='raw' and q.get('feed')=='sip' and q.get('timeframe')=='1Day' and q.get('asof')=='-':
                if set(group.symbol)<=set(q.get('symbols','').split(',')):accepted.append(receipt)
            request=receipt.get('request',{})
            if set(group.source)=={'YAHOO'} and request.get('provider')=='yfinance' and request.get('auto_adjust') is False and set(group.symbol)=={request.get('symbol')}:
                accepted.append(receipt)
        if not accepted:raise PolicyError('SOURCE_RECEIPT_MISSING','No matching source/feed/adjustment receipt',[digest])
        actual={}
        if 'bars' in data and set(group.source)=={'ALPACA'} and set(group.feed)=={'sip'} and set(group.adjustment_basis)=={'raw'}:
            for symbol,rows in data['bars'].items():
                for row in rows:
                    day=pd.Timestamp(row['t']).tz_convert('America/New_York').date()
                    actual[symbol,day]=tuple(row[k] for k in ('o','h','l','c','v'))
        elif 'chart' in data and set(group.source)=={'YAHOO'} and set(group.adjustment_basis)=={'yahoo_split_adjusted'}:
            chart=data['chart']['result'][0];symbol=chart['meta']['symbol']
            quotes=chart['indicators']['quote'][0]
            for i,t in enumerate(chart.get('timestamp',[])):
                day=datetime.fromtimestamp(t,timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
                actual[symbol,day]=tuple(quotes[k][i] for k in ('open','high','low','close','volume'))
        else:raise PolicyError('SOURCE_SCHEMA_UNVERIFIED','Unknown raw market response schema')
        receipt_times = {pd.Timestamp(receipt['fetched_at']) for receipt in accepted}
        required = {'available_at', 'ingested_at', 'event_time'}
        if not required.issubset(group.columns):
            raise PolicyError('AVAILABILITY_EVIDENCE_MISMATCH', 'Price observation timestamps are incomplete', [digest])
        observed = pd.to_datetime(group.available_at, utc=True)
        ingested = pd.to_datetime(group.ingested_at, utc=True)
        events = pd.to_datetime(group.event_time, utc=True)
        if not (observed.isin(receipt_times) & observed.ge(events) & ingested.ge(observed)).all():
            raise PolicyError('AVAILABILITY_EVIDENCE_MISMATCH',
                              'Price observation must match a source receipt timestamp and event ordering', [digest])
        for row in group.itertuples():
            if actual.get((row.symbol,pd.Timestamp(row.date).date()))!=(row.open,row.high,row.low,row.close,row.volume):
                raise PolicyError('PRICE_LINEAGE_MISMATCH','Stored OHLCV differs from raw source',[str(row.symbol),str(row.date)])
    return {'verified_rows':len(prices),'verified_response_objects':int(prices.raw_sha256.nunique())}


@dataclass(frozen=True)
class DatasetBundle:
    _prices:pd.DataFrame
    _metadata:dict
    _capabilities:dict

    @property
    def metadata(self):return deepcopy(self._metadata)

    @property
    def capabilities(self):return deepcopy(self._capabilities)

    @property
    def prices(self):return self._prices.copy(deep=True)

    def require(self,capability):
        if frame_hash(self._prices)!=self._metadata['snapshot_sha256']:
            raise PolicyError('SNAPSHOT_MUTATED','Frozen dataset changed after validation')
        decision=self._capabilities.get(capability)
        if not decision or decision['status']!='PASS':
            raise PolicyError('CAPABILITY_BLOCKED',f'{capability} lacks accepted evidence',decision['missing_evidence'] if decision else ['unknown capability'])


def load_real_bundle(database,source='alpaca',asof=None,cutoff=None,start='2017-01-03',symbols=None,raw_root=Path('data/raw')):
    require_real_source(source)
    source=source.upper()
    feed={'ALPACA':'sip','YAHOO':'yahoo'}.get(source)
    if not feed:raise PolicyError('PRICE_SOURCE_UNSUPPORTED','Selected source does not provide this price contract')
    cutoff=utc(cutoff or datetime.now(timezone.utc))
    if cutoff>datetime.now(timezone.utc):raise PolicyError('FUTURE_CUTOFF','Knowledge cutoff cannot be in the future')
    symbols=list(SYMBOLS if symbols is None else symbols)
    if not symbols or len(symbols)!=len(set(symbols)):raise ValueError('Unique nonempty symbols required')
    database=Path(database)
    if (database.parent/'catalog/.maintenance.lock').is_file():
        raise PolicyError('DATA_MAINTENANCE_RUNNING','Data maintenance owns the warehouse; retry after completion')
    if not database.is_file():raise PolicyError('NO_REAL_DATA','Real warehouse is unavailable',['prices_daily'])
    with duckdb.connect(str(database),read_only=True) as db:
        db.execute("SET TimeZone='UTC'")
        if asof is None:
            asof=db.execute('SELECT max(date) FROM prices_daily WHERE source=? AND feed=? AND event_time<=?', [source,feed,cutoff]).fetchone()[0]
        if asof is None:raise PolicyError('NO_REAL_DATA','No completed real session available')
        clock=TradingClock();clock.signal(str(asof))
        slots=','.join('?' for _ in symbols)
        prices=db.execute(f'''SELECT p.* REPLACE(obs.available_at AS available_at,obs.ingested_at AS ingested_at)
            FROM prices_daily p JOIN price_observations obs USING(security_id,date,source,feed,adjustment_basis,raw_sha256)
            WHERE p.source=? AND p.feed=? AND p.date>=? AND p.date<=? AND p.event_time<=? AND obs.available_at<=?
            AND obs.ingested_at<=? AND p.symbol IN ({slots})
            QUALIFY row_number() OVER(PARTITION BY p.security_id,p.date,p.source,p.feed,p.adjustment_basis
            ORDER BY obs.available_at DESC,p.raw_sha256 DESC)=1 ORDER BY p.security_id,p.date''',
            [source,feed,start,str(asof),cutoff,cutoff,cutoff,*symbols]).fetchdf()
    require_real_frame(prices)
    lineage=verify_lineage(prices,Path(raw_root))
    current=prices.loc[pd.to_datetime(prices.date).eq(pd.Timestamp(asof))]
    full=set(current.symbol)==set(symbols) and len(current)==len(symbols)
    raw=set(prices.adjustment_basis)=={'raw'}
    adjusted=set(prices.adjustment_basis)=={'yahoo_split_adjusted'}
    def state(missing):return {'status':'BLOCKED' if missing else 'PASS','missing_evidence':missing}
    caps={
        'observation':state([] if full else ['requested-session symbol coverage']),
        'raw_prices':state([] if raw else ['verified raw OHLCV']),
        'exploratory_price_factors':state([] if adjusted else ['corporate-action-consistent feature price series']),
        'historical_model':state(['not yet evaluated']),
        'industry_factors':state(['not yet evaluated']),
        'pit_fundamentals':state(['not yet evaluated']),
        'historical_backtest':state(['not yet evaluated']),
        'forward_data':state(['not yet evaluated']),
        'forward_shadow':state(['not yet evaluated'])}
    from .capability_checks import assess
    with duckdb.connect(str(database),read_only=True) as evidence_db:
        caps.update(assess(evidence_db,prices,Path(raw_root),asof,cutoff))
    meta={'source':source,'feed':feed,'adjustment_bases':sorted(set(prices.adjustment_basis)),
        'asof_date_et':str(pd.Timestamp(asof).date()),'knowledge_cutoff_utc':cutoff.isoformat(),
        'source_version_kind':'current_revised_snapshot','mode':'OBSERVATION_CURRENT_VINTAGE',
        'scope':('EXPLICIT_CURRENT_ETF_PROXY_LIST_NOT_PIT_UNIVERSE' if set(symbols)<=set(SYMBOLS)
                 else 'EXPLICIT_SYMBOL_LIST_NOT_HISTORICAL_PIT_UNIVERSE'),'symbols':symbols,'rows':len(prices),
        'latest_session_rows':len(current),'latest_session_complete':full,'snapshot_sha256':frame_hash(prices),
        'source_provenance':lineage,'historical_decision_eligible':False,'real_orders_enabled':False}
    return DatasetBundle(prices,meta,caps)
