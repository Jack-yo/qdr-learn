"""Strict per-row audit of immutable, real-source historical forecast archives.

A SHA256-valid Parquet file can still contain look-ahead forecasts, wrong asset
IDs, impossible clock intervals or revised price anchors. These checks are an
additional gate; they do not establish PIT membership or model scientific merit.
"""
from __future__ import annotations

from datetime import date
import math

import pandas as pd

from quant_research.policy import PolicyError


_REQUIRED = {
    'date', 'security_id', 'symbol', 'sector', 'horizon', 'variant',
    'decision_eligible', 'signal_time', 'feature_available_at', 'fit_time',
    'entry_time', 'exit_time', 'adv20', 'atr20', 'reference_close',
    'predicted_return', 'expected_excess_return', 'downside_quantile',
    'reversal_5d', 'model_version',
}
_NUMERIC = ('adv20', 'atr20', 'reference_close', 'predicted_return',
            'expected_excess_return', 'downside_quantile', 'reversal_5d')
_TIMES = ('signal_time', 'feature_available_at', 'fit_time', 'entry_time', 'exit_time')


def validate_frozen_predictions(predictions, prices, clock, config):
    """Raise PolicyError on any inconsistent row; never silently discard one.

    Validates archival shape and the fixed T close → T+1 open → T+H close
    protocol against the actual exchange calendar. Caller MUST independently
    verify all source receipts, a verified PIT bundle, model bytes and manifest
    hashes. An accepted row is a modelled signal, not a broker order.
    """
    if not isinstance(predictions, pd.DataFrame) or predictions.empty or len(predictions) > 3_000_000:
        raise PolicyError('FROZEN_PREDICTIONS_EMPTY', 'Frozen real prediction file is empty or too large')
    if missing := sorted(_REQUIRED - set(predictions.columns)):
        raise PolicyError('FROZEN_PREDICTIONS_SCHEMA', 'Missing required modelled signal columns', missing)
    if not isinstance(prices, pd.DataFrame) or prices.empty:
        raise PolicyError('FROZEN_PRICE_EVIDENCE_MISSING', 'Verified historic prices required for row audit')
    if not {'date', 'security_id', 'symbol', 'close', 'adjustment_basis', 'source'} <= set(prices):
        raise PolicyError('FROZEN_PRICE_SCHEMA', 'Price source lacks necessary identity and close fields')
    if set(prices.source) != {'ALPACA'} or set(prices.adjustment_basis) != {'raw'}:
        raise PolicyError('FROZEN_RAW_PRICE_REQUIRED', 'Strict frozen signals require verified unadjusted SIP pricing')
    if any(col in predictions for col in ('actual_return', 'actual_excess_return', 'target', 'future_return')):
        raise PolicyError('FROZEN_LABELS_PRESENT', 'Frozen pre-decision signals cannot contain future outcome labels')
    if 'research_mode' in predictions and not predictions.research_mode.isin({'strict', 'historical_pit'}).all():
        raise PolicyError('FROZEN_RESEARCH_MODE_INVALID', 'Retrospective labels cannot become historical decisions')
    if predictions[['date','security_id','horizon','variant']].duplicated().any():
        raise PolicyError('FROZEN_SIGNAL_DUPLICATE', 'Each security/date/horizon/model variant must be unique')
    if not predictions.decision_eligible.map(lambda x: type(x) is bool or type(x).__name__ == 'bool').all() or not predictions.decision_eligible.all():
        raise PolicyError('FROZEN_SIGNAL_INELIGIBLE', 'All frozen rows require independently accepted decision eligibility')
    if predictions[['security_id','symbol','sector','variant','model_version']].isna().any().any() or any(
        predictions[col].astype(str).str.strip().eq('').any() for col in ('security_id','symbol','sector','variant','model_version')
    ):
        raise PolicyError('FROZEN_SIGNAL_IDENTITY_EMPTY', 'Frozen rows require explicit security, model, and sector identities')
    if predictions.sector.astype(str).str.upper().isin({'UNKNOWN','UNVERIFIED','N/A'}).any():
        raise PolicyError('FROZEN_SECTOR_UNVERIFIED', 'Sector risk cannot use an unknown historic sector assignment')
    if not predictions.variant.isin({'A','B','C','D'}).all():
        raise PolicyError('FROZEN_MODEL_VARIANT_INVALID', 'Unknown frozen Alpha model variant')
    if not predictions.horizon.isin({1,3,5}).all():
        raise PolicyError('FROZEN_HORIZON_INVALID', 'Only H1/H3/H5 are supported')
    if set(predictions.horizon.astype(int)) != set(config.horizons) or not (predictions.variant == 'D').any():
        raise PolicyError('FROZEN_COVERAGE_INCOMPLETE', 'Frozen model lacks a required horizon or D variant')
    converted = predictions.copy(deep=False)
    try:
        converted['date'] = pd.to_datetime(converted.date, errors='raise').dt.date
    except (TypeError, ValueError, OverflowError, AttributeError):
        raise PolicyError('FROZEN_SIGNAL_DATE_INVALID', 'Invalid forecast session dates') from None
    if converted.date.isna().any() or any(day >= date(2025,1,1) or day > config.validation_end or day < config.start for day in converted.date):
        raise PolicyError('FROZEN_TEST_SEAL_VIOLATION', 'Frozen forecast includes an out-of-range or sealed test session')
    for col in _TIMES:
        # utc=True alone would silently accept naive times. Reject them first.
        try:
            original = pd.to_datetime(converted[col], errors='raise')
            if original.isna().any() or any(pd.Timestamp(t).tzinfo is None for t in original):
                raise ValueError('timezone missing')
            converted[col] = pd.to_datetime(original, utc=True)
        except (TypeError, ValueError, OverflowError, AttributeError):
            raise PolicyError('FROZEN_TIME_INVALID', 'Frozen model timestamps must be valid and timezone-aware', [col]) from None
    if ((converted.feature_available_at > converted.signal_time)
            | (converted.fit_time > converted.signal_time)
            | (converted.signal_time >= converted.entry_time)
            | (converted.entry_time >= converted.exit_time)).any():
        raise PolicyError('FROZEN_FUTURE_INPUT', 'Fitted model or features were not available by the decision cutoff')
    for field in _NUMERIC:
        values = pd.to_numeric(converted[field], errors='coerce')
        if not values.map(lambda v: math.isfinite(float(v)) if pd.notna(v) else False).all():
            raise PolicyError('FROZEN_NUMERIC_INVALID', 'Frozen signal requires finite numeric inputs', [field])
        if field in ('adv20', 'atr20', 'reference_close') and not values.gt(0).all():
            raise PolicyError('FROZEN_LIQUIDITY_INVALID', 'Risk and price inputs must be positive', [field])
    if 'p_up' in converted:
        scores = pd.to_numeric(converted.p_up, errors='coerce')
        if not scores.map(lambda v: math.isfinite(float(v)) if pd.notna(v) else False).all() or not scores.between(0,1).all():
            raise PolicyError('FROZEN_PROBABILITY_INVALID', 'Probability scores must lie between 0 and 1')
    price_keys = prices[['date','security_id','symbol','close']].copy()
    price_keys.date = pd.to_datetime(price_keys.date).dt.date
    price_keys = price_keys.rename(columns={'close':'verified_raw_close'})
    if price_keys.duplicated(['date','security_id']).any():
        raise PolicyError('FROZEN_PRICE_AMBIGUOUS', 'Duplicate historic security/date prices')
    joined = converted.merge(price_keys,on=['date','security_id','symbol'],how='left',validate='many_to_one',suffixes=('','_verified'))
    if joined.verified_raw_close.isna().any():
        raise PolicyError('FROZEN_IDENTITY_PRICE_MISMATCH', 'Frozen securities must match actual source identity on decision date')
    if not (pd.to_numeric(joined.reference_close, errors='coerce') - pd.to_numeric(joined.verified_raw_close, errors='coerce')).abs().le(1e-8).all():
        raise PolicyError('FROZEN_PRICE_ANCHOR_CHANGED', 'Frozen signal price anchor differs from verified raw close')
    for (day, horizon), group in converted.groupby(['date','horizon'],sort=False):
        try:
            window = clock.window(str(day), int(horizon))
        except ValueError:
            raise PolicyError('FROZEN_TRADING_WINDOW_INVALID', 'Forecast references an invalid XNYS session or exit') from None
        if not (group.signal_time.eq(pd.Timestamp(window.signal_time)).all()
                and group.entry_time.eq(pd.Timestamp(window.entry_time)).all()
                and group.exit_time.eq(pd.Timestamp(window.exit_time)).all()):
            raise PolicyError('FROZEN_TRADING_CLOCK_MISMATCH', 'T signal, T+1 open or T+H close differs from frozen protocol')
    return {
        'status': 'ROW_INTEGRITY_VERIFIED_NOT_INDEPENDENT_MODEL_ATTESTATION',
        'rows': int(len(converted)),
        'sessions': int(converted.date.nunique()),
        'horizons': sorted(int(x) for x in converted.horizon.unique()),
        'data_must_pass_separate_PIT_and_model_admission': True,
        'real_orders_enabled': False,
    }
