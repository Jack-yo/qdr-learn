"""Public market-source expansion for L1: observable data, not tradable forecasts.

Supported sources: Cboe exchange-wide options JSON, OFR stress CSV, BLS ICS
calendar, CFTC Nasdaq/gold weekly positioning, Cboe equity volume CSV, and
a transparently limited fixed equity sample sourced from Alpaca on demand.

All data are read-only, bounded, and marked as unverified historical PIT.
"""
from __future__ import annotations

import csv
import io
import json
import math
from hashlib import sha256
import re
from collections import defaultdict
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from quant_research.data.l1_light_sources import LiveSources, SourceUnavailable
from quant_research.data.l1_official_sources import _date, _finite


CBOE_PREFIX = "https://cdn.cboe.com/data/us/options/market_statistics/daily/"
OFR_FSI = "https://www.financialresearch.gov/financial-stress-index/data/fsi.csv"
BLS_CALENDAR = "https://www.bls.gov/schedule/news_release/bls.ics"
CFTC_TFF = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_DISAGG = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CBOE_VOLUME_PREFIX = "https://cdn.cboe.com/resources/us/equities/market-statistics/historical-market-volume/"
ICI_ETF = "https://www.ici.org/research/stats/etf_flows"
FINRA_PREFIX = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol"
NY = ZoneInfo("America/New_York")

# Fixed transparent sample, NOT S&P 500 constituents, NOT all US-listed stocks.
# Deliberately kept small so the provider can serve it on demand.
EQUITY_SAMPLE = (
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO",
    "JPM","V","MA","XOM","UNH","HD","PG","COST","ABBV","BAC",
    "KO","PEP","CSCO","CRM","ORCL","WMT","NFLX","AMD","CVX",
    "MRK","ABT","IBM"
)
SAMPLE_ID = "FIXED_US_LARGE_CAP_30_V1"


def parse_cboe_options(body):
    """Use official ratios JSON and verify that underlying volume legs agree."""
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get("ratios"), list):
            raise ValueError("Invalid Cboe ratios payload")
        ratios = {str(x["name"]).strip().upper(): _finite(x["value"], 0, 100)
                  for x in payload["ratios"] if isinstance(x, dict)
                  and x.get("name") and x.get("value") not in (None, "")}
        families = {
            "total": ("TOTAL PUT/CALL RATIO", "SUM OF ALL PRODUCTS"),
            "index": ("INDEX PUT/CALL RATIO", "INDEX OPTIONS"),
            "equity": ("EQUITY PUT/CALL RATIO", "EQUITY OPTIONS"),
            "etp": ("EXCHANGE TRADED PRODUCTS PUT/CALL RATIO", "EXCHANGE TRADED PRODUCTS"),
        }
        values = {}
        for short, (ratio_name, leg_name) in families.items():
            if ratio_name not in ratios:
                continue
            rows = payload.get(leg_name, [])
            volume = next((x for x in rows if isinstance(x, dict)
                           and str(x.get("name","")).upper()=="VOLUME"), None)
            if not volume:
                continue
            call = _finite(volume.get("call"), 0)
            put = _finite(volume.get("put"), 0)
            total = _finite(volume.get("total"), 0)
            if total == 0 or call == 0:
                continue  # 0/0 is not zero sentiment.
            if abs((put + call) - total) > 0.001:
                raise SourceUnavailable("CBOE_VOLUME_LEGS_MISMATCH")
            calculated = put/call
            if abs(calculated-ratios[ratio_name]) > 0.015:
                raise SourceUnavailable("CBOE_RATIO_LEGS_MISMATCH")
            values["cboe_pcr_"+short] = round(calculated, 5)
            values["cboe_put_volume_"+short] = int(put)
        # Open interest measures aggregate contract counts, not dealer gamma.
        spx_key = next((key for key in payload if key.startswith("SPX + SPXW")), None)
        if spx_key is not None:
            oi_rows = payload.get(spx_key, [])
            oi = next((x for x in oi_rows if isinstance(x, dict)
                       and str(x.get("name","")).upper()=="OPEN INTEREST"), None)
            if oi:
                call,put = _finite(oi.get("call"),0),_finite(oi.get("put"),0)
                if call > 0:
                    values["cboe_spx_put_call_oi"] = round(put/call,5)
                    values["cboe_spx_total_oi"] = int(_finite(oi.get("total"),0))
                    if abs((call+put)-values["cboe_spx_total_oi"])>0.001:
                        raise SourceUnavailable("CBOE_OI_LEGS_MISMATCH")
        if not any(key.startswith("cboe_pcr_") for key in values):
            raise SourceUnavailable("CBOE_NO_USABLE_RATIOS")
        return values
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise SourceUnavailable("CBOE_INVALID_OPTIONS_JSON") from exc


