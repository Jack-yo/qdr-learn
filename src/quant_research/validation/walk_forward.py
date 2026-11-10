"""Calendar gap AND actual-label-time purge; no randomized date splitting."""
import pandas as pd


def training_mask(frame, sessions, test_start, fit_time, gap=5, window=1260, strict=True):
    sessions = pd.DatetimeIndex(sessions)
    test_start = pd.Timestamp(test_start)
    before = sessions[sessions<test_start]
    allowed = before[:-gap] if len(before)>gap else before[:0]
    allowed = allowed[-window:]
    mask = frame.date.isin(allowed) & (pd.to_datetime(frame.exit_time,utc=True)<fit_time)
    if strict:
        mask &= (pd.to_datetime(frame.feature_available_at,utc=True)<=fit_time)
        mask &= (pd.to_datetime(frame.label_available_at,utc=True)<=fit_time)
    return mask


def quarterly_folds(sessions, start, end):
    dates = pd.DatetimeIndex(sessions)
    dates = dates[(dates>=pd.Timestamp(start))&(dates<=pd.Timestamp(end))]
    for _, group in pd.Series(dates,index=dates).groupby(dates.to_period("Q")):
        yield pd.DatetimeIndex(group.to_numpy())
