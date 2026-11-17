"""Read-only official U.S. public market observations for L1.

Uses the existing bounded request cache; no historical warehouse or account APIs.
These are CURRENT observations with source dates, not PIT-certified model features.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import xml.etree.ElementTree as ET

from quant_research.data.l1_light_sources import SourceUnavailable


def _finite(value, low=None, high=None):
    try:
        number = float(value)
        if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
            raise ValueError("out of range")
        return number
    except (ValueError, TypeError, OverflowError) as exc:
        raise SourceUnavailable("INVALID_OFFICIAL_NUMBER") from exc


def _date(value):
    try:
        return datetime.fromisoformat(str(value)[:10]).date().isoformat()
    except (ValueError, TypeError) as exc:
        raise SourceUnavailable("INVALID_OFFICIAL_DATE") from exc


def parse_treasury_curve(xml_bytes):
    """Treasury monthly Atom/OData XML. Return daily published 2Y/10Y par yields."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise SourceUnavailable("TREASURY_INVALID_XML") from exc
    rows = {}
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        props = {}
        for node in entry.iter():
            name = node.tag.rsplit("}", 1)[-1].upper()
            if name in {"NEW_DATE", "BC_2YEAR", "BC_10YEAR"}:
                props[name] = (node.text or "").strip()
        if not props.get("NEW_DATE") or not props.get("BC_2YEAR") or not props.get("BC_10YEAR"):
            continue
        day = _date(props["NEW_DATE"])
        two = _finite(props["BC_2YEAR"], 0, 30)
        ten = _finite(props["BC_10YEAR"], 0, 30)
        if day in rows:
            raise SourceUnavailable("TREASURY_DUPLICATE_DATE")
        rows[day] = {"treasury_2y_pct": two, "treasury_10y_pct": ten,
                     "treasury_2s10s_bp": round((ten - two) * 100, 3)}
    if not rows:
        raise SourceUnavailable("TREASURY_NO_VALID_CURVE")
    return rows


def parse_nyfed_rates(body, rate_type):
    """New York Fed reference-rate JSON uses percentRate as percentage points."""
    try:
        records = json.loads(body)["refRates"]
        if not isinstance(records, list):
            raise ValueError("refRates must be a list")
        values = {}
        for item in records:
            if item.get("type", "").upper() != rate_type.upper():
                continue
            day = _date(item.get("effectiveDate"))
            if day in values:
                raise ValueError("duplicate rate date")
            values[day] = _finite(item.get("percentRate"), 0, 30)
    except (ValueError, TypeError, KeyError) as exc:
        raise SourceUnavailable("NYFED_INVALID_RESPONSE") from exc
    if not values:
        raise SourceUnavailable("NYFED_RATE_NOT_FOUND")
    return values


def parse_cftc_tff(body):
    """Futures-only E-mini S&P 500 leveraged-fund position / open interest.

    CFTC Tuesday report date is NOT its Friday publication timestamp.
    It is not dealer positioning, options gamma or an intraday signal.
    """
    try:
        rows = json.loads(body)
        if not isinstance(rows, list):
            raise ValueError("Expected list")
        values = {}
        for item in rows:
            if item.get("cftc_contract_market_code") != "13874A":
                continue
            name = str(item.get("market_and_exchange_names", "")).upper()
            if "E-MINI S&P 500" not in name or "MICRO" in name:
                continue
            day = _date(item.get("report_date_as_yyyy_mm_dd"))
            oi = _finite(item.get("open_interest_all"), 1)
            long = _finite(item.get("lev_money_positions_long"), 0)
            short = _finite(item.get("lev_money_positions_short"), 0)
            if day in values:
                raise ValueError("duplicate report date")
            values[day] = {"cftc_emini_sp500_lev_net_pct_oi": round((long - short) / oi * 100, 5),
                           "cftc_emini_sp500_lev_long": long,
                           "cftc_emini_sp500_lev_short": short}
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceUnavailable("CFTC_INVALID_RESPONSE") from exc
    if not values:
        raise SourceUnavailable("CFTC_TARGET_CONTRACT_MISSING")
    return values


class OfficialL1Sources:
    """Uses the same LiveSources.request allowlist and 32-MB bounded cache."""

    TREASURY = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    NYFED_SOFR = "https://markets.newyorkfed.org/api/rates/secured/sofr/last/10.json"
    NYFED_EFFR = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/10.json"
    CFTC = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

    def __init__(self, live):
        self.live = live

    @staticmethod
    def _receipt(source, fetched, digest, status):
        return {"source": source, "fetched_at": fetched, "sha256": digest,
                "pit": status}

    def treasury(self, asof, *, refresh=False):
        month = _date(asof)[:7].replace("-", "")
        params = {"data": "daily_treasury_yield_curve", "field_tdr_date_value_month": month}
        body, fetched, digest = self.live.request(self.TREASURY, params, ttl=21600, refresh=refresh)
        rows = parse_treasury_curve(body)
        return rows, self._receipt("US_TREASURY", fetched, digest, "CURRENT_MONTH_OFFICIAL_NOT_HISTORICAL_PIT")

    def nyfed(self, kind, *, refresh=False):
        if kind not in ("SOFR", "EFFR"):
            raise SourceUnavailable("NYFED_RATE_NOT_ALLOWED")
        url = self.NYFED_SOFR if kind == "SOFR" else self.NYFED_EFFR
        body, fetched, digest = self.live.request(url, ttl=3600, refresh=refresh)
        return parse_nyfed_rates(body, kind), self._receipt(
            "NYFED_" + kind, fetched, digest, "OFFICIAL_EFFECTIVE_DATE_NOT_HISTORICAL_PIT")

    def cftc_sp500(self, *, refresh=False):
        params = {
            "cftc_contract_market_code": "13874A",
            "$select": "cftc_contract_market_code,market_and_exchange_names,"
                       "report_date_as_yyyy_mm_dd,open_interest_all,"
                       "lev_money_positions_long,lev_money_positions_short",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "14",
        }
        body, fetched, digest = self.live.request(self.CFTC, params, ttl=14400, refresh=refresh)
        return parse_cftc_tff(body), self._receipt(
            "CFTC_TFF_FUTURES_ONLY", fetched, digest, "TUESDAY_POSITION_PUBLISHED_FRIDAY_NOT_PIT")