def parse_ofr_stress_csv(body):
    """Accept only identifiable dated, numeric official OFR FSI columns."""
    try:
        reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
        rows = list(reader)
        normalize=lambda s:re.sub("[^a-z0-9]","",str(s).lower())
        header_idx = next((i for i,row in enumerate(rows[:15])
                           if any(normalize(x)=="date" for x in row) and
                           any(normalize(x) in {"ofrfsi","fsi","ofrfinancialstressindex"}
                               for x in row)), None)
        if header_idx is None:
            raise SourceUnavailable("OFR_UNRECOGNIZED_SCHEMA")
        header = [normalize(x) for x in rows[header_idx]]
        day_idx = header.index("date")
        val_idx = next(i for i,x in enumerate(header)
                       if x in {"ofrfsi","fsi","ofrfinancialstressindex"})
        observed={}
        for row in rows[header_idx+1:]:
            if len(row)<=max(day_idx,val_idx):
                continue
            try:
                day=_date(row[day_idx])
                value=_finite(row[val_idx],-30,30)
            except SourceUnavailable:
                continue
            if day in observed:
                raise SourceUnavailable("OFR_DUPLICATE_DATE")
            observed[day]={"ofr_fsi":value}
        if not observed:
            raise SourceUnavailable("OFR_EMPTY_SERIES")
        return observed
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise SourceUnavailable("OFR_INVALID_CSV") from exc


def parse_bls_calendar(body):
    """Unfold RFC5545 lines and resolve official publication timestamps to UTC."""
    try:
        text=body.decode("utf-8-sig").replace("\r\n","\n")
        lines=[]
        for raw in text.split("\n"):
            if raw.startswith((" ","\t")) and lines:
                lines[-1]+=raw[1:]
            else:
                lines.append(raw.strip())
        if not any(x=="BEGIN:VCALENDAR" for x in lines):
            raise SourceUnavailable("BLS_INVALID_CALENDAR")
        events=[]
        event=None
        for line in lines:
            if line=="BEGIN:VEVENT":
                event={}
                continue
            if line=="END:VEVENT":
                if event and "dt" in event and "name" in event:
                    events.append(event)
                event=None
                continue
            if event is None or ":" not in line:
                continue
            field,value=line.split(":",1)
            field=field.upper()
            if field.startswith("DTSTART"):
                dateval=value[:8]
                if not re.fullmatch(r"\d{8}",dateval):
                    continue
                if len(value)<15: # all-day events are not precise releases
                    continue
                wall=datetime.strptime(value[:15],"%Y%m%dT%H%M%S")
                if value.endswith("Z"):
                    dt=wall.replace(tzinfo=timezone.utc)
                elif "TZID=AMERICA/NEW_YORK" in field:
                    dt=wall.replace(tzinfo=NY).astimezone(timezone.utc)
                else:
                    continue  # no assumed timezone
                event["dt"]=dt
            elif field.startswith("SUMMARY"):
                event["name"]=value.replace("\\, ",", ").replace("\\, ",", ")
        if not events:
            raise SourceUnavailable("BLS_NO_DATED_RELEASES")
        unique={}
        for e in events:
            key=(e["dt"],e["name"])
            unique[key]=e
        return sorted(unique.values(),key=lambda e:e["dt"])
    except (UnicodeDecodeError, ValueError, OverflowError) as exc:
        raise SourceUnavailable("BLS_INVALID_ICS") from exc


def parse_cftc_contract(body, code, *, trader="leveraged"):
    """CFTC TFF or Disaggregated futures-only, strictly one contract per report."""
    try:
        records=json.loads(body)
        if not isinstance(records,list):
            raise ValueError("list required")
        fields=("lev_money_positions_long","lev_money_positions_short") if trader=="leveraged" else (
            "m_money_positions_long_all","m_money_positions_short_all")
        data={}
        for row in records:
            if row.get("cftc_contract_market_code")!=code:
                continue
            day=_date(row.get("report_date_as_yyyy_mm_dd"))
            oi=_finite(row.get("open_interest_all"),1)
            long=_finite(row.get(fields[0]),0)
            short=_finite(row.get(fields[1]),0)
            if day in data:
                raise SourceUnavailable("CFTC_DUPLICATE_CONTRACT_DATE")
            data[day]={"net_pct_oi":round((long-short)/oi*100,5),
                       "net_contracts":int(long-short)}
        if not data:
            raise SourceUnavailable("CFTC_CONTRACT_NOT_FOUND")
        return data
    except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        raise SourceUnavailable("CFTC_INVALID_CONTRACT_RESPONSE") from exc


def parse_cboe_equities_volume(body):
    """Daily cross-venue tape aggregates. TRF share is NOT directional flow."""
    try:
        rows=csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        grouped=defaultdict(lambda:{"total":0.0,"trf":0.0,"venue_count":0})
        for row in rows:
            day=_date(row.get("Day"))
            venue=str(row.get("Market Participant","")).upper()
            if not venue:
                continue
            notional=_finite(row.get("Total Notional"),0)
            slot=grouped[day]
            slot["total"]+=notional
            slot["venue_count"]+=1
            if "TRF" in venue:
                slot["trf"]+=notional
        out={}
        for day,values in grouped.items():
            if values["total"]>0 and values["venue_count"]>=8:
                out[day]={"cboe_trf_notional_share":100*values["trf"]/values["total"],
                          "cboe_reported_notional_usd":values["total"]}
        if not out:
            raise SourceUnavailable("CBOE_EQUITY_VOLUME_NO_VALID_DAY")
        return out
    except (UnicodeDecodeError,ValueError,TypeError,csv.Error) as exc:
        raise SourceUnavailable("CBOE_EQUITY_VOLUME_INVALID") from exc


