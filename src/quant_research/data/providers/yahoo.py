"""Yahoo via yfinance, preserving vendor chart bytes and explicit non-raw prices."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from quant_research.data.http import DataUnavailable, RawResponse, atomic_write
from quant_research.data.schema import CorporateAction, PriceRecord

FLAGS = "EXPLORATORY|SURVIVORSHIP_BIASED|DATA_INCOMPLETE|IDENTITY_UNVERIFIED|NOT_RAW_EXECUTION_PRICE|FIRST_OBSERVED_NOT_PIT"


class YFinanceDownloader:
    """Record only successful chart bodies, never cookies, crumb or auth headers."""
    def __init__(self, cache_root):
        self.cache_root = Path(cache_root)
        self.session = None
        self.captured = []

    def __call__(self, symbol, start, end):
        import yfinance as yf
        from curl_cffi import requests

        yf.set_tz_cache_location(str(self.cache_root / "yfinance-internal"))
        owner = self
        if self.session is None:
            class RecordingSession(requests.Session):
                def get(self, *args, **kwargs):
                    response = super().get(*args, **kwargs)
                    if response.status_code == 200 and urlsplit(response.url).path.startswith("/v8/finance/chart/"):
                        owner.captured.append(response.content)
                    return response
            self.session = RecordingSession(impersonate="chrome")
        self.captured.clear()
        try:
            # Explicit flags protect against library default changes. We normalize
            # captured Yahoo bytes, not yfinance's postprocessed DataFrame.
            yf.Ticker(symbol, session=self.session).history(
                start=start, end=str(date.fromisoformat(end) + timedelta(days=1)), interval="1d",
                auto_adjust=False, back_adjust=False, actions=True, repair=False,
                keepna=True, rounding=False, raise_errors=True, timeout=30,
            )
        except Exception as exc:
            raise DataUnavailable(f"Yahoo {symbol} download failed ({type(exc).__name__}); no data fabricated") from None
        if not self.captured:
            raise DataUnavailable(f"Yahoo {symbol} returned no captured chart response")
        return self.captured[-1]


class YahooProvider:
    def __init__(self, clock, root, offline=False, refresh=False, downloader=None, sleep=time.sleep):
        self.clock, self.root = clock, Path(root)
        self.offline, self.refresh, self.sleep = offline, refresh, sleep
        self.downloader = downloader or YFinanceDownloader(self.root)
        self.last_actions = []

    def _raw(self, symbol, start, end):
        request = {"provider": "yfinance", "symbol": symbol, "start": start, "end_inclusive": end,
                   "interval": "1d", "auto_adjust": False, "back_adjust": False,
                   "repair": False, "actions": True, "normalization_version": "yahoo-v1"}
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        pointer = self.root / "yahoo" / "requests" / (key + ".json")
        if pointer.exists() and (self.offline or not self.refresh):
            metadata = json.loads(pointer.read_text(encoding="utf-8"))
            digest = metadata["sha256"]
            if metadata.get("request") != request or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise DataUnavailable("Yahoo cache identity mismatch")
            body = (self.root / "objects" / digest).read_bytes()
            if hashlib.sha256(body).hexdigest() != digest:
                raise DataUnavailable("Yahoo cache hash mismatch")
            return RawResponse(body, datetime.fromisoformat(metadata["fetched_at"]), digest, key)
        if self.offline:
            raise DataUnavailable(f"Yahoo offline cache miss for {symbol}")
        body = None
        for attempt in range(3):
            self.sleep(1 if attempt == 0 else 2 ** (attempt + 1))
            try:
                body = self.downloader(symbol, start, end)
                break
            except DataUnavailable:
                if attempt == 2:
                    raise
        fetched = datetime.now(timezone.utc)
        digest = hashlib.sha256(body).hexdigest()
        object_path = self.root / "objects" / digest
        if object_path.exists():
            if hashlib.sha256(object_path.read_bytes()).hexdigest() != digest:
                raise DataUnavailable("Yahoo raw object corrupted")
        else:
            atomic_write(object_path, body)
        import importlib.metadata
        metadata = {"request": request, "sha256": digest, "fetched_at": fetched.isoformat(),
                    "request_key": key, "yfinance_version": importlib.metadata.version("yfinance")}
        encoded = json.dumps(metadata).encode()
        atomic_write(self.root / "yahoo" / "receipts" / (uuid4().hex + ".json"), encoded)
        atomic_write(pointer, encoded)
        return RawResponse(body, fetched, digest, key)

    def bars(self, symbols, start, end):
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        if first > last or not symbols or any(not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", s) for s in symbols):
            raise ValueError("Invalid Yahoo dates or symbols")
        sessions = self.clock.calendar.sessions_in_range(start, end)
        if len(sessions) and self.clock.close(sessions[-1]) >= datetime.now(timezone.utc):
            raise ValueError("Requested range includes an unfinished session")
        result, self.last_actions = [], []
        for symbol in symbols:
            raw = self._raw(symbol, start, end)
            bars, actions = parse_chart(raw, symbol, first, last, self.clock)
            result.extend(bars)
            self.last_actions.extend(actions)
        return sorted(result, key=lambda r: (r.security_id, r.date))


def parse_chart(raw, symbol, first, last, clock):
    payload = json.loads(raw.body)
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result") or len(chart["result"]) != 1:
        raise DataUnavailable(f"Yahoo {symbol} chart error/empty result")
    data = chart["result"][0]
    meta = data.get("meta", {})
    if meta.get("symbol") != symbol or meta.get("currency") != "USD" or meta.get("exchangeTimezoneName") != "America/New_York":
        raise DataUnavailable("Yahoo symbol/currency/exchange timezone mismatch")
    if meta.get("dataGranularity") != "1d":
        raise DataUnavailable("Yahoo response is not daily granularity")
    stamps = data.get("timestamp", [])
    quote = data.get("indicators", {}).get("quote", [])
    adjusted = data.get("indicators", {}).get("adjclose", [])
    if len(quote) != 1 or len(adjusted) != 1:
        raise DataUnavailable("Yahoo quote/adjusted-close schema missing")
    quote, adjusted = quote[0], adjusted[0].get("adjclose", [])
    if any(len(quote.get(k, [])) != len(stamps) for k in ("open", "high", "low", "close", "volume")) or len(adjusted) != len(stamps):
        raise DataUnavailable("Yahoo chart arrays have unequal lengths")
    bars, actions, seen, previous = [], [], set(), None
    zone = ZoneInfo("America/New_York")
    for i, stamp in enumerate(stamps):
        day = datetime.fromtimestamp(stamp, timezone.utc).astimezone(zone).date()
        if previous is not None and stamp <= previous:
            raise DataUnavailable("Yahoo timestamps not strictly increasing")
        previous = stamp
        if not first <= day <= last:
            continue
        if day in seen:
            raise DataUnavailable("Duplicate Yahoo daily key")
        seen.add(day)
        event = clock.close(day)
        if event > raw.fetched_at:
            raise DataUnavailable("Yahoo unfinished daily bar")
        if any(quote[name][i] is None for name in ("open","high","low","close","volume")):
            raise DataUnavailable(f"SOURCE_INCOMPLETE_OHLCV:{symbol}:{day}; no replacement values generated")
        bars.append(PriceRecord(
            security_id=f"YAHOO-SYMBOL-UNVERIFIED:{symbol}", symbol=symbol, date=day,
            open=quote["open"][i], high=quote["high"][i], low=quote["low"][i], close=quote["close"][i],
            volume=quote["volume"][i], adj_close=adjusted[i], adjustment_basis="yahoo_split_adjusted",
            source="YAHOO", feed="yahoo", event_time=event, available_at=raw.fetched_at,
            ingested_at=raw.fetched_at, availability_basis="first_observed", raw_sha256=raw.sha256, quality_flag=FLAGS,
        ))
    for kind, events in data.get("events", {}).items():
        if kind not in ("dividends", "splits", "capitalGains"):
            raise DataUnavailable("Unknown Yahoo corporate action kind")
        for identifier, event in events.items():
            day = datetime.fromtimestamp(event["date"], timezone.utc).astimezone(zone).date()
            if not first <= day <= last:
                continue
            clock.session(day)
            if kind == "splits":
                value = float(event["numerator"]) / float(event["denominator"])
            else:
                value = event["amount"]
            actions.append(CorporateAction(security_id=f"YAHOO-SYMBOL-UNVERIFIED:{symbol}",
                event_id=f"{kind}:{identifier}", ex_date=day,
                action_type={"dividends":"dividend", "splits":"split", "capitalGains":"capital_gain"}[kind],
                factor_or_cash=value, available_at=raw.fetched_at, version=raw.sha256, currency=meta["currency"]))
    if not bars:
        raise DataUnavailable(f"Yahoo {symbol} returned no usable requested daily rows")
    return bars, actions
