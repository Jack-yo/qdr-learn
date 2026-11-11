"""V4 fail-closed end-of-day stage orchestrator and immutable run diary.

This is orchestration, not a credentialed market-data provider or a source of
model approval. Stages must be supplied by registered server-side adapters.
No strategy result may mint its own verified-trading status.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

from quant_research.policy import PolicyError


_STAGES=('data','market','styles','alpha','risk','freeze')
_DIGEST=re.compile(r'[0-9a-f]{64}\Z')


def _canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,
                      allow_nan=False,separators=(',',':'))


def run_v4_daily(root, session_date: str, *, source_snapshot_sha256: str,
                 protocol_sha256: str, adapters: dict) -> dict:
    """Execute T after close. Never advances the paper ledger automatically.

    A stage may return {'status':'PASS','detail':...}, 'RESEARCH_ONLY',
    'NO_TRADE', or 'BLOCKED'. Once any stage fails, the later stages are
    skipped and the full result is frozen for audit.
    """
    day=date.fromisoformat(session_date)
    if day.isoformat()!=session_date:
        raise ValueError('Session date must use ISO format')
    from quant_research.clock import TradingClock
    TradingClock().signal(session_date)  # Reject weekends and pre-close execution
    if not all(isinstance(x,str) and _DIGEST.fullmatch(x)
               for x in (source_snapshot_sha256,protocol_sha256)):
        raise ValueError('Complete source/protocol hashes required')
    if set(adapters)-set(_STAGES) or any(not callable(v) for v in adapters.values()):
        raise ValueError('Stage adapters must be known server-side callables')
    base=Path(root).resolve()/'outputs/v4_daily'/session_date
    identity=sha256((session_date+source_snapshot_sha256+protocol_sha256).encode()).hexdigest()[:16]
    folder=base/identity
    manifest_path=folder/'manifest.json'
    if manifest_path.is_file():
        existing=json.loads(manifest_path.read_text(encoding='utf-8'))
        if existing.get('identity')!=identity:
            raise ValueError('Immutable end-of-day manifest ID mismatch')
        return existing
    stages=[]
    for stage in _STAGES:
        fn=adapters.get(stage)
        if fn is None:
            stages.append({'stage':stage,'status':'BLOCKED','code':'STAGE_ADAPTER_NOT_CONNECTED'})
            break
        # No actual research-only output may silently become an order.
        try:
            result=fn(session_date,tuple(stages))
            if not isinstance(result,dict) or result.get('status') not in ('PASS','RESEARCH_ONLY','NO_TRADE','BLOCKED'):
                raise ValueError('Unknown stage result')
            entry={'stage':stage,'status':result['status'],
                   'code':str(result.get('code',''))[:120],
                   'detail':result.get('detail',{})}
            _canonical(entry)   # No NaN or unbounded unserializable data.
        except (Exception,) as exc:
            entry={'stage':stage,'status':'BLOCKED','code':type(exc).__name__}
        stages.append(entry)
        if entry['status'] != 'PASS':
            break
    completed=len(stages)==len(_STAGES) and all(x['status']=='PASS' for x in stages)
    # Successful orchestration does not prove the stage's underlying model
    # or market-data evidence. Proof admission is a separate code boundary.
    result={'schema_version':'v4-daily-1',
            'identity':identity,'session_date_et':session_date,
            'source_snapshot_sha256':source_snapshot_sha256,
            'protocol_sha256':protocol_sha256,
            'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'status':'STAGES_COMPLETE_ADMISSION_PENDING' if completed else 'BLOCKED_OR_NO_TRADE',
            'stages':stages,'real_orders_enabled':False,
            'execution_eligible':False,
            'paper_ledger_advanced':False}
    result['content_sha256']=sha256(_canonical(result).encode()).hexdigest()
    base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.writing-',dir=base) as temp:
        work=Path(temp)
        (work/'manifest.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,
            sort_keys=True,allow_nan=False),encoding='utf-8')
        if folder.exists():
            raise FileExistsError('Daily snapshot was written concurrently')
        work.rename(folder)
    return result


def read_v4_daily(root, session_date: str, identity: str) -> dict:
    day=date.fromisoformat(session_date)
    if day.isoformat()!=session_date or not re.fullmatch(r'[a-f0-9]{16}',identity):
        raise ValueError('Invalid daily archive location')
    path=(Path(root).resolve()/'outputs/v4_daily'/session_date/identity/'manifest.json')
    if not path.is_file():
        raise FileNotFoundError('Daily V4 run missing')
    result=json.loads(path.read_text(encoding='utf-8'))
    digest=result.pop('content_sha256',None)
    if digest!=sha256(_canonical(result).encode()).hexdigest():
        raise PolicyError('DAILY_MANIFEST_TAMPERED','Recorded daily research cannot be modified')
    result['content_sha256']=digest
    if (result.get('session_date_et')!=session_date
            or result.get('identity')!=identity
            or result.get('execution_eligible') is not False
            or result.get('real_orders_enabled') is not False):
        raise PolicyError('DAILY_RUN_SCOPE_INVALID','Daily archive claims unsupported execution')
    return result