class _HTMLToText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments=[]
    def handle_data(self, text):
        self.fragments.append(text)


def parse_ici_weekly_etf_issuance(body):
    """Extract only the explicit current ICI reported release, no HTML table guess."""
    try:
        parser=_HTMLToText()
        parser.feed(body.decode("utf-8"))
        text=" ".join(" ".join(parser.fragments).split())
        intro=re.search(r"(?:Washington,\s*DC;\s*)([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
                        text)
        if intro is None:
            raise SourceUnavailable("ICI_PUBLISH_DATE_MISSING")
        published=datetime.strptime(intro.group(1),"%B %d, %Y").date().isoformat()
        sentence=re.search(
            r"shares (issued exceeded that of shares redeemed|redeemed exceeded that of shares issued)"
            r" by \$([0-9,.]+) billion for the week ended ([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
            text, re.IGNORECASE)
        if sentence is None:
            raise SourceUnavailable("ICI_WEEKLY_ESTIMATE_NOT_FOUND")
        end=datetime.strptime(sentence.group(3),"%B %d, %Y").date().isoformat()
        if published < end:
            raise SourceUnavailable("ICI_PUBLICATION_PRECEDES_WINDOW")
        signed=_finite(sentence.group(2).replace(",",""),0,2000)
        if sentence.group(1).lower().startswith("redeemed"):
            signed=-signed
        return {end:{"ici_weekly_etf_net_issuance_bn_usd":round(signed,3),
                     "source_published_date":published}}
    except (UnicodeDecodeError,ValueError,TypeError,OverflowError) as exc:
        raise SourceUnavailable("ICI_INVALID_RELEASE_HTML") from exc


def parse_finra_consolidated_short_volume(body):
    """FINRA TRF/ADF reported daily short-sale flow, NOT open short interest."""
    try:
        reader=csv.DictReader(io.StringIO(body.decode("utf-8-sig")),delimiter="|")
        expected={"Date","Symbol","ShortVolume","ShortExemptVolume","TotalVolume","Market"}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise SourceUnavailable("FINRA_INVALID_FILE_LAYOUT")
        aggregates=defaultdict(lambda:{"short":0.0,"total":0.0,"markets":set()})
        eligible={"SPY","QQQ","IWM"}
        day=None
        for row in reader:
            sym=str(row.get("Symbol","")).upper().strip()
            if sym not in eligible:
                continue
            rawday=str(row.get("Date","")).strip()
            if not re.fullmatch(r"\d{8}",rawday):
                raise SourceUnavailable("FINRA_INVALID_REPORT_DATE")
            thisday=datetime.strptime(rawday,"%Y%m%d").date().isoformat()
            if day is not None and day!=thisday:
                raise SourceUnavailable("FINRA_MIXED_REPORT_DATES")
            day=thisday
            short=_finite(row.get("ShortVolume"),0)
            exempt=_finite(row.get("ShortExemptVolume"),0)
            total=_finite(row.get("TotalVolume"),0)
            # Per official layout, ShortVolume already INCLUDES ShortExemptVolume.
            if total==0 or short>total or exempt>short:
                raise SourceUnavailable("FINRA_VOLUME_INCONSISTENT")
            record=aggregates[sym]
            record["short"]+=short
            record["total"]+=total
            record["markets"].add(str(row.get("Market","")).strip().upper())
        if day is None:
            raise SourceUnavailable("FINRA_TARGET_SYMBOLS_NOT_FOUND")
        values={}
        for sym,info in aggregates.items():
            if info["total"]<=0:
                continue
            values[f"finra_{sym.lower()}_short_volume_pct"]=round(
                100*info["short"]/info["total"],4)
        if not values:
            raise SourceUnavailable("FINRA_NO_VALID_VOLUME")
        return {day:values}
    except (UnicodeDecodeError,TypeError,ValueError,csv.Error) as exc:
        raise SourceUnavailable("FINRA_INVALID_VOLUME_FILE") from exc


