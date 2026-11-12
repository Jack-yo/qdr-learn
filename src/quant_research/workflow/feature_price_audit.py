"""Reproducible raw-to-feature-price normalization audit, with no model or trading."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.data.feature_prices import build_split_prices, split_reference, compare_reference
from quant_research.data.http import HttpCache, DataUnavailable
from quant_research.data.providers.actions import ActionProvider
from quant_research.data.split_evidence import precision_diagnostics, review_issuer_splits, DOCUMENTS, issuer_headers


def execute(args):
    if args.offline and getattr(args, 'refresh_source_responses', False):
        raise ValueError('Offline audit cannot refresh source responses')
    cutoff = datetime.fromisoformat(args.cutoff) if args.cutoff else None
    raw_root = args.data_dir/'raw'
    bundle = load_real_bundle(args.db, asof=args.asof, cutoff=cutoff, start=args.start, raw_root=raw_root)
    bundle.require('observation')
    meta = bundle.metadata
    http = HttpCache(raw_root, offline=args.offline,
                     refresh=getattr(args, 'refresh_source_responses', False))
    # Fetch before setting the default knowledge cutoff. Explicit cutoffs never move.
    ActionProvider(http).events(meta['symbols'], args.action_start, args.action_end)
    reference, pages = split_reference(http, TradingClock(), meta['symbols'], args.start, meta['asof_date_et'])
    issuer_fetch_errors = []
    if args.issuer_documents:
        for url in DOCUMENTS.values():
            try:
                http.get(url, headers=issuer_headers(url,http.offline))
            except (DataUnavailable,FileNotFoundError) as exc:
                issuer_fetch_errors.append({'url':url,'code':getattr(exc,'code','OFFLINE_CACHE_MISSING')})
    bundle = load_real_bundle(args.db, asof=meta['asof_date_et'], cutoff=cutoff, start=args.start, raw_root=raw_root)
    if any(pd.Timestamp(p['retrieved_at_utc']) > pd.Timestamp(bundle.metadata['knowledge_cutoff_utc']) for p in pages):
        from quant_research.policy import PolicyError
        raise PolicyError('REFERENCE_AFTER_CUTOFF', 'Split reference was observed after the knowledge cutoff')
    features = build_split_prices(bundle, HttpCache(raw_root, offline=True), args.action_start, args.action_end)
    comparison = compare_reference(features, reference)
    precision = precision_diagnostics(bundle, features, reference, raw_root)
    issuer = review_issuer_splits(features, HttpCache(raw_root, offline=True), bundle.metadata['knowledge_cutoff_utc']) if args.issuer_documents else None
    if issuer is not None:
        issuer['fetch_errors'] = issuer_fetch_errors
    output = args.output/str(uuid4())
    output.mkdir(parents=True)
    features.prices.to_parquet(output/'feature_prices.parquet', index=False)
    reference.to_parquet(output/'vendor_split_reference.parquet', index=False)
    (output/'comparison.json').write_text(json.dumps(comparison, indent=2), encoding='utf-8')
    (output/'precision.json').write_text(json.dumps(precision, indent=2), encoding='utf-8')
    if issuer is not None:
        (output/'issuer_checks.json').write_text(json.dumps(issuer, indent=2), encoding='utf-8')
    manifest = {**features.metadata, 'run_id': output.name, 'stage': 'G4',
                'status': 'NORMALIZATION_VERIFIED_CURRENT_VINTAGE' if comparison['status']=='PASS' else 'BLOCKED',
                'knowledge_cutoff_utc': bundle.metadata['knowledge_cutoff_utc'],
                'reference_pages': pages, 'reference_comparison': comparison,
                'precision_diagnostic': precision, 'issuer_review': issuer,
                'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'prediction_rows': 0, 'modelled_fills': 0, 'sealed_strategy_test_used': False,
                'raw_source_provenance': bundle.metadata['source_provenance']}
    package = Path(__file__).resolve().parents[1]
    manifest['code_sha256'] = hashlib.sha256(b''.join(p.relative_to(package).as_posix().encode()+p.read_bytes()
                                                     for p in sorted(package.rglob('*.py')))).hexdigest()
    manifest['artifacts_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output.resolve()), 'status': manifest['status'], 'rows': features.metadata['rows'],
                      'splits': len(features.metadata['applied_splits']), 'reference_status': comparison['status']}), flush=True)
    return 0 if comparison['status']=='PASS' else 4
