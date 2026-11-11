"""Immutable read-only archive for V4 out-of-sample research outputs.

A correct artifact hash proves local integrity, NOT real-source provenance,
PIT eligibility, statistical significance or permission for simulated orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import tempfile

import pandas as pd


_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_FRAMES = ('predictions','folds','metrics','increment_vs_alpha_only')
_FOLDER = Path('outputs/v4_research/runs')


def _path(root, run_id):
    if not isinstance(run_id,str) or not _ID.fullmatch(run_id):
        raise ValueError('Unsafe research run identifier')
    base = Path(root).resolve() / _FOLDER
    directory = (base / run_id).resolve()
    if not directory.is_relative_to(base.resolve()):
        raise ValueError('Research run escapes archive')
    return base, directory


def _digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_research_run(root, run_id: str, report: dict, *,
                       input_snapshot_sha256: str,
                       experiment_config_sha256: str) -> dict:
    """Write once. No overwrite, no fake provenance, no executable forecasts."""
    if not all(isinstance(v,str) and _SHA.fullmatch(v)
               for v in (input_snapshot_sha256,experiment_config_sha256)):
        raise ValueError('Research run requires actual source/config digests')
    if report.get('status') != 'RESEARCH_ONLY_NOT_ADMITTED_TO_PAPER':
        raise ValueError('Only non-executable V4 research may be stored here')
    for name in _FRAMES:
        if not isinstance(report.get(name),pd.DataFrame):
            raise ValueError(f'Missing research output: {name}')
    base,dest = _path(root,run_id)
    base.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        raise FileExistsError('An immutable research run with this ID already exists')
    with tempfile.TemporaryDirectory(prefix='.v4-writing-',dir=base) as temp:
        work = Path(temp)
        digests={}
        for name in _FRAMES:
            file = work / (name+'.parquet')
            report[name].to_parquet(file,index=False)
            digests[file.name] = _digest(file)
        manifest = {
            'schema_version':'v4-research-1',
            'run_id':run_id,
            'created_at_utc':datetime.now(timezone.utc).isoformat(),
            'input_snapshot_sha256':input_snapshot_sha256,
            'experiment_config_sha256':experiment_config_sha256,
            'model_variants':report.get('model_variants',{}),
            'panel_contract':report.get('panel_contract',{}),
            'source_independently_attested':False,
            'historical_decision_eligible':False,
            'research_only':True,'real_orders_enabled':False,
            'artifact_sha256':digests}
        (work/'manifest.json').write_text(
            json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False),
            encoding='utf-8')
        # Temporary sibling and one-time directory rename prevent partial
        # successful manifests. Incomplete earlier attempts cannot be reused.
        work.rename(dest)
        # TemporaryDirectory cleanup sees the renamed source as absent.
    return read_research_run(root,run_id,include_rows=False)


def read_research_run(root, run_id: str, *, include_rows=False) -> dict:
    _,folder = _path(root,run_id)
    if not folder.is_dir():
        raise FileNotFoundError('Research run does not exist')
    manifest_path=folder/'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Research manifest missing')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('schema_version')!='v4-research-1'
            or manifest.get('run_id')!=run_id
            or manifest.get('historical_decision_eligible') is not False
            or manifest.get('real_orders_enabled') is not False
            or manifest.get('source_independently_attested') is not False):
        raise ValueError('Research archive claims unsupported capabilities')
    hashes=manifest.get('artifact_sha256')
    if not isinstance(hashes,dict) or set(hashes)!={x+'.parquet' for x in _FRAMES}:
        raise ValueError('Missing or extra model result digests')
    for filename,expected in hashes.items():
        path=(folder/filename).resolve()
        if (not path.is_relative_to(folder.resolve()) or not path.is_file()
                or not isinstance(expected,str) or not _SHA.fullmatch(expected)
                or _digest(path)!=expected):
            raise ValueError(f'Corrupt research result artifact: {filename}')
    output={'status':'VERIFIED_LOCAL_RESEARCH_ARTIFACT_ONLY',
            'manifest':manifest,'manifest_sha256':_digest(manifest_path),
            'real_orders_enabled':False,'historical_decision_eligible':False}
    # Small numeric summaries can be used by the browser. Historical forecast
    # rows, with realized labels, remain in the research archive by default.
    names = _FRAMES if include_rows else ('metrics','increment_vs_alpha_only','folds')
    for name in names:
        frame=pd.read_parquet(folder/(name+'.parquet'))
        if name=='predictions' and len(frame)>50_000:
            raise ValueError('Full prediction archive exceeds safe response cap')
        output[name]=frame
    return output


def list_research_runs(root, *, limit=30) -> list[dict]:
    if type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Run list limit must be 1–100')
    base=Path(root).resolve()/_FOLDER
    if not base.is_dir():
        return []
    items=[]
    for folder in sorted(base.iterdir(),reverse=True):
        if not folder.is_dir() or not _ID.fullmatch(folder.name):
            continue
        try:
            content=read_research_run(root,folder.name,include_rows=False)
            manifest=content['manifest']
            items.append({'run_id':folder.name,'created_at_utc':manifest['created_at_utc'],
                          'input_snapshot_sha256':manifest['input_snapshot_sha256'],
                          'status':content['status'],'model_variants':list(manifest.get('model_variants',{}))})
        except (ValueError,OSError,KeyError,TypeError):
            items.append({'run_id':folder.name,'status':'CORRUPT_RESEARCH_RUN'})
        if len(items)>=limit:
            break
    return items
