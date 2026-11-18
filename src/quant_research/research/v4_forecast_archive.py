"""Source-linked, append-only V4 forward research forecast archive.

Do not persist realized outcomes in a T-day forecast artifact. A local hash
does not grant historical PIT, model validation or paper trading privileges.
"""
from __future__ import annotations

from hashlib import sha256
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile

import pandas as pd


_SHA=re.compile(r'[a-f0-9]{64}\Z')
_ID=re.compile(r'[a-f0-9]{16}\Z')
_ROOT=Path('outputs/v4_forecasts')
_FILE_NAMES=('forecasts.parquet','model_cards.parquet')
_BANNED=frozenset({'gross_return','excess_return','actual_return','future_return',
                   'realized_return','net_pnl','broker_order_id'})

def _validated_input_contract(contract):
    """Bind exact input bytes/cohort and optional verified L2 style receipt."""
    if contract is None:
        return None  # Legacy v1 research-only archive compatibility.
    required={'artifacts_sha256','factor_names','source_symbols'}
    optional={'l2_style_context_receipt'}
    if (not isinstance(contract,dict) or required-set(contract)
            or set(contract)-required-optional):
        raise ValueError('Invalid V4 forward input provenance contract')
    files,names,symbols=(contract[key] for key in
                         ('artifacts_sha256','factor_names','source_symbols'))
    if (not isinstance(files,dict) or not
            {'factors.parquet','labels.parquet','market_style.parquet'}<=set(files)
            or any(not isinstance(key,str) or not key.endswith('.parquet')
                   or not isinstance(value,str) or not _SHA.fullmatch(value)
                   for key,value in files.items())):
        raise ValueError('Incomplete V4 forward input byte fingerprints')
    if (not isinstance(names,list) or not names or len(set(names))!=len(names)
            or any(not isinstance(x,str) or not x for x in names)
            or not isinstance(symbols,list) or len(set(symbols))!=len(symbols)
            or any(not isinstance(x,str) or not x for x in symbols)):
        raise ValueError('Invalid V4 factor/security cohort fingerprint')
    output={'artifacts_sha256':dict(sorted(files.items())),
            'factor_names':list(names),'source_symbols':list(symbols)}
    if 'l2_style_context_receipt' in contract:
        from quant_research.workflow.l2_l3_binding import (
            validate_l2_style_binding_receipt)
        output['l2_style_context_receipt']=validate_l2_style_binding_receipt(
            contract['l2_style_context_receipt'])
    return output


