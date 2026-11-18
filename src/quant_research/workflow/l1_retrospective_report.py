"""Archive a current-vintage ETF observation, never a frozen forecast."""
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

from quant_research.policy import SYMBOLS
from quant_research.workflow.l1_current_observation import current_observation_for_api


def write_retrospective_report(root: Path, asof: str, output: Path) -> dict:
    root=Path(root).resolve()
    payload=current_observation_for_api(root/'data/real_v21.duckdb',asof=asof,
                                        raw_root=root/'data/raw',symbols=SYMBOLS)
    if payload['asof_session']!=asof or payload['forecast'] is not None or payload['current_prediction_eligible'] is not False:
        raise ValueError('L1_RETROSPECTIVE_SCOPE_INVALID')
    target=Path(output)
    target.mkdir(parents=True,exist_ok=False)
    data=target/'observations.json'
    data.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,allow_nan=False),encoding='utf-8')
    columns=['feature_id','domain','source','frequency','start_date','end_date','available_at',
             'coverage_ratio','missing_rate','coverage_scope','PIT_status','research_eligible','blocked_reason']
    table=target/'feature_coverage.csv'
    with table.open('w',encoding='utf-8',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=columns);writer.writeheader()
        for feature in payload['features']:
            observed=feature['status']=='OBSERVED'
            writer.writerow({'feature_id':feature['id'],'domain':feature['domain'],
                'source':feature['source'] or '', 'frequency':'daily',
                'start_date':asof if observed else '', 'end_date':asof if observed else '',
                'available_at':feature['available_at'] or '', 'coverage_ratio':int(observed),
                'missing_rate':int(not observed), 'coverage_scope':'ASOF_FEATURE_AVAILABILITY_ONLY',
                'PIT_status':'NOT_INDEPENDENTLY_VERIFIED','research_eligible':False,
                'blocked_reason':'HISTORICAL_PIT_AND_CORPORATE_ACTIONS_NOT_VERIFIED' if observed else feature['reason']})
    result={'status':'CURRENT_VINTAGE_RETROSPECTIVE_OBSERVATION','asof_session':asof,
            'knowledge_cutoff_utc':payload['knowledge_cutoff_utc'],
            'source_snapshot_sha256':payload['source_snapshot_sha256'],
            'observed_features':sum(f['status']=='OBSERVED' for f in payload['features']),
            'registered_features':len(payload['features']),
            'outputs_sha256':{p.name:sha256(p.read_bytes()).hexdigest() for p in (data,table)},
            'coverage_scope':'ASOF_FEATURE_AVAILABILITY_ONLY',
            'historical_pit_verified':False,'model_admitted':False,'real_orders_enabled':False}
    (target/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False),encoding='utf-8')
    return result