def sample_stock_breadth(raw, asof):
    """Fixed liquid-stock sample only; never label as all-US breadth or PIT."""
    rows={}
    for symbol, bars in raw.items():
        if symbol not in EQUITY_SAMPLE or not isinstance(bars,list):
            continue
        clean=[]
        for bar in bars:
            try:
                stamp=datetime.fromisoformat(str(bar["t"]).replace("Z","+00:00"))
                day=stamp.astimezone(NY).date().isoformat()
                price=_finite(bar.get("c"),.0001)
                high=_finite(bar.get("h"),.0001)
                low=_finite(bar.get("l"),.0001)
                if low<=price<=high and day<=asof:
                    clean.append((day,price,high,low))
            except (KeyError,ValueError,TypeError,SourceUnavailable):
                continue
        ordered=sorted(clean,key=lambda v:v[0])
        if len(ordered)<21 or ordered[-1][0]!=asof or len({x[0] for x in ordered})!=len(ordered):
            continue
        rows[symbol]=ordered
    if len(rows)<24:
        raise SourceUnavailable("INSUFFICIENT_STOCK_SAMPLE_COVERAGE")
    up=above=nh=nl=0
    for v in rows.values():
        close=v[-1][1]
        up+=int(close>v[-2][1])
        above+=int(close>sum(x[1] for x in v[-20:])/20)
        nh+=int(v[-1][2]>max(x[2] for x in v[-21:-1]))
        nl+=int(v[-1][3]<min(x[3] for x in v[-21:-1]))
    n=len(rows)
    return {"stock_sample_advance_share":round(up/n*100,3),
            "stock_sample_above_ma20_share":round(above/n*100,3),
            "stock_sample_new_high20_count":nh,"stock_sample_new_low20_count":nl,
            "stock_sample_valid_count":n,"stock_sample_target_count":len(EQUITY_SAMPLE)}


