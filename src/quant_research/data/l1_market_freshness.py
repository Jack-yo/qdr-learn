"""Conservative, provenance-aware freshness assessment for L1 market monitoring.

Freshness is about source observations, never trading or forecast eligibility.
Calendar-day tolerances deliberately include normal weekends/release lags;
a CURRENT label is not proof that the feed is exchange-real-time.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from math import isfinite


_MAX_AGE_DAYS = {
    "intraday": 1,
    "intraday/daily": 4,
    "daily": 4,
    "event": 4,
    "daily/weekly": 12,
    "weekly": 12,
    "biweekly": 21,
    "daily/weekly/monthly": 45,
    "monthly": 45,
    "per-session": None,  # Realized path labels are outcomes, not live signals.
}


def observed_day(value):
    """Parse an actual observation date; never invent one from a fetch time."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def numeric_or_class_value(value, *, unit=""):
    """Reject missing, NaN and infinite values without pandas dependency."""
    if value is None or isinstance(value, bool):
        return False
    if unit == "class":
        return bool(str(value).strip()) and str(value).strip().lower() not in {
            "none", "nan", "<na>", "nat",
        }
    try:
        return isfinite(float(value))
    except (ValueError, TypeError, OverflowError):
        return False


def available_by_session_end(value, session_day):
    """For a historical as-of request, exclude values not yet available then.

    Missing availability timestamps are *not* PIT-certified; legacy rows can
    remain visible but their eligibility remains false. Invalid/naive provided
    timestamps are rejected for historical queries.
    """
    if session_day is None or value is None:
        return True
    day = observed_day(session_day)
    if day is None:
        raise ValueError("INVALID_ASOF_SESSION")
    try:
        if isinstance(value, datetime):
            stamp = value
        else:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError, OverflowError):
        return False
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return False
    cutoff = datetime.combine(day, time.max, tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc) <= cutoff


def freshness(observation_date, cadence, reference_date=None):
    """Return explicit observation freshness without claiming real-time access."""
    policy_days = _MAX_AGE_DAYS.get(str(cadence))
    anchor = observed_day(reference_date)
    if anchor is None:
        return {"status": "NOT_EVALUATED", "age_days": None, "max_age_days": policy_days}
    day = observed_day(observation_date)
    if day is None:
        return {"status": "UNKNOWN_DATE", "age_days": None, "max_age_days": policy_days}
    age = (anchor - day).days
    if age < 0:
        status = "FUTURE_OBSERVATION"
    elif policy_days is None:
        status = "NOT_APPLICABLE"
    else:
        status = "STALE" if age > policy_days else "CURRENT"
    return {"status": status, "age_days": age, "max_age_days": policy_days}
