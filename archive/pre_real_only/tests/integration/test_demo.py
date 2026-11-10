import json
import socket

import pytest

from quant_research.cli import main


def test_demo_offline_reproducible(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network forbidden in fixture demo")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for _ in range(2):
        assert main(["demo", "--fixture", "--output", str(tmp_path)]) == 0
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in tmp_path.glob("*/report.json")]
    assert len(reports) == 2
    assert reports[0]["result_sha256"] == reports[1]["result_sha256"]
    assert reports[0]["run_id"] != reports[1]["run_id"]
    assert reports[0]["future_leakage_blocked"]
    assert reports[0]["performance"] is None
    assert reports[0]["securities"] == 20
    for directory in tmp_path.iterdir():
        assert (directory / "run.log").read_text(encoding="utf-8").find(directory.name) >= 0


@pytest.mark.parametrize("day", ["2024-11-28", "2024-11-30", "2099-01-01", "2024-12-09", "invalid"])
def test_cli_invalid_asof(tmp_path, day):
    with pytest.raises(SystemExit) as exc:
        main(["demo", "--fixture", "--asof", day, "--output", str(tmp_path)])
    assert exc.value.code == 2
    assert not list(tmp_path.iterdir())