def scan_official_l1(root, *, sources=None, now=None, refresh=False, asof=None):
    """Independent public-data scan for progressive L1 UI loading.

    Market scores and PIT training are intentionally unaffected. Missing feeds
    are represented by source-health status, never zero or synthetic values.
    """
    from concurrent.futures import ThreadPoolExecutor
    from quant_research.clock import TradingClock
    from quant_research.data.l1_light_sources import LiveSources

    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("Timestamp must be timezone-aware")
    stamp = stamp.astimezone(timezone.utc)
    clock = TradingClock()
    if asof:
        asof = _date(asof)
        if asof > stamp.date().isoformat():
            raise ValueError("Future asof not allowed")
        latest = clock.session(asof)
    else:
        # Trading calendar is America/New_York; UTC calendar date only bounds
        # the previous session lookup, final close+delay is authoritative.
        latest = clock.calendar.date_to_session(stamp.date(), direction="previous")
    while clock.close(latest) + clock.delay > stamp:
        latest = clock.calendar.previous_session(latest)
    limit = latest.date().isoformat()
    official = OfficialL1Sources(sources or LiveSources(root))
    jobs = {
        "treasury": lambda: official.treasury(limit, refresh=refresh),
        "nyfed_sofr": lambda: official.nyfed("SOFR", refresh=refresh),
        "nyfed_effr": lambda: official.nyfed("EFFR", refresh=refresh),
        "cftc_sp500": lambda: official.cftc_sp500(refresh=refresh),
    }
    acquired, health, features = {}, {}, []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {key: pool.submit(fn) for key, fn in jobs.items()}
        for key, future in tasks.items():
            try:
                values, receipt = future.result()
                eligible = [(day, value) for day, value in values.items() if day <= limit]
                if key == "cftc_sp500":
                    # Tuesday's position is normally published Friday. Use a
                    # conservative 22:00 UTC on that Friday for current observation.
                    eligible = [(day, val) for day, val in eligible
                                if stamp >= datetime.fromisoformat(day).replace(
                                    tzinfo=timezone.utc) + timedelta(days=3, hours=22)]
                if not eligible:
                    raise SourceUnavailable("NO_ELIGIBLE_OBSERVATION")
                day, value = max(eligible)
                lag = (datetime.fromisoformat(limit)-datetime.fromisoformat(day)).days
                if lag > (21 if key == "cftc_sp500" else 7):
                    raise SourceUnavailable("STALE_OBSERVATION")
                acquired[key] = (day, value, receipt)
                health[key] = {"status": "OBSERVED", "source": receipt["source"],
                               "effective_date": day, "fetched_at": receipt["fetched_at"],
                               "receipt_sha256": receipt["sha256"], "pit": receipt["pit"]}
            except (SourceUnavailable, ValueError, KeyError, TypeError, AttributeError) as exc:
                health[key] = {"status": "MISSING",
                               "code": getattr(exc, "code", type(exc).__name__)}
    def add(key, domain, fid, label, val, unit, *, observed_day=None):
        day, _, receipt = acquired[key]
        numeric = _finite(val)
        features.append({"domain": domain, "id": fid, "label": label,
                         "value": round(numeric, 5), "unit": unit,
                         "status": "OBSERVED", "source": receipt["source"],
                         "observed_date": observed_day or day,
                         "fetched_at": receipt["fetched_at"],
                         "pit": receipt["pit"], "receipt_sha256": receipt["sha256"]})
    if "treasury" in acquired:
        day, values, _ = acquired["treasury"]
        for fid, label, unit in (
            ("treasury_2y_pct", "美国国债 2 年收益率", "%"),
            ("treasury_10y_pct", "美国国债 10 年收益率", "%"),
            ("treasury_2s10s_bp", "美国国债 10Y−2Y 期限利差", "bps"),
        ):
            add("treasury", "cross_asset", fid, label, values[fid], unit)
    for kind, key, label in (("SOFR", "nyfed_sofr", "SOFR"),
                              ("EFFR", "nyfed_effr", "EFFR")):
        if key in acquired:
            add(key, "funding", key, "纽约联储 " + label,
                acquired[key][1], "%")
    if "nyfed_sofr" in acquired and "nyfed_effr" in acquired:
        day, sofr, _ = acquired["nyfed_sofr"]
        effr_day, effr, _ = acquired["nyfed_effr"]
        if day == effr_day:
            add("nyfed_sofr", "funding", "nyfed_sofr_minus_effr_bp",
                "SOFR−EFFR 融资利差", (sofr-effr)*100, "bps")
    if "cftc_sp500" in acquired:
        day, positions, _ = acquired["cftc_sp500"]
        add("cftc_sp500", "positioning", "cftc_emini_sp500_lev_net_pct_oi",
            "E-mini S&P 500 杠杆基金净仓/未平仓量",
            positions["cftc_emini_sp500_lev_net_pct_oi"], "%")
    return {"schema": "qdr.l1.official.v1", "asof_session": limit,
            "status": "OBSERVATION_ONLY" if features else "NO_AVAILABLE_PUBLIC_FEED",
            "historical_pit_verified": False, "features": features,
            "source_health": health, "fetched_at": stamp.isoformat(),
            "not_in_model_scores": True}
