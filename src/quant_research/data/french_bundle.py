"""Read-only, source-reconciled French factor vintages for descriptive monitoring."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

import pandas as pd

from quant_research.clock import TradingClock,utc
from quant_research.policy import PolicyError
from .bundle import frame_hash
from .providers.french import FILES,parse_daily_zip
from .store import duckdb


FACTORS=('Mkt-RF','SMB','HML','RMW','CMA','Mom','ST_Rev','RF')
BASE='https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/'
DATASET_FACTORS={'ff5':{'Mkt-RF','SMB','HML','RMW','CMA','RF'},'momentum':{'Mom'},'reversal':{'ST_Rev'}}


@dataclass(frozen=True)
class FrenchBundle:
    _frame:pd.DataFrame
    _metadata:dict

    @property
    def frame(self):
        if frame_hash(self._frame)!=self._metadata['snapshot_sha256']:
            raise PolicyError('FACTOR_SNAPSHOT_MUTATED','Factor snapshot changed after source reconciliation')
        return self._frame.copy(deep=True)

    @property
    def metadata(self):return deepcopy(self._metadata)


def verify_french_rows(frame,raw_root):
    receipts={}
    for path in (raw_root/'receipts').glob('*.json'):
        try:r=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):continue
        if r.get('url') in {BASE+f for f in FILES.values()} and r.get('params')=={}:
            receipts.setdefault(r.get('sha256'),[]).append(r)
    evidence=[]
    for version,group in frame.groupby('version'):
        if len(str(version))!=64 or any(c not in '0123456789abcdef' for c in str(version)):
            raise PolicyError('FACTOR_SOURCE_HASH_INVALID','Factor version must identify the raw ZIP')
        path=raw_root/'objects'/version
        if not path.is_file():raise PolicyError('FACTOR_RAW_MISSING','Factor source ZIP is unavailable',[version])
        body=path.read_bytes()
        if hashlib.sha256(body).hexdigest()!=version:raise PolicyError('FACTOR_RAW_CORRUPT','Factor ZIP SHA256 mismatch')
        matched=receipts.get(version,[])
        if not matched:raise PolicyError('FACTOR_RECEIPT_MISSING','No official factor URL receipt matches the source ZIP')
        datasets={name for name,file in FILES.items() if any(r['url']==BASE+file for r in matched)}
        if len(datasets)!=1:raise PolicyError('FACTOR_SOURCE_AMBIGUOUS','Factor ZIP has ambiguous source identity')
        dataset=next(iter(datasets));observed=min(pd.Timestamp(r['fetched_at']) for r in matched)
        if set(group.factor_name)-DATASET_FACTORS[dataset]:raise PolicyError('FACTOR_SOURCE_MISMATCH','Factor names do not match their source file')
        if pd.to_datetime(group.available_at,utc=True).min()<observed:
            raise PolicyError('FACTOR_AVAILABILITY_MISMATCH','Stored factors predate source observation')
        lookup={(r.date,r.factor_name):r.value_decimal for r in parse_daily_zip(body,observed.to_pydatetime(),version)}
        for row in group.itertuples():
            key=(pd.Timestamp(row.date).date(),row.factor_name)
            expected=lookup.get(key)
            if key not in lookup or not ((pd.isna(expected) and pd.isna(row.value_decimal)) or expected==row.value_decimal):
                raise PolicyError('FACTOR_LINEAGE_MISMATCH','Stored factor differs from the raw published value',[row.factor_name,str(row.date)])
        evidence.append({'dataset':dataset,'source_url':BASE+FILES[dataset],'raw_sha256':version,
                         'first_observed_utc':observed.isoformat(),'verified_rows':len(group)})
    return evidence


def load_french_bundle(database,raw_root,start='2017-01-03',asof=None,cutoff=None,mode='observation'):
    if mode not in ('observation','research'):raise ValueError('Unknown factor monitoring mode')
    cutoff=utc(cutoff or datetime.now(timezone.utc))
    if cutoff>datetime.now(timezone.utc):raise PolicyError('FUTURE_CUTOFF','Knowledge cutoff cannot be in the future')
    if pd.Timestamp(start)<pd.Timestamp('2017-01-01'):raise ValueError('Monitor scope begins in 2017')
    if mode=='research':
        asof=asof or '2024-12-31'
        if pd.Timestamp(asof)>pd.Timestamp('2024-12-31'):
            raise PolicyError('SEALED_TEST_REJECTED','Research monitoring cannot open the sealed strategy test period')
    database=Path(database)
    for parent in database.parents:
        lock=parent/'catalog/.maintenance.lock'
        if lock.is_file():
            owner=json.loads(lock.read_text(encoding='utf-8'))
            if owner.get('pid')!=os.getpid():
                raise PolicyError('DATA_MAINTENANCE_RUNNING','Factor maintenance is running')
    if not database.is_file():raise PolicyError('NO_FRENCH_DATA','Managed French factor store is unavailable',['maintain-data --groups french'])
    with duckdb.connect(str(database),read_only=True) as db:
        db.execute("SET TimeZone='UTC'")
        if asof is None:
            asof=db.execute("SELECT max(date) FROM factor_returns WHERE source='KEN_FRENCH' AND use_policy='ATTRIBUTION_ONLY' AND available_at<=?",[cutoff]).fetchone()[0]
        if asof is None:raise PolicyError('NO_FRENCH_DATA','No factor vintage available at this knowledge cutoff')
        clock=TradingClock();clock.signal(str(asof))
        frame=db.execute("""SELECT * FROM factor_returns WHERE source='KEN_FRENCH' AND use_policy='ATTRIBUTION_ONLY'
            AND date>=? AND date<=? AND available_at<=?
            QUALIFY row_number() OVER(PARTITION BY date,factor_name ORDER BY available_at DESC,version DESC)=1
            ORDER BY date,factor_name""",[start,str(asof),cutoff]).fetchdf()
    if frame.empty:raise PolicyError('NO_FRENCH_DATA','No factor rows match the requested range and cutoff')
    if set(frame.factor_name)-set(FACTORS):raise PolicyError('UNSUPPORTED_FRENCH_FACTOR','Unreviewed factor names in store')
    if pd.to_datetime(frame.date).max()!=pd.Timestamp(asof):
        raise PolicyError('FRENCH_ASOF_UNAVAILABLE','Requested observation date is not covered; no fallback to older data',
                          ['latest available: '+str(pd.to_datetime(frame.date).max().date())])
    proof=verify_french_rows(frame,Path(raw_root))
    meta={'source':'FRENCH','provider':'KEN_FRENCH','use_policy':'ATTRIBUTION_ONLY','mode':mode.upper(),
          'asof_date_et':str(pd.Timestamp(asof).date()),'start_date':start,'data_cutoff_utc':cutoff.isoformat(),
          'source_version_kind':'current_revised_snapshot','rows':len(frame),'snapshot_sha256':frame_hash(frame),
          'source_provenance':proof,'historical_decision_eligible':False,'research_grade':False,
          'execution_ready':False,'real_orders_enabled':False,'sealed_strategy_test_used':False,
          'limitations':['CURRENT_VINTAGE_NOT_HISTORICAL_PUBLICATION','FACTOR_PUBLICATION_LAG_UNVERIFIED',
                         'FRENCH_FACTORS_ARE_NOT_ETF_PROXY_RETURNS','DESCRIPTIVE_STATES_ARE_NOT_PREDICTIONS']}
    return FrenchBundle(frame,meta)
