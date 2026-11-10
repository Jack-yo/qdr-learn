"""SEC submissions + companyfacts snapshots; explicitly not a reconstructed PIT dataset."""
from datetime import datetime
from datetime import date
import json
import os
import re

from quant_research.data.http import DataUnavailable


class SECProvider:
    def __init__(self, http, user_agent=None):
        self.http = http
        self.user_agent = user_agent or os.environ.get("SEC_USER_AGENT", "")

    def filing_history(self,snapshot,start='2017-01-01',end='2024-12-31'):
        """Fetch every advertised history page, retaining unverified source clocks."""
        date.fromisoformat(start);date.fromisoformat(end)
        if start>end:raise ValueError('Invalid filing interval')
        payload=snapshot['payload'];cik=str(snapshot['cik']).zfill(10)
        pages=[(payload['filings']['recent'],snapshot['raw_sha256'],snapshot['fetched_at'])]
        for entry in payload['filings'].get('files',[]):
            name=entry['name']
            if not re.fullmatch(r'CIK'+cik+r'-submissions-[0-9]+\.json',name):raise DataUnavailable('Historical filing name mismatch')
            raw=self.http.get('https://data.sec.gov/submissions/'+name,headers={'User-Agent':self.user_agent,'Accept':'application/json'})
            history=json.loads(raw.body)
            if len(history.get('accessionNumber',[]))!=entry['filingCount']:raise DataUnavailable('Historical filing page count mismatch')
            pages.append((history,raw.sha256,raw.fetched_at))
        rows,seen=[],set()
        for table,digest,observed in pages:
            fields=('accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument')
            size=len(table.get('accessionNumber',[]))
            if any(len(table.get(f,[]))!=size for f in fields):raise DataUnavailable('Filing history array lengths disagree')
            for i in range(size):
                accession=table['accessionNumber'][i]
                if accession in seen:raise DataUnavailable('Duplicate accession across history pages')
                seen.add(accession)
                if not re.fullmatch(r'\d{10}-\d{2}-\d{6}',accession):raise DataUnavailable('Invalid accession')
                filed=table['filingDate'][i];date.fromisoformat(filed)
                if not start<=filed<=end:continue
                document=table['primaryDocument'][i]
                if document and (document.startswith('/') or '..' in document or not re.fullmatch(r'[A-Za-z0-9_.\-/]+',document)):
                    raise DataUnavailable('Unsafe filing document path')
                rows.append({'cik':cik,'accession':accession,'form':table['form'][i],
                    'filed_date':filed,'period_end':table['reportDate'][i] or None,
                    'accepted_time_source_text':table['acceptanceDateTime'][i],
                    'accepted_at_verified_utc':None,'available_at_historical_utc':None,
                    'retrieved_at_utc':observed.isoformat(),'source_hash':digest,
                    'primary_document':document,'publication_status':'ORIGINAL_HEADER_REQUIRED',
                    'source_version_kind':'current_revised_snapshot'})
        self.history_page_evidence=[{'sha256':d,'rows':len(t['accessionNumber']),'retrieved_at_utc':o.isoformat()} for t,d,o in pages]
        return sorted(rows,key=lambda r:(r['filed_date'],r['accession']))

    def snapshots(self, cik):
        if not re.fullmatch(r"\d{1,10}", str(cik)) or int(cik) == 0:
            raise ValueError("CIK must contain 1–10 digits and be positive")
        if not self.http.offline and not re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.user_agent):
            raise DataUnavailable("Set SEC_USER_AGENT to project name and real contact email")
        cik = str(cik).zfill(10)
        headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        results = []
        for kind, path in [("submissions", f"submissions/CIK{cik}.json"),
                           ("companyfacts", f"api/xbrl/companyfacts/CIK{cik}.json")]:
            raw = self.http.get("https://data.sec.gov/" + path, headers=headers)
            payload = json.loads(raw.body)
            if int(payload.get("cik", -1)) != int(cik):
                raise DataUnavailable("SEC response CIK does not match request")
            if kind == "submissions" and not isinstance(payload.get("filings", {}).get("recent"), dict):
                raise DataUnavailable("Unexpected SEC submissions schema")
            if kind == "companyfacts" and not isinstance(payload.get("facts"), dict):
                raise DataUnavailable("Unexpected SEC companyfacts schema")
            results.append({"cik": cik, "kind": kind, "raw_sha256": raw.sha256,
                            "fetched_at": raw.fetched_at, "available_at": raw.fetched_at,
                            "quality_flag": "SNAPSHOT_ONLY|NOT_PIT", "payload": payload})
        return results


def recent_filings(snapshot):
    """Preserve acceptance time, but knowledge time stays first observation."""
    recent = snapshot["payload"]["filings"]["recent"]
    required = ["accessionNumber", "form", "acceptanceDateTime", "reportDate"]
    if any(key not in recent for key in required):
        raise DataUnavailable("SEC recent filing arrays missing required fields")
    size = len(recent["accessionNumber"])
    if any(len(recent[key]) != size for key in required):
        raise DataUnavailable("SEC recent filing arrays have unequal lengths")
    results = []
    for index in range(size):
        stamp = recent["acceptanceDateTime"][index]
        accepted = datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        if accepted is not None and (accepted.tzinfo is None or accepted > snapshot["fetched_at"]):
            raise DataUnavailable("Invalid SEC acceptance timestamp")
        results.append({"cik": snapshot["cik"], "accession": recent["accessionNumber"][index],
            "form": recent["form"][index], "period_end": recent["reportDate"][index] or None,
            "accepted_at": accepted, "available_at": snapshot["available_at"],
            "source_version": snapshot["raw_sha256"], "quality_flag": "SNAPSHOT_ONLY|NOT_PIT"})
    return results
