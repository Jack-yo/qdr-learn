"""Feature-price evidence for strict normalization audits and L3 forward research.

The strict G4 raw-to-adjusted reconstruction audit and the prospective L3
feature admission are intentionally separate.  A mismatch in our local split
reconstruction must remain visible, but it must not prevent research-only use
of the provider's own source-hashed split-adjusted SIP bars.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pandas as pd

from quant_research.clock import TradingClock
from quant_research.data.bundle import load_real_bundle
from quant_research.data.feature_prices import (
    build_split_prices, split_reference, compare_reference,
    vendor_split_features,
)
from quant_research.data.http import HttpCache, DataUnavailable
from quant_research.data.providers.actions import ActionProvider
from quant_research.data.split_evidence import (
    precision_diagnostics, review_issuer_splits, DOCUMENTS, issuer_headers,
)
from quant_research.policy import PolicyError


def _verify_reference_receipts(raw_root, pages):
    """Require immutable receipts for every vendor-normalized response page."""
    raw_root = Path(raw_root)
    receipts = {}
    for path in (raw_root / 'receipts').glob('*.json'):
        try:
            receipt = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        receipts.setdefault(receipt.get('request_key'), []).append(receipt)
    verified = []
    for page in pages:
        digest = page.get('raw_sha256')
        request_key = page.get('request_key')
        fetched = page.get('retrieved_at_utc')
        object_path = raw_root / 'objects' / str(digest)
        if (not isinstance(digest, str) or len(digest) != 64
                or not object_path.is_file()
                or hashlib.sha256(object_path.read_bytes()).hexdigest() != digest):
            raise PolicyError(
                'VENDOR_SPLIT_RESPONSE_MISSING',
                'Vendor split-adjusted response object failed content verification',
            )
        matches = [
            r for r in receipts.get(request_key, [])
            if r.get('sha256') == digest
            and r.get('fetched_at') == fetched
            and r.get('url') == 'https://data.alpaca.markets/v2/stocks/bars'
            and (r.get('params') or {}).get('adjustment') == 'split'
            and (r.get('params') or {}).get('feed') == 'sip'
            and (r.get('params') or {}).get('timeframe') == '1Day'
            and (r.get('params') or {}).get('asof') == '-'
        ]
        if not matches:
            raise PolicyError(
                'VENDOR_SPLIT_RECEIPT_MISSING',
                'Vendor split-adjusted page lacks a matching immutable receipt',
            )
        verified.append({
            'request_key': request_key,
            'raw_sha256': digest,
            'retrieved_at_utc': fetched,
        })
    if not verified:
        raise PolicyError(
            'VENDOR_SPLIT_RECEIPT_MISSING',
            'No vendor split-adjusted source pages were verified',
        )
    return {'verified_pages': len(verified), 'pages': verified}


def _code_sha():
    package = Path(__file__).resolve().parents[1]
    return hashlib.sha256(b''.join(
        p.relative_to(package).as_posix().encode() + p.read_bytes()
        for p in sorted(package.rglob('*.py'))
    )).hexdigest()


def _write_run(output, features, reference, manifest, *, comparison=None,
               precision=None, issuer=None):
    output.mkdir(parents=True)
    features.prices.to_parquet(output / 'feature_prices.parquet', index=False)
    reference.to_parquet(output / 'vendor_split_reference.parquet', index=False)
    if comparison is not None:
        (output / 'comparison.json').write_text(
            json.dumps(comparison, indent=2), encoding='utf-8')
    if precision is not None:
        (output / 'precision.json').write_text(
            json.dumps(precision, indent=2), encoding='utf-8')
    if issuer is not None:
        (output / 'issuer_checks.json').write_text(
            json.dumps(issuer, indent=2), encoding='utf-8')
    manifest['code_sha256'] = _code_sha()
    manifest['artifacts_sha256'] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in output.iterdir()
    }
    (output / 'manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')


def execute(args):
    if args.offline and getattr(args, 'refresh_source_responses', False):
        raise ValueError('Offline audit cannot refresh source responses')
    purpose = getattr(args, 'purpose', 'normalization-audit')
    if purpose not in {'normalization-audit', 'l3-forward'}:
        raise ValueError('Unknown feature-price audit purpose')
    if purpose == 'l3-forward' and getattr(args, 'issuer_documents', False):
        raise ValueError('Issuer-document review belongs to normalization-audit')
    if purpose == 'normalization-audit' and not getattr(args, 'action_end', None):
        raise ValueError('normalization-audit requires --action-end')

    cutoff = datetime.fromisoformat(args.cutoff) if args.cutoff else None
    symbols = None
    if getattr(args, 'symbols', None):
        symbols = [item.strip().upper() for item in args.symbols.split(',') if item.strip()]
        if len(symbols) != len(set(symbols)) or 'SPY' not in symbols:
            raise ValueError(
                'Explicit L3 feature universe must contain unique symbols including SPY')

    raw_root = args.data_dir / 'raw'
    bundle = load_real_bundle(
        args.db, asof=args.asof, cutoff=cutoff, start=args.start,
        symbols=symbols, raw_root=raw_root,
    )
    bundle.require('observation')
    meta = bundle.metadata
    http = HttpCache(
        raw_root, offline=args.offline,
        refresh=getattr(args, 'refresh_source_responses', False),
    )

    if purpose == 'l3-forward':
        reference, pages = split_reference(
            http, TradingClock(), meta['symbols'], args.start, meta['asof_date_et'])
        source_evidence = _verify_reference_receipts(raw_root, pages)
        # Re-open after the vendor fetch so an implicit cutoff includes the
        # actual source observation. An explicit caller cutoff never moves.
        bundle = load_real_bundle(
            args.db, asof=meta['asof_date_et'], cutoff=cutoff, start=args.start,
            symbols=symbols, raw_root=raw_root,
        )
        knowledge_cutoff = pd.Timestamp(bundle.metadata['knowledge_cutoff_utc'])
        if any(pd.Timestamp(p['retrieved_at_utc']) > knowledge_cutoff for p in pages):
            raise PolicyError(
                'REFERENCE_AFTER_CUTOFF',
                'Vendor split-adjusted source was observed after the knowledge cutoff',
            )
        features = vendor_split_features(bundle, reference)
        output = args.output / str(uuid4())
        feature_source_snapshot_sha256 = hashlib.sha256(
            json.dumps(source_evidence, sort_keys=True, separators=(',', ':')).encode()
        ).hexdigest()
        manifest = {
            **features.metadata,
            'feature_source_snapshot_sha256': feature_source_snapshot_sha256,
            'run_id': output.name,
            'stage': 'G4_FORWARD',
            'purpose': 'l3-forward',
            'status': 'FORWARD_VENDOR_SPLIT_FEATURES_VERIFIED_CURRENT_VINTAGE',
            'knowledge_cutoff_utc': bundle.metadata['knowledge_cutoff_utc'],
            'reference_pages': pages,
            'vendor_source_provenance': source_evidence,
            'reference_comparison': {
                'status': 'NOT_APPLICABLE_DIRECT_VENDOR_SOURCE',
                'scope': 'L3_FORWARD_FEATURE_ADMISSION_ONLY',
            },
            'strict_normalization_audit_status': 'NOT_RUN',
            'generated_at_utc': datetime.now(timezone.utc).isoformat(),
            'prediction_rows': 0,
            'modelled_fills': 0,
            'sealed_strategy_test_used': False,
            'raw_source_provenance': bundle.metadata['source_provenance'],
            'research_only': True,
            'execution_ready': False,
            'real_orders_enabled': False,
        }
        _write_run(output, features, reference, manifest)
        print(json.dumps({
            'output': str(output.resolve()),
            'status': manifest['status'],
            'rows': features.metadata['rows'],
            'reference_pages': source_evidence['verified_pages'],
            'normalization_audit_status': 'NOT_RUN',
        }), flush=True)
        return 0

    # Strict G4 normalization audit.  This remains unchanged in policy:
    # local action-based normalization must match the separate vendor reference
    # under the predeclared precision tolerances or the audit stays BLOCKED.
    ActionProvider(http).events(meta['symbols'], args.action_start, args.action_end)
    reference, pages = split_reference(
        http, TradingClock(), meta['symbols'], args.start, meta['asof_date_et'])
    _verify_reference_receipts(raw_root, pages)
    issuer_fetch_errors = []
    if args.issuer_documents:
        for url in DOCUMENTS.values():
            try:
                http.get(url, headers=issuer_headers(url, http.offline))
            except (DataUnavailable, FileNotFoundError) as exc:
                issuer_fetch_errors.append({
                    'url': url,
                    'code': getattr(exc, 'code', 'OFFLINE_CACHE_MISSING'),
                })
    bundle = load_real_bundle(
        args.db, asof=meta['asof_date_et'], cutoff=cutoff, start=args.start,
        symbols=symbols, raw_root=raw_root,
    )
    if any(pd.Timestamp(p['retrieved_at_utc']) >
           pd.Timestamp(bundle.metadata['knowledge_cutoff_utc']) for p in pages):
        raise PolicyError(
            'REFERENCE_AFTER_CUTOFF',
            'Split reference was observed after the knowledge cutoff',
        )
    features = build_split_prices(
        bundle, HttpCache(raw_root, offline=True),
        args.action_start, args.action_end,
    )
    comparison = compare_reference(features, reference)
    precision = precision_diagnostics(bundle, features, reference, raw_root)
    issuer = (
        review_issuer_splits(
            features, HttpCache(raw_root, offline=True),
            bundle.metadata['knowledge_cutoff_utc'],
        )
        if args.issuer_documents else None
    )
    if issuer is not None:
        issuer['fetch_errors'] = issuer_fetch_errors
    output = args.output / str(uuid4())
    manifest = {
        **features.metadata,
        'run_id': output.name,
        'stage': 'G4',
        'purpose': 'normalization-audit',
        'status': (
            'NORMALIZATION_VERIFIED_CURRENT_VINTAGE'
            if comparison['status'] == 'PASS' else 'BLOCKED'
        ),
        'knowledge_cutoff_utc': bundle.metadata['knowledge_cutoff_utc'],
        'reference_pages': pages,
        'reference_comparison': comparison,
        'precision_diagnostic': precision,
        'issuer_review': issuer,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'prediction_rows': 0,
        'modelled_fills': 0,
        'sealed_strategy_test_used': False,
        'raw_source_provenance': bundle.metadata['source_provenance'],
        'research_only': True,
        'execution_ready': False,
        'real_orders_enabled': False,
    }
    _write_run(
        output, features, reference, manifest,
        comparison=comparison, precision=precision, issuer=issuer,
    )
    print(json.dumps({
        'output': str(output.resolve()),
        'status': manifest['status'],
        'rows': features.metadata['rows'],
        'splits': len(features.metadata['applied_splits']),
        'reference_status': comparison['status'],
    }), flush=True)
    return 0 if comparison['status'] == 'PASS' else 4
