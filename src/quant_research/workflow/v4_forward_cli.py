"""CLI for a strictly labeled, forward-only V4 research forecast.

This is deliberately separate from paper/order execution. No future outcome
is read or saved into the frozen research forecast.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
import yaml

from quant_research.clock import TradingClock
from quant_research.models.v4_forward import forecast_asof
from quant_research.models.v4_oos import OOSProtocol
from quant_research.models.v4_panel import prepare_v4_alpha_panel
from quant_research.research.v4_forecast_archive import (freeze_research_forecast,
    read_research_forecast, forecast_archive_identity)
from quant_research.workflow.v4_study_cli import _checked_inputs


def run_managed_forward(root: Path, *, bundle_id: str, asof_session: str) -> dict:
    root=Path(root).resolve()
    inputs,manifest=_checked_inputs(root,bundle_id)
    factor_names=manifest.get('factor_names')
    if not isinstance(factor_names,list) or not factor_names:
        raise ValueError('Input bundle needs explicit registered Alpha factors')
    config_path=root/'configs/experiments/v4_research.yaml'
    policy=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    protocol=OOSProtocol(**policy['oos'])
    clock=TradingClock()
    day=clock.session(asof_session)
    signal=clock.signal(day)  # Cannot generate a pre-close "after-close" prediction.
    # Model-only historical studies may omit candidate metadata, but any
    # forward bundle claiming candidate provenance must pass the complete
    # same-day cohort audit even when called outside the V4 daily orchestrator.
    if 'candidate_meta' in inputs:
        from quant_research.workflow.v4_bundle_contract import audit_forward_candidate_cohort
        audit_forward_candidate_cohort(inputs,manifest,day,signal)
    config_sha=sha256(config_path.read_bytes()).hexdigest()
    input_contract={'artifacts_sha256':manifest['artifacts_sha256'],
                    'factor_names':factor_names,
                    'source_symbols':manifest.get('source_symbols') or []}
    archive_id=forecast_archive_identity(str(day.date()),
        manifest['source_snapshot_sha256'],config_sha,input_contract=input_contract)
    try:
        existing=read_research_forecast(root,str(day.date()),archive_id,include_rows=False)
    except FileNotFoundError:
        existing=None
    if existing:
        return {'status':('FORWARD_RESEARCH_ALREADY_FROZEN'
                         if existing['manifest']['prospective_before_next_open']
                         else 'RETROSPECTIVE_ASOF_ALREADY_ARCHIVED'),
                'prospective_before_next_open':existing['manifest']['prospective_before_next_open'],
                'session_date_et':str(day.date()),'identity':archive_id,
                'forecast_rows':existing['manifest']['forecast_rows'],
                'source_snapshot_sha256':manifest['source_snapshot_sha256'],
                'execution_eligible':False,'real_orders_enabled':False}
    features,scope=prepare_v4_alpha_panel(
        inputs['factors'],inputs['labels'],inputs['market_style'],clock,
        expected_factor_names=factor_names)
    feature_columns=scope['market_style_columns']
    market=[x for x in feature_columns if x.startswith('market_') and pd.api.types.is_numeric_dtype(features[x])]
    style=[x for x in feature_columns if x.startswith('style_') and pd.api.types.is_numeric_dtype(features[x])]
    if not market or not style:
        raise ValueError('Both genuine market and style condition features required')
    variants={'A':factor_names,'B':factor_names+market,
              'C':factor_names+style,'D':factor_names+market+style}
    exchange_sessions=clock.calendar.sessions_in_range('2016-01-01',asof_session)
    report=forecast_asof(features,variants,exchange_sessions,day,
                         source_snapshot_sha256=manifest['source_snapshot_sha256'],
                         protocol=protocol)
    if report['status']!='FORWARD_RESEARCH_PREDICTIONS_ONLY':
        return {'status':report['status'],'session_date_et':asof_session,
                'execution_eligible':False,'real_orders_enabled':False}
    frozen=freeze_research_forecast(root,report,
                                   protocol_sha256=config_sha,
                                   input_contract=input_contract)
    return {'status':('FORWARD_RESEARCH_FROZEN_ONLY'
                       if frozen['manifest']['prospective_before_next_open']
                       else 'RETROSPECTIVE_ASOF_RECONSTRUCTION_ONLY'),
            'prospective_before_next_open':frozen['manifest']['prospective_before_next_open'],
            'session_date_et':asof_session,
            'identity':frozen['manifest']['identity'],
            'forecast_rows':frozen['manifest']['forecast_rows'],
            'source_snapshot_sha256':manifest['source_snapshot_sha256'],
            'execution_eligible':False,'real_orders_enabled':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description='V4 research-only day-close forecast')
    parser.add_argument('--root',type=Path,default=Path.cwd())
    parser.add_argument('--bundle-id',required=True)
    parser.add_argument('--asof',required=True)
    args=parser.parse_args(argv)
    print(json.dumps(run_managed_forward(args.root,bundle_id=args.bundle_id,
                                          asof_session=args.asof),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