class ExtendedPublicSources:
    def __init__(self, live):
        self.live=live

    @staticmethod
    def receipt(source,stamp,digest):
        return {"source":source,"fetched_at":stamp,"sha256":digest,
                "pit":"CURRENT_OBSERVATION_NOT_HISTORICAL_PIT"}

    def cboe_options(self,limit,*,refresh=False):
        from datetime import date
        # Use the last completed session and, if not yet published, walk back.
        last=datetime.fromisoformat(limit).date()
        failures=[]
        for i in range(5):
            day=(last-timedelta(days=i)).isoformat()
            if (last-timedelta(days=i)).weekday()>=5:
                continue
            url=CBOE_PREFIX+day+"_daily_options"
            try:
                body,stamp,digest=self.live.request(url,ttl=7200,refresh=refresh)
                return {day:parse_cboe_options(body)},self.receipt("CBOE_DAILY_OPTIONS",stamp,digest)
            except SourceUnavailable as exc:
                failures.append(exc.code)
                if exc.code not in ("HTTP_404","HTTP_403"):
                    break
        raise SourceUnavailable("CBOE_OPTIONS_UNAVAILABLE_"+failures[-1] if failures else "CBOE_NO_SESSION")

    def ofr_fsi(self,*,refresh=False):
        headers={"User-Agent":"QDR-Research/1.0 (public market analysis; github.com/Jack-yo/qdr-learn)"}
        body,stamp,digest=self.live.request(OFR_FSI,headers=headers,ttl=21600,refresh=refresh)
        return parse_ofr_stress_csv(body),self.receipt("OFR_FSI",stamp,digest)

    def bls_calendar(self,*,refresh=False):
        body,stamp,digest=self.live.request(BLS_CALENDAR,ttl=14400,refresh=refresh)
        return parse_bls_calendar(body),self.receipt("BLS_RELEASE_CALENDAR",stamp,digest)

    def cftc_nasdaq(self,*,refresh=False):
        query={"cftc_contract_market_code":"20974A",
               "$select":"cftc_contract_market_code,report_date_as_yyyy_mm_dd,"
                         "open_interest_all,lev_money_positions_long,lev_money_positions_short",
               "$order":"report_date_as_yyyy_mm_dd DESC","$limit":"12"}
        body,stamp,digest=self.live.request(CFTC_TFF,query,ttl=14400,refresh=refresh)
        return parse_cftc_contract(body,"20974A"),self.receipt("CFTC_TFF_NASDAQ100",stamp,digest)

    def cftc_commodity(self,commodity,*,refresh=False):
        codes={"gold":"088691","wti":"067651"}
        if commodity not in codes:
            raise SourceUnavailable("UNKNOWN_CFTC_COMMODITY")
        code=codes[commodity]
        query={"cftc_contract_market_code":code,
               "$select":"cftc_contract_market_code,report_date_as_yyyy_mm_dd,"
                         "open_interest_all,m_money_positions_long_all,m_money_positions_short_all",
               "$order":"report_date_as_yyyy_mm_dd DESC","$limit":"12"}
        body,stamp,digest=self.live.request(CFTC_DISAGG,query,ttl=14400,refresh=refresh)
        return parse_cftc_contract(body,code,trader="managed"),self.receipt("CFTC_DISAGG_"+commodity.upper(),stamp,digest)

    def cboe_equity_volume(self,limit,*,refresh=False):
        year=limit[:4]
        url=CBOE_VOLUME_PREFIX+"market_history_"+year+".csv"
        body,stamp,digest=self.live.request(url,ttl=21600,refresh=refresh)
        return parse_cboe_equities_volume(body),self.receipt("CBOE_EQUITIES_VOLUME",stamp,digest)

    def ici_weekly_etf(self,*,refresh=False):
        body,stamp,digest=self.live.request(ICI_ETF,ttl=21600,refresh=refresh)
        return parse_ici_weekly_etf_issuance(body),self.receipt(
            "ICI_WEEKLY_ESTIMATED_ETF_ISSUANCE",stamp,digest)

    def finra_short_volume(self,limit,*,refresh=False):
        last=datetime.fromisoformat(limit).date()
        failures=[]
        for n in range(8):
            day=last-timedelta(days=n)
            if day.weekday()>4:continue
            endpoint=FINRA_PREFIX+day.strftime("%Y%m%d")+".txt"
            try:
                body,stamp,digest=self.live.request(endpoint,ttl=7200,refresh=refresh)
                report=parse_finra_consolidated_short_volume(body)
                if day.isoformat() not in report:
                    raise SourceUnavailable("FINRA_REPORT_DATE_MISMATCH")
                return report,self.receipt("FINRA_CNMS_SHORT_VOLUME",stamp,digest)
            except SourceUnavailable as exc:
                failures.append(exc.code)
                if exc.code!="HTTP_404":
                    break
        raise SourceUnavailable("FINRA_SHORT_VOLUME_UNAVAILABLE_"+failures[-1]
                                if failures else "FINRA_NO_REPORT")

    def market_breadth(self,limit,*,refresh=False,now=None):
        """Broad current active/tradable non-OTC US-equity breadth from Alpaca snapshots.

        This is a current vendor universe, not historical PIT membership. Snapshot
        coverage and batch failures are returned with every metric.
        """
        stamp=now or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("market breadth clock must be timezone-aware")
        stamp=stamp.astimezone(timezone.utc)
        assets,asset_receipt=self.live.assets(refresh=refresh)
        symbols=[x["symbol"] for x in assets]
        def missing_snapshot_result(code, *, snapshot_receipts=(), batch_errors=(),
                                    observation_mode="NO_SNAPSHOT_DATA"):
            input_hashes=[asset_receipt["sha256"]]+[x["sha256"] for x in snapshot_receipts]
            derived=sha256(json.dumps({"asof":None,"inputs":sorted(input_hashes),
                "universe":"ALPACA_ACTIVE_TRADABLE_NON_OTC_CURRENT_DIRECTORY_V1",
                "snapshot_error":code},sort_keys=True,separators=(",",":")).encode()).hexdigest()
            fetched=max([asset_receipt["fetched_at"]]+[x["fetched_at"] for x in snapshot_receipts])
            expected=len(assets)
            errors=list(batch_errors)
            if code:
                errors.append({"code":code})
            result={
                "advances":None,"declines":None,"unchanged":None,
                "advance_share":None,"up_volume_share":None,
                "downside_sync_share":None,"stock_dispersion_1":None,
                "market_snapshot_coverage_pct":0.0,
                "coverage_n":0,"expected_n":expected,
                "observation_mode":observation_mode,"observed_date":None,
                "batch_count":len(snapshot_receipts),
                "batch_error_count":max(1,len(errors)),
                "feed_sources":sorted({x.get("source","UNKNOWN") for x in snapshot_receipts}),
                "batch_errors":errors[:10],
                "asset_receipt_sha256":asset_receipt["sha256"],
                "snapshot_receipt_sha256":[x["sha256"] for x in snapshot_receipts],
                "snapshot_error_code":code,
            }
            receipt={
                "source":"ALPACA_ACTIVE_US_EQUITY_SNAPSHOT_BREADTH",
                "fetched_at":fetched,"sha256":derived,
                "pit":"CURRENT_ACTIVE_ASSET_UNIVERSE_NOT_HISTORICAL_PIT",
                "coverage_n":0,"expected_n":expected,"coverage":0.0,
                "observation_mode":observation_mode,
                "batch_error_count":result["batch_error_count"],
                "feed_sources":result["feed_sources"],
                "input_receipts":input_hashes,
                "snapshot_error_code":code,
            }
            return {limit:result},receipt

        try:
            snapshots,snapshot_receipts,batch_errors=self.live.snapshots_for_symbols(
                symbols,refresh=refresh,batch_size=200,max_workers=4)
        except SourceUnavailable as exc:
            return missing_snapshot_result(exc.code)
        by_day=defaultdict(list)
        for symbol,record in snapshots.items():
            daily=record.get("dailyBar") or record.get("daily_bar") or {}
            previous=record.get("prevDailyBar") or record.get("prev_daily_bar") or {}
            try:
                day=_date(daily.get("t"))
                close=_finite(daily.get("c"),0)
                prev_close=_finite(previous.get("c"),0)
                volume=_finite(daily.get("v"),0)
                if close<=0 or prev_close<=0 or volume<0:
                    continue
                by_day[day].append((symbol,close/prev_close-1,volume))
            except (SourceUnavailable,ValueError,TypeError,KeyError):
                continue
        if not by_day:
            return missing_snapshot_result("ALPACA_BROAD_SNAPSHOT_HAS_NO_VALID_DAILY_BARS",
                snapshot_receipts=snapshot_receipts,batch_errors=batch_errors,
                observation_mode="NO_VALID_DAILY_BARS")
        # Use the most populated latest session; mixed/stale dates reduce coverage.
        latest_day=max(by_day,key=lambda day:(len(by_day[day]),day))
        rows=by_day[latest_day]
        expected=len(assets)
        covered=len(rows)
        coverage=covered/expected if expected else 0.0
        # Keep low-but-nonzero coverage as PARTIAL evidence; never discard the
        # asset-directory receipt or relabel a small sample as full-market coverage.
        returns=[x[1] for x in rows]
        volumes=[x[2] for x in rows]
        advances=sum(1 for x in returns if x>0)
        declines=sum(1 for x in returns if x<0)
        unchanged=sum(1 for x in returns if x==0)
        total_volume=sum(volumes)
        up_volume=sum(vol for (_,ret,vol) in rows if ret>0)
        mean=sum(returns)/len(returns)
        dispersion=math.sqrt(sum((x-mean)**2 for x in returns)/len(returns))*100
        input_hashes=[asset_receipt["sha256"]]+[x["sha256"] for x in snapshot_receipts]
        derived=sha256(json.dumps({"asof":latest_day,"inputs":sorted(input_hashes),
            "universe":"ALPACA_ACTIVE_TRADABLE_NON_OTC_CURRENT_DIRECTORY_V1"},
            sort_keys=True,separators=(",",":")).encode()).hexdigest()
        fetched=max([asset_receipt["fetched_at"]]+[x["fetched_at"] for x in snapshot_receipts])
        from quant_research.clock import TradingClock
        clock=TradingClock()
        latest_session=clock.session(limit)
        completed=clock.close(latest_session)+clock.delay<=stamp
        mode=("COMPLETED_DAILY_BAR" if latest_day==limit and completed else
              "INTRADAY_SNAPSHOT" if latest_day>limit else
              "LATEST_AVAILABLE_DAILY_BAR" if latest_day==limit else "STALE_SNAPSHOT")
        result={
            "advances":advances,"declines":declines,"unchanged":unchanged,
            "advance_share":advances/covered*100,
            "up_volume_share":up_volume/total_volume*100 if total_volume else None,
            "downside_sync_share":declines/covered*100,
            "stock_dispersion_1":dispersion,
            "market_snapshot_coverage_pct":coverage*100,
            "coverage_n":covered,"expected_n":expected,
            "observation_mode":mode,"observed_date":latest_day,
            "batch_count":len(snapshot_receipts),"batch_error_count":len(batch_errors),
            "feed_sources":sorted({x.get("source","UNKNOWN") for x in snapshot_receipts}),
            "batch_errors":batch_errors[:10],
            "asset_receipt_sha256":asset_receipt["sha256"],
            "snapshot_receipt_sha256":[x["sha256"] for x in snapshot_receipts],
        }
        receipt={"source":"ALPACA_ACTIVE_US_EQUITY_SNAPSHOT_BREADTH",
            "fetched_at":fetched,"sha256":derived,
            "pit":"CURRENT_ACTIVE_ASSET_UNIVERSE_NOT_HISTORICAL_PIT",
            "coverage_n":covered,"expected_n":expected,"coverage":coverage,
            "observation_mode":mode,"batch_error_count":len(batch_errors),
            "feed_sources":result["feed_sources"],"input_receipts":input_hashes}
        return {limit:result},receipt

    def stock_breadth(self,limit,*,refresh=False):
        raw,receipts=self.live.bars(days=55,refresh=refresh,symbols=EQUITY_SAMPLE)
        output=sample_stock_breadth(raw,limit)
        receipt=receipts[-1] if receipts else {}
        return {limit:output},self.receipt("ALPACA_STOCK_SAMPLE_"+SAMPLE_ID,
                receipt.get("fetched_at"),receipt.get("sha256"))


