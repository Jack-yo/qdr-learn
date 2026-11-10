"""Single authoritative signal/entry/exit clock."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import exchange_calendars as xcals
import pandas as pd


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradeWindow:
    signal_time: datetime
    entry_time: datetime
    exit_time: datetime
    horizon: int


class TradingClock:
    def __init__(self, start="2016-01-01", end="2027-12-31", delay_minutes=15):
        if delay_minutes <= 0:
            raise ValueError("Signal must be strictly after close")
        self.calendar = xcals.get_calendar("XNYS", start=start, end=end)
        self.delay = timedelta(minutes=delay_minutes)

    def session(self, day):
        value = pd.Timestamp(day)
        if value.tzinfo is not None or value != value.normalize():
            raise ValueError("Session must be a timezone-free date")
        if not self.calendar.is_session(value):
            raise ValueError(f"Not an XNYS trading session: {day}")
        return value

    def close(self, day):
        return self.calendar.session_close(self.session(day)).to_pydatetime()

    def signal(self, day, now=None):
        signal = self.close(day) + self.delay
        if signal > utc(now or datetime.now(timezone.utc)):
            raise ValueError("Session has not closed or signal delay has not elapsed")
        return signal

    def window(self, day, horizon, now=None):
        if type(horizon) is not int or horizon not in (1, 3, 5):
            raise ValueError("Horizon must be 1, 3 or 5 trading sessions")
        session = self.session(day)
        position = self.calendar.sessions.get_loc(session)
        sessions = self.calendar.sessions
        if position + horizon >= len(sessions):
            raise ValueError("Exit outside configured calendar coverage")
        signal = self.signal(day, now)
        entry = self.calendar.session_open(sessions[position + 1]).to_pydatetime()
        if signal >= entry:
            raise ValueError("Signal delay reaches or exceeds next session open")
        return TradeWindow(
            signal,
            entry,
            self.calendar.session_close(sessions[position + horizon]).to_pydatetime(),
            horizon,
        )
