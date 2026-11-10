"""French daily ZIP adapters: percent to decimal, vintage retained, attribution only."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO, StringIO
import re
from zipfile import ZipFile

from quant_research.data.http import DataUnavailable
from quant_research.data.schema import FactorRecord

FILES = {
    "ff5": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "momentum": "F-F_Momentum_Factor_daily_CSV.zip",
    "reversal": "F-F_ST_Reversal_Factor_daily_CSV.zip",
}


def parse_daily_zip(body, fetched_at, version):
    with ZipFile(BytesIO(body)) as archive:
        candidates = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if len(candidates) != 1:
            raise DataUnavailable("Expected exactly one French CSV")
        if archive.getinfo(candidates[0]).file_size > 50_000_000:
            raise DataUnavailable("French CSV exceeds maximum size")
        content = archive.read(candidates[0]).decode("utf-8-sig")
    header, records, seen = None, [], set()
    aliases = {"Mom": "Mom", "ST_Rev": "ST_Rev", "ST Rev": "ST_Rev", "Mkt-RF": "Mkt-RF"}
    for cells in csv.reader(StringIO(content)):
        cells = [c.strip() for c in cells]
        if not cells:
            continue
        if cells[0] == "" and any(c in ("Mkt-RF", "Mom", "ST_Rev", "ST Rev") for c in cells[1:]):
            header = [aliases.get(c, c) for c in cells[1:]]
            continue
        if not re.fullmatch(r"\d{8}", cells[0]):
            continue
        if header is None or len(cells) != len(header) + 1:
            raise DataUnavailable("French daily header/row schema mismatch")
        day = datetime.strptime(cells[0], "%Y%m%d").date()
        if day > fetched_at.date():
            raise DataUnavailable("French future-dated factor row")
        for name, value in zip(header, cells[1:], strict=True):
            key = (day, name)
            if key in seen:
                raise DataUnavailable("Duplicate French factor primary key")
            seen.add(key)
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise DataUnavailable("Invalid French numeric value") from None
            if not number.is_finite():
                raise DataUnavailable("Non-finite French factor")
            missing = number in (Decimal("-99.99"), Decimal("-999"))
            if not missing and abs(number) > 100:
                raise DataUnavailable("French percent outside plausible daily bounds")
            records.append(FactorRecord(date=day, factor_name=name,
                value_decimal=None if missing else float(number / 100),
                available_at=fetched_at, version=version))
    if not records:
        raise DataUnavailable("No daily French factor rows found")
    return records


class FrenchProvider:
    def __init__(self, http):
        self.http = http

    def factors(self, dataset):
        if dataset not in FILES:
            raise ValueError("Unknown French dataset")
        raw = self.http.get("https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/" + FILES[dataset])
        return parse_daily_zip(raw.body, raw.fetched_at, raw.sha256)