def scan_extended_public(root,*,sources=None,now=None,refresh=False):
    """Best-effort extras isolated from existing L1 market and official panels."""
    from quant_research.clock import TradingClock
    stamp=now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("timestamp must have timezone")
    stamp=stamp.astimezone(timezone.utc)
    clock=TradingClock()
    latest=clock.calendar.date_to_session(stamp.date(),direction="previous")
    while clock.close(latest)+clock.delay>stamp:
        latest=clock.calendar.previous_session(latest)
    limit=latest.date().isoformat()
    provider=ExtendedPublicSources(sources or LiveSources(root))
    jobs={
        "cboe_options":lambda:provider.cboe_options(limit,refresh=refresh),
        "ofr_fsi":lambda:provider.ofr_fsi(refresh=refresh),
        "bls_calendar":lambda:provider.bls_calendar(refresh=refresh),
        "cftc_nasdaq":lambda:provider.cftc_nasdaq(refresh=refresh),
        "cftc_gold":lambda:provider.cftc_commodity("gold",refresh=refresh),
        "cftc_wti":lambda:provider.cftc_commodity("wti",refresh=refresh),
        "cboe_equity_volume":lambda:provider.cboe_equity_volume(limit,refresh=refresh),
        "stock_sample":lambda:provider.stock_breadth(limit,refresh=refresh),
        "market_breadth":lambda:provider.market_breadth(limit,refresh=refresh,now=stamp),
        "ici_etf":lambda:provider.ici_weekly_etf(refresh=refresh),
        "finra_short_volume":lambda:provider.finra_short_volume(limit,refresh=refresh),
    }
    health,features,calendar_events={},[],[]
    with ThreadPoolExecutor(max_workers=10) as pool:
        future={name:pool.submit(fn) for name,fn in jobs.items()}
        for name,job in future.items():
            try:
                values,receipt=job.result()
                if name=="bls_calendar":
                    if not isinstance(values,list):
                        raise SourceUnavailable("BLS_BAD_EVENT_PAYLOAD")
                    upcoming=[x for x in values if stamp<=x["dt"]<=stamp+timedelta(days=14)]
                    calendar_events=[{
                        "event_id":str(x["name"])+"|"+x["dt"].isoformat(),
                        "name":x["name"],
                        "event_type":("CPI" if "consumer price index" in str(x["name"]).lower()
                                      else "NFP" if "employment situation" in str(x["name"]).lower()
                                      else "BLS"),
                        "start_utc":x["dt"].isoformat(),
                        "schedule_known_at":receipt["fetched_at"],
                        "source":receipt["source"],
                        "receipt_sha256":receipt["sha256"],
                    } for x in upcoming[:25]]
                    day=limit
                    values={
                        day:{"bls_scheduled_next_7d":sum(1 for x in values if stamp<=x["dt"]<=stamp+timedelta(days=7))}
                    }
                eligible=[(d,v) for d,v in values.items() if d<=limit]
                if name=="ici_etf":
                    # Use source article's publication day, not its Wednesday week-end,
                    # and hold until that publication date has fully elapsed in UTC.
                    eligible=[(d,v) for d,v in eligible if
                        stamp>=datetime.fromisoformat(v["source_published_date"]).replace(
                            tzinfo=timezone.utc)+timedelta(days=1)]
                if name.startswith("cftc_"):
                    # The Tuesday position report may not be published until
                    # Friday afternoon; do not predate this in the model UI.
                    eligible=[(d,v) for d,v in eligible if stamp>=
                              datetime.fromisoformat(d).replace(tzinfo=timezone.utc)+
                              timedelta(days=3,hours=22)]
                if not eligible:
                    raise SourceUnavailable("NO_RELEASED_OBSERVATION")
                day,value=max(eligible)
                lag=(datetime.fromisoformat(limit)-datetime.fromisoformat(day)).days
                max_lag=28 if name=="ici_etf" else 21 if name.startswith("cftc_") else 12 if name=="ofr_fsi" else 7
                if lag>max_lag:
                    raise SourceUnavailable("STALE_OBSERVATION")
                health[name]={"status":"OBSERVED","source":receipt["source"],
                              "effective_date":day,"fetched_at":receipt["fetched_at"],
                              "receipt_sha256":receipt["sha256"],"pit":receipt["pit"],
                              "coverage_n":receipt.get("coverage_n"),
                              "expected_n":receipt.get("expected_n"),
                              "observation_mode":receipt.get("observation_mode"),
                              "feed_sources":receipt.get("feed_sources"),
                              "batch_error_count":receipt.get("batch_error_count"),
                              "input_receipts":receipt.get("input_receipts")}
                def add(domain,fid,label,val,unit,scope="CURRENT_OBSERVATION_NOT_PIT",
                        *,status="OBSERVED",observed_day=None,coverage_n=None,
                        expected_n=None,metadata=None):
                    features.append({"domain":domain,"id":fid,"label":label,
                        "value":None if val is None else round(_finite(val),5),"unit":unit,
                        "status":status,"source":receipt["source"],
                        "observed_date":observed_day or day,
                        "fetched_at":receipt["fetched_at"],"pit":scope,
                        "receipt_sha256":receipt["sha256"],
                        "coverage_n":coverage_n,"expected_n":expected_n,
                        "metadata":metadata or {}})
                if name=="cboe_options":
                    for field,title in (("cboe_pcr_total","全市场期权成交 Put/Call"),
                                        ("cboe_pcr_index","指数期权成交 Put/Call"),
                                        ("cboe_pcr_equity","个股期权成交 Put/Call"),
                                        ("cboe_pcr_etp","ETF期权成交 Put/Call")):
                        if field in value:
                            add("options_pricing",field,title,value[field],"x")
                    if "cboe_spx_put_call_oi" in value:
                        add("options_positioning","cboe_spx_put_call_oi",
                            "SPX 系列 Put/Call 未平仓量比例",value["cboe_spx_put_call_oi"],"x",
                            "AGGREGATE_OI_NOT_DEALER_GAMMA")
                elif name=="ofr_fsi":
                    add("funding","ofr_fsi","OFR 综合金融压力指数",value["ofr_fsi"],"指数点")
                elif name=="bls_calendar":
                    add("events","bls_scheduled_next_7d",
                        "未来7天 BLS 已排程经济发布",value["bls_scheduled_next_7d"],"项",
                        "CURRENT_PUBLISHED_EVENT_SCHEDULE_NOT_HISTORICAL_PIT")
                elif name in ("cftc_nasdaq","cftc_gold","cftc_wti"):
                    title={"cftc_nasdaq":"Nasdaq-100 杠杆基金净仓 / OI",
                           "cftc_gold":"黄金管理资金净仓 / OI",
                           "cftc_wti":"WTI 管理资金净仓 / OI"}[name]
                    add("positioning",name+"_net_pct_oi",title,value["net_pct_oi"],"%",
                        "TUESDAY_FUTURES_POSITION_RELEASED_FRIDAY")
                elif name=="cboe_equity_volume":
                    add("microstructure","cboe_trf_notional_share",
                        "全市场场外报告成交额占比 (TRF)",
                        value["cboe_trf_notional_share"],"%",
                        "TRADE_REPORTING_FACILITY_NOT_DIRECTIONAL_ORDER_FLOW")
                elif name=="ici_etf":
                    add("positioning","ici_weekly_etf_net_issuance_bn_usd",
                        "ICI 全美 ETF 周度净发行估算",value["ici_weekly_etf_net_issuance_bn_usd"],
                        "十亿美元","ICI_WEEKLY_ESTIMATE_PUBLISHED_AFTER_WEEK_END_NOT_DAILY_FLOW")
                    features[-1]["published_date"]=value["source_published_date"]
                    health[name]["published_date"]=value["source_published_date"]
                elif name=="finra_short_volume":
                    for field,title in (
                        ("finra_spy_short_volume_pct","FINRA报告SPY卖空成交占比"),
                        ("finra_qqq_short_volume_pct","FINRA报告QQQ卖空成交占比"),
                        ("finra_iwm_short_volume_pct","FINRA报告IWM卖空成交占比"),
                    ):
                        if field in value:
                            add("microstructure",field,title,value[field],"%",
                                "FINRA_TRF_AND_ADF_SHORT_TRADE_VOLUME_NOT_SHORT_INTEREST")
                elif name=="stock_sample":
                    for field,title,unit in (
                        ("stock_sample_advance_share","30只大盘股样本当日上涨占比","%"),
                        ("stock_sample_above_ma20_share","样本股站上 MA20 占比","%"),
                        ("stock_sample_new_high20_count","样本股20日新高家数","家"),
                        ("stock_sample_new_low20_count","样本股20日新低家数","家"),
                    ):
                        add("breadth",field,title,value[field],unit,
                            "FIXED_30_LARGE_CAP_STOCK_SAMPLE_NOT_FULL_MARKET_PIT")
                elif name=="market_breadth":
                    coverage_n=value["coverage_n"];expected_n=value["expected_n"]
                    status=("OBSERVED" if coverage_n/expected_n>=0.98 and
                             not value["batch_error_count"] and
                             value["observation_mode"]!="STALE_SNAPSHOT" else "PARTIAL")
                    if coverage_n == 0:
                        status="MISSING"
                    health[name]["status"]=status
                    health[name]["code"]=value.get("snapshot_error_code")
                    health[name]["effective_date"]=value.get("observed_date")
                    scope="CURRENT_ACTIVE_TRADABLE_ALPACA_UNIVERSE_NOT_HISTORICAL_PIT"
                    meta={"observation_mode":value["observation_mode"],
                          "coverage_pct":round(value["market_snapshot_coverage_pct"],3),
                          "batch_count":value["batch_count"],
                          "batch_error_count":value["batch_error_count"],
                          "feed_sources":value["feed_sources"],
                          "input_receipts":[value["asset_receipt_sha256"]]+value["snapshot_receipt_sha256"]}
                    observed_day=value["observed_date"]
                    for domain,field,title,unit in (
                        ("breadth","advances","全市场活跃可交易证券上涨家数","只"),
                        ("breadth","declines","全市场活跃可交易证券下跌家数","只"),
                        ("breadth","unchanged","全市场活跃可交易证券平盘家数","只"),
                        ("breadth","advance_share","全市场活跃可交易证券上涨占比","%"),
                        ("breadth","up_volume_share","全市场活跃可交易证券上涨成交量占比","%"),
                        ("breadth","market_snapshot_coverage_pct","全市场快照覆盖率","%"),
                        ("correlation","downside_sync_share","全市场活跃可交易证券同步下跌占比","%"),
                        ("correlation","stock_dispersion_1","全市场活跃可交易证券日收益离散度","%"),
                    ):
                        if value[field] is None:
                            continue
                        add(domain,field,title,value[field],unit,scope,status=status,
                            observed_day=observed_day,coverage_n=coverage_n,
                            expected_n=expected_n,metadata=meta)
            except (SourceUnavailable,ValueError,KeyError,TypeError,OverflowError) as exc:
                health[name]={"status":"MISSING","code":getattr(exc,"code",type(exc).__name__),
                              "fetched_at":stamp.isoformat()}
    return {"schema":"qdr.l1.extended.v1","asof_session":limit,
            "status":"OBSERVATION_ONLY" if features else "NO_AVAILABLE_PUBLIC_FEED",
            "historical_pit_verified":False,"not_in_model_scores":True,
            "source_health":health,"features":features,"calendar_events":calendar_events,
            "fetched_at":stamp.isoformat()}
