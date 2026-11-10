"""Convert P0 fixture bars into the same normalized schema as real market data."""
import hashlib
import json

from quant_research.data.schema import PriceRecord


def normalize_fixture(bars):
    body = json.dumps([b.model_dump(mode="json") for b in bars], sort_keys=True).encode()
    digest = hashlib.sha256(body).hexdigest()
    records = [PriceRecord(**bar.model_dump(exclude={"source"}), symbol=bar.security_id.removeprefix("SYNTH-"),
                          source="SYNTHETIC_FIXTURE", feed="fixture", availability_basis="synthetic",
                          raw_sha256=digest, quality_flag="SYNTHETIC|DATA_INCOMPLETE|NOT_READY") for bar in bars]
    return records, body
