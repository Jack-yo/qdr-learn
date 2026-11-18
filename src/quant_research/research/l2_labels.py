"""QDR L2 P4 verified forward style-label construction.

The builder accepts only an independently prepared action-consistent trade-price
basis. It deliberately cannot consume the exploratory Yahoo split-adjusted P1
history, so P4 cannot silently promote current-vintage observations into labels.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quant_research.research.l2_forecast import HORIZONS, VERIFIED_LABEL_KIND
from quant_research.research.l2_style_rotation import (
    REQUIRED_SYMBOLS, STYLE_REGISTRY,
)


LABEL_PROTOCOL_VERSION = "qdr-l2-style-label-v1"
REQUIRED_PRICE_BASIS = "VERIFIED_ACTION_CONSISTENT_TRADE_RETURN_BASIS"


def _validate_matrix(name: str, frame: pd.DataFrame, sessions: pd.DatetimeIndex) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError(name + " must be a DataFrame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError(name + " requires a DatetimeIndex")
    index = frame.index.tz_localize(None).normalize() if frame.index.tz is not None else frame.index.normalize()
    if not index.equals(sessions):
        raise ValueError(name + " must use the exact exchange-session index")
    if frame.columns.has_duplicates:
        raise ValueError(name + " contains duplicate symbols")
    missing = sorted(set(REQUIRED_SYMBOLS) - set(frame.columns))
    if missing:
        raise ValueError(name + " missing symbols: " + ",".join(missing))


def build_verified_style_labels_v1(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    availability: pd.DataFrame,
    action_verified: pd.DataFrame,
    exchange_sessions,
    trading_clock,
    *,
    price_basis: str,
    action_evidence_version: str,
) -> pd.DataFrame:
    """Construct exact T+1-open to T+H-close style-relative labels.

    price_basis is intentionally strict. The caller must provide prices already
    transformed to a corporate-action-consistent trade-return basis; merely
    declaring that a split/dividend exists is not enough.
    """
    if price_basis != REQUIRED_PRICE_BASIS:
        raise ValueError("L2 labels require independently verified action-consistent trade prices")
    if not isinstance(action_evidence_version, str) or not action_evidence_version.strip():
        raise ValueError("action_evidence_version is required")

    sessions = pd.DatetimeIndex(exchange_sessions)
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    sessions = sessions.normalize()
    if sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("exchange_sessions must be unique and increasing")

    for name, frame in (
        ("open_prices", open_prices),
        ("close_prices", close_prices),
        ("availability", availability),
        ("action_verified", action_verified),
    ):
        _validate_matrix(name, frame, sessions)
    if not (open_prices.columns.equals(close_prices.columns)
            and open_prices.columns.equals(availability.columns)
            and open_prices.columns.equals(action_verified.columns)):
        raise ValueError("L2 label evidence matrices must have identical columns")

    opens = open_prices.loc[:, REQUIRED_SYMBOLS].apply(pd.to_numeric, errors="coerce")
    closes = close_prices.loc[:, REQUIRED_SYMBOLS].apply(pd.to_numeric, errors="coerce")
    known = availability.loc[:, REQUIRED_SYMBOLS].apply(
        pd.to_datetime, utc=True, errors="coerce"
    )
    verified = action_verified.loc[:, REQUIRED_SYMBOLS].fillna(False).astype(bool)
    if ((opens.notna() & opens.le(0)) | (closes.notna() & closes.le(0))).any().any():
        raise ValueError("Verified trade prices must be positive")

    rows = []
    for position, signal_session in enumerate(sessions):
        for horizon in HORIZONS:
            if position + horizon >= len(sessions):
                continue
            window = trading_clock.window(signal_session, horizon)
            entry_session = sessions[position + 1]
            exit_session = sessions[position + horizon]
            holding_sessions = sessions[position + 1:position + horizon + 1]
            for style in STYLE_REGISTRY:
                required = (*style.numerator, *style.denominator)
                reason = None
                entry = opens.loc[entry_session, list(required)]
                exit_ = closes.loc[exit_session, list(required)]
                if entry.isna().any() or exit_.isna().any():
                    reason = "MISSING_ENTRY_OPEN_OR_EXIT_CLOSE"
                elif not verified.loc[holding_sessions, list(required)].all().all():
                    reason = "INCOMPLETE_CORPORATE_ACTION_EVIDENCE"
                elif known.loc[holding_sessions, list(required)].isna().any().any():
                    reason = "MISSING_LABEL_SOURCE_AVAILABILITY"

                label_available_at = None
                if reason is None:
                    label_available_at = known.loc[
                        holding_sessions, list(required)
                    ].max().max()
                    if pd.isna(label_available_at):
                        reason = "MISSING_LABEL_SOURCE_AVAILABILITY"
                    elif label_available_at < pd.Timestamp(window.exit_time):
                        reason = "LABEL_SOURCE_AVAILABLE_BEFORE_EXIT"

                value = None
                if reason is None:
                    if style.kind == "pair":
                        numerator_return = (
                            closes.loc[exit_session, style.numerator[0]]
                            / opens.loc[entry_session, style.numerator[0]] - 1.0
                        )
                        denominator_return = (
                            closes.loc[exit_session, style.denominator[0]]
                            / opens.loc[entry_session, style.denominator[0]] - 1.0
                        )
                    else:
                        numerator_return = (
                            closes.loc[exit_session, list(style.numerator)].to_numpy(dtype=float)
                            / opens.loc[entry_session, list(style.numerator)].to_numpy(dtype=float)
                            - 1.0
                        ).mean()
                        denominator_return = (
                            closes.loc[exit_session, list(style.denominator)].to_numpy(dtype=float)
                            / opens.loc[entry_session, list(style.denominator)].to_numpy(dtype=float)
                            - 1.0
                        ).mean()
                    value = float(
                        (1.0 + numerator_return) / (1.0 + denominator_return) - 1.0
                    )
                    if not np.isfinite(value):
                        value = None
                        reason = "NONFINITE_FORWARD_RELATIVE_RETURN"

                rows.append({
                    "date": signal_session.date().isoformat(),
                    "style_id": style.style_id,
                    "horizon": int(horizon),
                    "forward_relative_return": value,
                    "label_available_at": (
                        pd.Timestamp(label_available_at).isoformat()
                        if label_available_at is not None and pd.notna(label_available_at)
                        else None
                    ),
                    "label_kind": VERIFIED_LABEL_KIND if value is not None else "BLOCKED",
                    "signal_time": pd.Timestamp(window.signal_time).isoformat(),
                    "entry_time": pd.Timestamp(window.entry_time).isoformat(),
                    "exit_time": pd.Timestamp(window.exit_time).isoformat(),
                    "entry_session": entry_session.date().isoformat(),
                    "exit_session": exit_session.date().isoformat(),
                    "price_basis": REQUIRED_PRICE_BASIS,
                    "action_evidence_version": action_evidence_version,
                    "block_reason": reason,
                    "protocol_version": LABEL_PROTOCOL_VERSION,
                    "decision_eligible": False,
                    "real_orders_enabled": False,
                })
    return pd.DataFrame(rows).sort_values(
        ["date", "style_id", "horizon"], kind="stable"
    ).reset_index(drop=True)
