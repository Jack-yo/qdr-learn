"""V4 CLI: run a source-hashed, non-executable four-layer Alpha study.

Expected managed folder:
 data/managed/v4_inputs/<bundle_id>/manifest.json
 data/managed/v4_inputs/<bundle_id>/factors.parquet
 data/managed/v4_inputs/<bundle_id>/labels.parquet
 data/managed/v4_inputs/<bundle_id>/market_style.parquet

This verifies local byte integrity. A manifest does NOT attest that the vendor
was historically point-in-time; outputs remain research-only even on success.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

import pandas as pd
import yaml

from quant_research.clock import TradingClock
from quant_research.models.v4_oos import OOSProtocol
from quant_research.research.v4_artifacts import write_research_run
from quant_research.workflow.v4_alpha import study_conditional_alpha


_ID = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_FILES = ('factors.parquet','labels.parquet','market_style.parquet')
_OPTIONAL_FILES = ('candidate_meta.parquet',)


def _checked_inputs(root, bundle_id):
    if not isinstance(bundle_id,str) or not _ID.fullmatch(bundle_id):
        raise ValueError('Invalid managed data bundle ID')
    folder=(root/'data/managed/v4_inputs'/bundle_id).resolve()
    if not folder.is_relative_to((root/'data/managed/v4_inputs').resolve()):
        raise ValueError('Research bundle path escapes project data')
    manifest_file=folder/'manifest.json'
    if not manifest_file.is_file():
        raise FileNotFoundError('Timestamped V4 input manifest missing')
    manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
    digests=manifest.get('artifacts_sha256')
    if (manifest.get('kind')!='V4_STRICT_LABEL_STUDY_INPUT'
            or not isinstance(digests,dict) or not set(_FILES).issubset(digests)
            or set(digests)-set(_FILES)-set(_OPTIONAL_FILES)
            or not isinstance(manifest.get('source_snapshot_sha256'),str)
            or not _SHA.fullmatch(manifest['source_snapshot_sha256'])):
        raise ValueError('Unrecognized source-hashed V4 research input contract')
    frames={}
    for name in digests:
        file=(folder/name).resolve()
        expected=digests[name]
        if (not file.is_relative_to(folder) or not file.is_file()
                or not isinstance(expected,str) or not _SHA.fullmatch(expected)
                or sha256(file.read_bytes()).hexdigest()!=expected):
            raise ValueError(f'Research input file changed: {name}')
        frames[name.split('.')[0]]=pd.read_parquet(file)
    manifest=dict(manifest)
    if 'l2_style_context_receipt' in manifest:
        from quant_research.workflow.l2_l3_binding import (
            validate_l2_style_binding_receipt)
        manifest['l2_style_context_receipt']=validate_l2_style_binding_receipt(
            manifest['l2_style_context_receipt'])
    return frames,manifest


def run_managed_alpha_study(root: Path, *, bundle_id: str, run_id: str,
                            evaluation_start: str, evaluation_end: str) -> dict:
    """Train and archive OOS research, without minting trading eligibility."""
    root=Path(root).resolve()
    frames,manifest=_checked_inputs(root,bundle_id)
    factor_names=manifest.get('factor_names')
    if (not isinstance(factor_names,list) or not factor_names
            or any(not isinstance(x,str) or not x for x in factor_names)):
        raise ValueError('Explicit factor names required in source bundle')
    binding_receipt=manifest.get('l2_style_context_receipt')
    if binding_receipt is not None:
        from quant_research.workflow.l2_l3_binding import (
            CONTRACT_VERSION, verify_l2_style_history_binding)
        verify_l2_style_history_binding(
            root,frames['market_style'],binding_receipt)
        if (
            binding_receipt.get('contract_version')==CONTRACT_VERSION
            and 'HISTORICAL_PIT_REPLAY'
                in set(binding_receipt.get('context_modes') or [])
        ):
            admission_day=pd.Timestamp(
                binding_receipt['admission_asof_session']
            )
            admission_frozen=pd.Timestamp(
                binding_receipt['admission_frozen_at_utc']
            )
            requested_start=pd.Timestamp(evaluation_start)
            if (
                requested_start.tzinfo is not None
                or admission_day.tzinfo is not None
                or admission_frozen.tzinfo is None
            ):
                raise ValueError(
                    'V4_L3_OOS_ADMISSION_TIME_INVALID'
                )
            frozen_day=(
                admission_frozen.tz_convert('America/New_York')
                .tz_localize(None).normalize()
            )
            admission_effective_day=max(admission_day,frozen_day)
            if requested_start<=admission_effective_day:
                raise ValueError(
                    'V4_L3_OOS_MUST_START_AFTER_L2_ADMISSION'
                )
    protocol_path=root/'configs/experiments/v4_research.yaml'
    config=yaml.safe_load(protocol_path.read_text(encoding='utf-8'))
    protocol=OOSProtocol(**config['oos'])
    clock=TradingClock()
    sessions=clock.calendar.sessions_in_range('2016-01-01',evaluation_end)
    eval_start=pd.Timestamp(evaluation_start)
    eval_end=pd.Timestamp(evaluation_end)
    if (eval_start.tzinfo is not None or eval_end.tzinfo is not None
            or eval_start>eval_end
            or eval_end>pd.Timestamp.now(tz='America/New_York').tz_localize(None)):
        raise ValueError('Evaluation window must be past or current XNYS sessions')
    requested=sessions[(sessions>=eval_start)&(sessions<=eval_end)]
    if len(requested)==0:
        raise ValueError('No eligible model evaluation sessions')
    results=study_conditional_alpha(
        factors=frames['factors'],labels=frames['labels'],
        market_style=frames['market_style'],trading_clock=clock,
        exchange_sessions=sessions,alpha_factor_names=factor_names,
        evaluation_dates=requested,
        source_snapshot_sha256=manifest['source_snapshot_sha256'],
        protocol=protocol)
    digest=sha256(protocol_path.read_bytes()).hexdigest()
    saved=write_research_run(root,run_id,results,
                             input_snapshot_sha256=manifest['source_snapshot_sha256'],
                             experiment_config_sha256=digest)
    return {'status':'V4_OOS_RESEARCH_ARCHIVED_NO_EXECUTION','run_id':run_id,
            'input_bundle_id':bundle_id,'artifact':saved['manifest_sha256'],
            'real_orders_enabled':False,'historical_decision_eligible':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='V4 timestamped Alpha OOS research; no trade orders')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--bundle-id',required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--evaluation-start',required=True)
    parser.add_argument('--evaluation-end',required=True)
    args=parser.parse_args(argv)
    print(json.dumps(run_managed_alpha_study(args.root,bundle_id=args.bundle_id,
        run_id=args.run_id,evaluation_start=args.evaluation_start,
        evaluation_end=args.evaluation_end),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