def forecast_archive_identity(day,source,protocol_sha256,*,input_contract=None):
    """V2 binds exact local dataset artifacts; V1 reads remain compatible."""
    if any(not isinstance(x,str) or not _SHA.fullmatch(x)
           for x in (source,protocol_sha256)):
        raise ValueError('Valid source and protocol SHA256 required')
    validated=_validated_input_contract(input_contract)
    if validated is None:
        return sha256((str(day)+source+protocol_sha256).encode()).hexdigest()[:16]
    key={'day':str(day),'source':source,'protocol':protocol_sha256,
         'input_contract':validated,'schema':'v4-forward-2'}
    return sha256(json.dumps(key,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:16]


def _hash(path):
    return sha256(path.read_bytes()).hexdigest()


def _loc(root, day, ident):
    date=pd.Timestamp(day)
    if date.tzinfo is not None or date.date().isoformat()!=str(day):
        raise ValueError('Unsafe forecast session')
    if not isinstance(ident,str) or not _ID.fullmatch(ident):
        raise ValueError('Unsafe forecast identity')
    base=Path(root).resolve()/_ROOT
    folder=(base/str(day)/ident).resolve()
    if not folder.is_relative_to(base.resolve()):
        raise ValueError('Forecast path escaped archive')
    return base,folder


def freeze_research_forecast(root, report: dict, *, protocol_sha256: str,
                             input_contract: dict | None = None) -> dict:
    """Freeze one as-of model output. Does not write paper orders."""
    if report.get('status')!='FORWARD_RESEARCH_PREDICTIONS_ONLY':
        raise ValueError('Cannot freeze a missing/blocked forecast as a successful run')
    data=report.get('forecasts')
    cards=report.get('model_cards')
    if (not isinstance(data,pd.DataFrame) or data.empty
            or not isinstance(cards,pd.DataFrame) or cards.empty):
        raise ValueError('Forecast and model evidence must both exist')
    if _BANNED.intersection(data.columns):
        raise ValueError('Forward archive cannot contain realized future outcomes or order IDs')
    if 'decision_eligible' not in data or not data.decision_eligible.eq(False).all():
        raise ValueError('Research forecasts cannot be execution-eligible')
    day=report.get('asof_session')
    source=report.get('source_snapshot_sha256')
    if not all(isinstance(x,str) and _SHA.fullmatch(x) for x in (source,protocol_sha256)):
        raise ValueError('Source and research protocol digests required')
    from quant_research.clock import TradingClock
    clock=TradingClock()
    window=clock.window(day,1)
    created=datetime.now(timezone.utc)
    genuine_forward=bool(pd.Timestamp(window.signal_time) <= pd.Timestamp(created)
                         < pd.Timestamp(window.entry_time))
    validated=_validated_input_contract(input_contract)
    identity=forecast_archive_identity(day,source,protocol_sha256,
                                       input_contract=validated)
    base,dest=_loc(root,day,identity)
    if dest.exists():
        raise FileExistsError('Already froze this input/protocol/day')
    base_dir=dest.parent
    base_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.writing-',dir=base_dir) as temporary:
        work=Path(temporary)
        hashes={}
        for name,frame in [('forecasts.parquet',data),('model_cards.parquet',cards)]:
            target=work/name
            frame.to_parquet(target,index=False)
            hashes[name]=_hash(target)
        manifest={'schema':('v4-forward-2' if validated is not None else 'v4-forward-1'),
                  'session_date_et':str(day),
                  'identity':identity,'source_snapshot_sha256':source,
                  'protocol_sha256':protocol_sha256,
                  'forecast_rows':len(data),'model_cards':len(cards),
                  'artifacts_sha256':hashes,
                  'created_at_utc':created.isoformat(),
                  'prospective_before_next_open':genuine_forward,
                  'status':('PROSPECTIVE_FORWARD_RESEARCH_ONLY' if genuine_forward
                            else 'RETROSPECTIVE_ASOF_RECONSTRUCTION_ONLY'),
                  'decision_eligible':False,'source_independently_attested':False,
                  'real_orders_enabled':False}
        if validated is not None:
            manifest['input_contract']=validated
            manifest['input_contract_sha256']=sha256(json.dumps(
                validated,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (work/'manifest.json').write_text(
            json.dumps(manifest,sort_keys=True,indent=2,allow_nan=False),encoding='utf-8')
        if dest.exists():
            raise FileExistsError('Concurrent forecast archive exists')
        work.rename(dest)
    return read_research_forecast(root,day,identity,include_rows=False)


def read_research_forecast(root, day, identity, *, include_rows=False):
    _,folder=_loc(root,day,identity)
    path=folder/'manifest.json'
    if not path.is_file():
        raise FileNotFoundError('Forecast record unavailable')
    manifest=json.loads(path.read_text(encoding='utf-8'))
    if (manifest.get('schema') not in ('v4-forward-1','v4-forward-2')
            or manifest.get('identity')!=identity
            or manifest.get('session_date_et')!=str(day)
            or manifest.get('decision_eligible') is not False
            or manifest.get('real_orders_enabled') is not False
            or manifest.get('source_independently_attested') is not False
            or type(manifest.get('prospective_before_next_open')) is not bool
            or set(manifest.get('artifacts_sha256',{}))!=set(_FILE_NAMES)):
        raise ValueError('Forecast record is not a restricted research archive')
    if manifest['schema']=='v4-forward-2':
        contract=_validated_input_contract(manifest.get('input_contract'))
        if contract is None:
            raise ValueError('V2 input provenance missing')
        contract_digest=sha256(json.dumps(contract,sort_keys=True,
            separators=(',',':')).encode()).hexdigest()
        if (manifest.get('input_contract_sha256')!=contract_digest or
                forecast_archive_identity(day,manifest.get('source_snapshot_sha256'),
                    manifest.get('protocol_sha256'),input_contract=contract)!=identity):
            raise ValueError('Frozen forecast input provenance or identity changed')
    # The manifest's prospective flag must agree with its actual recorded
    # creation timestamp and the exchange's next-open window. A replay
    # after T+1 cannot be upgraded by merely changing a JSON boolean.
    try:
        from quant_research.clock import TradingClock
        window=TradingClock().window(day,1)
        created=pd.Timestamp(manifest['created_at_utc'])
        if created.tzinfo is None:
            raise ValueError('Forecast creation time must be UTC aware')
        expected=bool(pd.Timestamp(window.signal_time)<=created
                      <pd.Timestamp(window.entry_time))
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Invalid frozen forecast creation timestamp') from exc
    if expected is not manifest['prospective_before_next_open']:
        raise ValueError('Forecast prospective timing flag contradicts its timestamp')
    for name in _FILE_NAMES:
        artifact=(folder/name).resolve()
        digest=manifest['artifacts_sha256'][name]
        if (not artifact.is_relative_to(folder.resolve())
                or not artifact.is_file() or not isinstance(digest,str)
                or not _SHA.fullmatch(digest) or _hash(artifact)!=digest):
            raise ValueError(f'Forecast artifact is missing or corrupt: {name}')
    info={'status':('VERIFIED_LOCAL_FORWARD_RESEARCH_ONLY'
                    if manifest['prospective_before_next_open']
                    else 'VERIFIED_LOCAL_RETROSPECTIVE_ASOF_ONLY'),
          'manifest':manifest,
          'manifest_sha256':_hash(path),'real_orders_enabled':False}
    if include_rows:
        forecasts=pd.read_parquet(folder/'forecasts.parquet')
        if len(forecasts)>100000 or _BANNED.intersection(forecasts.columns):
            raise ValueError('Forward archive has invalid or excessive forecast rows')
        if not forecasts.decision_eligible.eq(False).all():
            raise ValueError('Forecast cannot become execution-eligible')
        info['forecasts']=forecasts
        info['model_cards']=pd.read_parquet(folder/'model_cards.parquet')
    return info


def latest_forward_research(root, *, limit=5):
    if type(limit) is not int or not 1<=limit<=20:
        raise ValueError('Invalid archive limit')
    base=Path(root).resolve()/_ROOT
    if not base.is_dir():
        return []
    items=[]
    for session_dir in sorted(base.iterdir(),reverse=True):
        if not session_dir.is_dir():
            continue
        for folder in sorted(session_dir.iterdir(),reverse=True):
            if not folder.is_dir():
                continue
            try:
                item=read_research_forecast(root,session_dir.name,folder.name)
                receipt=(item['manifest'].get('input_contract') or {}).get(
                    'l2_style_context_receipt')
                items.append({'session_date_et':session_dir.name,
                              'identity':folder.name,'status':item['status'],
                              'forecast_rows':item['manifest']['forecast_rows'],
                              'model_cards':item['manifest']['model_cards'],
                              'source_snapshot_sha256':item['manifest']['source_snapshot_sha256'],
                              'l2_style_binding_verified':bool(
                                  receipt and receipt.get('binding_verified') is True),
                              'l2_style_historical_pit_attested':bool(
                                  receipt and receipt.get('historical_pit_attested') is True),
                              'l2_style_binding_context_sha256':(
                                  receipt.get('context_identity_sha256')
                                  if receipt else None)})
            except (ValueError,OSError,KeyError,TypeError):
                items.append({'session_date_et':session_dir.name,
                              'identity':folder.name,'status':'CORRUPT_FORECAST_ARCHIVE'})
            if len(items)>=limit:
                return items
    return items
