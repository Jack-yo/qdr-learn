"""Bounded issuer-document checks and precision diagnostics, without capability overrides."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN
import hashlib
import html
from io import BytesIO
import json
import math
import os
import re
import unicodedata

import pandas as pd
from pypdf import PdfReader

from quant_research.policy import PolicyError
from .http import DataUnavailable
from .event_store import verify_event


DOCUMENTS = {
    'ISHARES_NOVEMBER': 'https://www.ishares.com/us/literature/sai/sai-ishares-trust-3-31.pdf',
    'ISHARES_APRIL': 'https://www.sec.gov/Archives/edgar/data/1100663/000119312526129300/d765912d497.htm',
    'SSGA_DECEMBER': 'https://www.ssga.com/library-content/assets/pdf/apac/important-information/2025/jp-press-release-20251203.pdf',
}


def issuer_headers(url, offline):
    agent = 'QuantResearch/2.1 public-document-audit'
    if url.startswith('https://www.sec.gov/') and not offline:
        agent = os.environ.get('SEC_USER_AGENT','')
        if not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+',agent):
            raise DataUnavailable('SEC original retrieval requires a compliant local User-Agent','MISSING_SEC_USER_AGENT')
    return {'User-Agent':agent}


def review_issuer_splits(features, http, cutoff):
    """Validate specific fields on one relevant page; never infer from search snippets."""
    for event in features.metadata['applied_splits']:
        verify_event(event, http.root)
    documents, texts = {}, {}
    for name, url in DOCUMENTS.items():
        try:
            raw = http.get(url, headers=issuer_headers(url,http.offline))
            if pd.Timestamp(raw.fetched_at) > pd.Timestamp(cutoff):
                raise DataUnavailable('Issuer document observed after cutoff', 'ISSUER_AFTER_CUTOFF')
            receipts = [json.loads(p.read_text(encoding='utf-8')) for p in (http.root/'receipts').glob('*.json')]
            if not any(r.get('url')==url and r.get('sha256')==raw.sha256 and r.get('fetched_at')==raw.fetched_at.isoformat()
                       and r.get('params')=={} for r in receipts):
                raise DataUnavailable('Issuer document lacks immutable receipt', 'ISSUER_RECEIPT_MISSING')
            if url.endswith('.htm'):
                text = html.unescape(re.sub('<[^>]*>', ' ', raw.body.decode('utf-8')))
                if 'Form 497' not in text or 'iShares' not in text:
                    raise DataUnavailable('Original filing content unverified','ISSUER_HTML_SCHEMA')
                texts[name] = [unicodedata.normalize('NFKC', text)]
                page_count,document_format = 1,'SEC_ORIGINAL_HTML'
            else:
                if not raw.body.startswith(b'%PDF-'):
                    raise DataUnavailable('Issuer response is not a PDF', 'ISSUER_NOT_PDF')
                reader = PdfReader(BytesIO(raw.body))
                # The scope is the front supplements, not general prospectus NLP.
                texts[name] = [unicodedata.normalize('NFKC', p.extract_text() or '') for p in reader.pages[:12]]
                page_count,document_format = len(reader.pages),'PDF'
            documents[name] = {'status': 'FETCHED_AND_HASH_VERIFIED', 'url': url, 'raw_sha256': raw.sha256,
                               'retrieved_at_utc': raw.fetched_at.isoformat(), 'request_key': raw.request_key,
                               'pages': page_count, 'pages_inspected': len(texts[name]),'format':document_format,
                               'text_pages_sha256': [hashlib.sha256(t.encode()).hexdigest() for t in texts[name]]}
        except (DataUnavailable, FileNotFoundError) as exc:
            documents[name] = {'status': 'BLOCKED', 'url': url, 'code': getattr(exc, 'code', 'OFFLINE_CACHE_MISSING')}
    checks = []
    for event in features.metadata['applied_splits']:
        symbol, payload = event['symbol'], event['payload']
        source = 'ISHARES_NOVEMBER' if symbol in ('MTUM','QUAL') else 'SSGA_DECEMBER' if symbol in ('XLB','XLE','XLK','XLU','XLY') else 'ISHARES_APRIL' if symbol=='IWF' else None
        matched = []
        for i, text in enumerate(texts.get(source, [])):
            compact = re.sub(r'\s+', '', text)
            if symbol in ('MTUM','QUAL'):
                ok = bool(re.search(r'\b'+symbol+r'\s+4:1\b', text)) and all(x in compact for x in
                    ('November3,2026','November4,2026','November5,2026','SupplementdatedOctober5,2026'))
                expected = ('2026-11-05',1,4,'2026-11-03','2026-11-04')
            elif source=='SSGA_DECEMBER':
                ok = bool(re.search(r'^'+symbol+r'[^\n]*\b2:1\b',text,re.M)) and all(x in compact for x in
                    ('2025年12月2日','2025年12月4日','2025年12月5日'))
                expected = ('2025-12-05',1,2,'2025-12-02','2025-12-04')
            elif symbol=='IWF':
                ok = bool(re.search(r'\bIWF\s+4:1\b', text)) and all(x in compact for x in
                    ('April27,2026','April28,2026','April29,2026','SupplementdatedMarch27,2026'))
                expected = ('2026-04-29',1,4,'2026-04-27','2026-04-28')
            else:
                continue
            fields = (payload.get('ex_date'), payload.get('old_rate'),payload.get('new_rate'),payload.get('record_date'),payload.get('payable_date'))
            if ok and fields==expected:
                matched.append(i+1)
        checks.append({'symbol': symbol, 'event_id': event['provider_event_id'], 'provider_sha256': event['raw_sha256'],
                       'status': 'CASE_FIELDS_MATCH' if len(matched)==1 else 'BLOCKED_ORIGINAL_FIELDS_NOT_VERIFIED',
                       'document': source, 'document_sha256': documents.get(source,{}).get('raw_sha256'),
                       'matched_pages': matched, 'checked_fields': ['ex_date','old_rate','new_rate','record_date','payable_date'],
                       'historical_publication_time_verified': False, 'execution_accepted': False})
    passed = sum(c['status']=='CASE_FIELDS_MATCH' for c in checks)
    return {'status': 'CASE_FIELDS_MATCH' if checks and passed==len(checks) else 'BLOCKED',
            'matched_splits': passed, 'requested_splits': len(checks), 'documents': documents, 'checks': checks,
            'scope': 'FIXED_CASE_FIELDS_ONLY_NOT_COMPLETE_ACTION_MASTER', 'historical_decision_eligible': False,
            'execution_accepted': False}


def precision_diagnostics(bundle, features, reference, raw_root):
    """Read exact JSON decimals. Quantizer hypotheses are diagnostics, not acceptance tolerances."""
    bundle.require('raw_prices')
    raw_frame, local = bundle.prices, features.prices
    if features.metadata['raw_snapshot_sha256'] != bundle.metadata['snapshot_sha256']:
        raise PolicyError('PRECISION_INPUT_MISMATCH', 'Features do not derive from the selected raw bundle')
    lookup = {}
    for digest in raw_frame.raw_sha256.unique():
        body = (raw_root/'objects'/digest).read_bytes()
        if hashlib.sha256(body).hexdigest()!=digest:
            raise PolicyError('RAW_RESPONSE_CORRUPT', 'Exact-decimal input hash mismatch')
        for symbol, bars in json.loads(body,parse_float=Decimal)['bars'].items():
            for bar in bars:
                lookup[digest,symbol,bar['t'][:10]] = bar
    target = reference.copy()
    target['date'] = pd.to_datetime(target.date).dt.date
    target = target.set_index(['symbol','date'],verify_integrity=True)
    modes = (ROUND_HALF_UP, ROUND_HALF_EVEN, ROUND_DOWN)
    checks = {}
    # Decimal ratios come from the actual event fields, not the float multiplier.
    splits = features.metadata['applied_splits']
    for event in splits:
        verify_event(event, raw_root)
    adjusted = local.loc[local.split_price_multiplier.ne(1)]
    for column, key in (('open','o'),('high','h'),('low','l'),('close','c')):
        counts = {mode:0 for mode in modes}
        floating_mismatches, exact_max_error, tie_count = 0, Decimal(0), 0
        for row in adjusted.itertuples():
            day = pd.Timestamp(row.date).date()
            value = Decimal(lookup[row.raw_sha256,row.symbol,str(day)][key])
            for event in splits:
                if event['symbol']==row.symbol and str(day)<event['payload']['ex_date']:
                    value *= Decimal(str(event['payload']['old_rate']))/Decimal(str(event['payload']['new_rate']))
            expected = Decimal(str(target.loc[(row.symbol,day),column]))
            exact_max_error = max(exact_max_error,abs(value-expected))
            tie_count += value*100 % 1 == Decimal('.5')
            for mode in modes:
                counts[mode] += value.quantize(Decimal('.01'),rounding=mode)!=expected
            floating_mismatches += math.floor(getattr(row,column)*100+0.5)/100 != float(expected)
        checks[column] = {'rows': len(adjusted), 'exact_max_absolute_error': str(exact_max_error),
                          'exact_half_cent_ties': int(tie_count), 'decimal_quantizer_mismatches': counts,
                          'binary64_floor_x100_plus_half_div100_mismatches': int(floating_mismatches)}
    return {'scope': 'EMPIRICAL_PRECISION_DIAGNOSTIC_NOT_VENDOR_SPECIFICATION', 'checks': checks,
            'vendor_rounding_guaranteed': False, 'changes_strict_tolerances': False,
            'enables_any_capability': False}
