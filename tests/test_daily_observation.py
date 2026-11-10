from pathlib import Path
import json
import shutil

import pandas as pd
import pytest

from quant_research.data.close_snapshot import STORE, read_snapshot
from quant_research.policy import PolicyError
from quant_research.workflow.daily_observation import generate, latest_report
from quant_research.workflow.forward_observations import inventory


def test_real_frozen_observation_replays_with_auditable_prices(tmp_path):
    root = Path.cwd()
    if not (root / STORE).is_file():
        pytest.skip("BLOCKED_NO_REAL_PREOPEN_CAPTURE")
    snap = read_snapshot(root)
    day = snap["session_date_et"]
    (tmp_path / STORE).parent.mkdir(parents=True)
    shutil.copyfile(root / STORE, tmp_path / STORE)
    raw = tmp_path / "data/raw"
    (raw / "objects").mkdir(parents=True)
    (raw / "receipts").mkdir()
    digests = {row["raw_sha256"] for row in snap["rows"]}
    for digest in digests:
        shutil.copyfile(root / "data/raw/objects" / digest, raw / "objects" / digest)
    for receipt in (root / "data/raw/receipts").glob("*.json"):
        if json.loads(receipt.read_text(encoding="utf-8")).get("sha256") in digests:
            shutil.copyfile(receipt, raw / "receipts" / receipt.name)

    report = generate(tmp_path, day)
    assert report["capture_sha256"] == snap["capture_sha256"]
    data = latest_report(tmp_path, day)
    assert data["session_date_et"] == day and not data["decision_eligible"]
    assert data["signal_status"] == "BLOCKED_NO_ELIGIBLE_MODEL" and data["candidates"] == []
    assert data["style_observation"]["code"] == "NO_FRENCH_DATA"
    quotes = pd.read_csv(tmp_path / data["artifacts"]["quotes.csv"])
    assert len(quotes) == 20
    assert quotes.capture_sha256.eq(snap["capture_sha256"]).all()
    spy = next(row for row in snap["rows"] if row["symbol"] == "SPY")
    assert data["market_observation"]["spy_bar_open_to_close"] == pytest.approx(spy["close"] / spy["open"] - 1)
    assert inventory(tmp_path)["status"] == "BLOCKED"
    assert not (tmp_path / "data/paper.sqlite3").exists()

    # No nearest-date substitution for a historical request.
    with pytest.raises(PolicyError, match="Freeze the SIP"):
        latest_report(tmp_path, "2024-12-31")
    (tmp_path / data["artifacts"]["quotes.csv"]).write_text("corrupted export", encoding="utf-8")
    with pytest.raises(PolicyError, match="SHA256"):
        latest_report(tmp_path)


def test_missing_freeze_does_not_emit_report(tmp_path):
    with pytest.raises(PolicyError) as error:
        generate(tmp_path, "2024-12-31")
    assert error.value.code == "NO_CLOSE_SNAPSHOT"
    assert not (tmp_path / "outputs").exists()
