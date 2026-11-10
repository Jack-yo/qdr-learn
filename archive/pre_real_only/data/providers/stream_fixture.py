"""Version 2 fixture: per-symbol RNG streams preserve history when end extends."""
from datetime import timedelta
import hashlib
import json
from random import Random

from quant_research.contracts import DailyBar
from quant_research.data.normalize import normalize_fixture
from .fixture import SYMBOLS


def stream_fixture_records(clock,start,end,seed=42):
    sessions = clock.calendar.sessions_in_range(start,end)
    bars = []
    for index,symbol in enumerate(SYMBOLS):
        rng = Random(int(hashlib.sha256(f"stream-fixture-v2:{seed}:{symbol}".encode()).hexdigest(),16))
        price = 50.0+5*index
        for day in sessions:
            opening = round(price*(1+rng.uniform(-0.01,0.01)),4)
            price = round(opening*(1+rng.uniform(-0.02,0.02)),4)
            event = clock.close(day)
            bars.append(DailyBar(security_id="SYNTH-"+symbol,date=day.date(),open=opening,
                high=round(max(opening,price)*1.01,4),low=round(min(opening,price)*0.99,4),close=price,
                volume=rng.randint(100000,1000000),event_time=event,available_at=event+timedelta(minutes=5),ingested_at=event+timedelta(minutes=10)))
    return normalize_fixture(bars)
