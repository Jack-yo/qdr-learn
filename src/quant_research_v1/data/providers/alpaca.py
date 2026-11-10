"""Historical daily market-data API only; no account or trading endpoints."""
from datetime import date, datetime, timedelta, timezone
import json
import os
import re
from zoneinfo import ZoneInfo

from quant_research.clock import utc
from quant_research.data.http import DataUnavailable
from quant_research.data.schema import PriceRecord


class AlpacaProvider:
    def __init__(self, clock, http, feed="iex",page_limit=10000):
        if feed not in ("iex", "sip"):
            raise ValueError("Feed must be explicit iex or sip")
        self.clock, self.http, self.feed = clock, http, feed
        if not 1<=page_limit<=10000: raise ValueError('Invalid pagination limit')
        self.page_limit,self.last_page_count=page_limit,0

    def bars(self, symbols, start, end):
        if any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols):
            raise ValueError("Invalid symbol")
        start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        if start_date > end_date:
            raise ValueError("Start exceeds end")
        sessions = self.clock.calendar.sessions_in_range(start, end)
        if len(sessions) and self.clock.close(sessions[-1]) >= datetime.now(timezone.utc):
            raise ValueError("Requested range includes an unfinished session")
        # Alpaca end is inclusive; use local end-of-day with explicit UTC offset.
        zone = ZoneInfo("America/New_York")
        params = {"symbols": ",".join(sorted(set(symbols))), "timeframe": "1Day", "adjustment": "raw",
                  "feed": self.feed, "sort": "asc", "limit": self.page_limit,
                  "asof": "-",  # Disable automatic present-day symbol mapping.
                  "start": datetime.combine(start_date, datetime.min.time(), zone).isoformat(),
                  # Daily bars are timestamped at session start. A deterministic
                  # completed-session boundary avoids requesting future midnight
                  # (403 on delayed SIP) and remains reproducible offline.
                  "end": (self.clock.close(sessions[-1])+timedelta(minutes=1)).isoformat() if len(sessions) else datetime.combine(end_date,datetime.min.time(),zone).isoformat()}
        headers = {}
        if not self.http.offline:
            key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_SECRET_KEY")
            if not key or not secret:
                raise DataUnavailable("ALPACA_API_KEY / ALPACA_SECRET_KEY required for live ingestion")
            headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        records, tokens, keys = [], set(), set()
        self.last_page_count=0
        while True:
            raw = self.http.get("https://data.alpaca.markets/v2/stocks/bars", params, headers)
            self.last_page_count+=1
            payload = json.loads(raw.body)
            if not isinstance(payload.get("bars"), dict):
                raise DataUnavailable("Unexpected Alpaca bars schema")
            for symbol, bars in payload["bars"].items():
                if symbol not in symbols:
                    raise DataUnavailable("Unexpected symbol returned")
                for bar in bars:
                    stamp = datetime.fromisoformat(bar["t"].replace("Z", "+00:00"))
                    utc(stamp)
                    day = stamp.astimezone(zone).date()
                    if not start_date <= day <= end_date:
                        continue
                    event = self.clock.close(day)
                    if event > raw.fetched_at:
                        raise DataUnavailable("Unfinished daily bar returned")
                    key = (symbol, day)
                    if key in keys:
                        raise DataUnavailable("Duplicate bar across pages")
                    keys.add(key)
                    records.append(PriceRecord(
                        security_id=f"SYMBOL-UNVERIFIED:{symbol}", symbol=symbol, date=day,
                        open=bar["o"], high=bar["h"], low=bar["l"], close=bar["c"], volume=bar["v"],
                        vwap=bar.get("vw"), source="ALPACA", feed=self.feed,
                        event_time=event, available_at=raw.fetched_at, ingested_at=raw.fetched_at,
                        availability_basis="first_observed", raw_sha256=raw.sha256,
                        quality_flag="EXPLORATORY|SURVIVORSHIP_BIASED|IDENTITY_UNVERIFIED|DATA_INCOMPLETE",
                    ))
            token = payload.get("next_page_token")
            if not token:
                break
            if token in tokens:
                raise DataUnavailable("Repeated Alpaca pagination token")
            tokens.add(token)
            params = {**params, "page_token": token}
        return sorted(records, key=lambda b: (b.security_id, b.date))
