import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from quant_research.web import Console, action_commands, handler, snapshot, ThreadingHTTPServer


def test_real_actions_never_execute_or_unseal():
    for action in ("market", "factors", "daily", "market-model", "alpha-model"):
        command = action_commands(action)[0]
        assert command[0] not in {"backtest", "paper-step", "paper-replay"}
        assert command[command.index("--source") + 1] == "yahoo"
        assert command[command.index("--mode") + 1] == "retrospective"
    with pytest.raises(ValueError): action_commands("arbitrary-command")
    assert action_commands("acceptance")[0][0] == "real-acceptance"
    assert action_commands("daily", "alpaca") == [["daily-observation"]]
    assert action_commands("market-research-yahoo", "alpaca")[0] == [
        "train-market", "--source", "yahoo", "--mode", "retrospective",
        "--db", "data/research.duckdb", "--output", "outputs/market_research",
    ]


def test_missing_database_is_explicit(tmp_path):
    state = snapshot(tmp_path)
    assert state["prices"] == []
    assert not state["execution_enabled"]
    assert not state["real_orders_enabled"]


def test_console_single_writer_and_http_boundaries(tmp_path):
    console = Console(tmp_path)
    console.lock.acquire()
    assert not console.start("market")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(console))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # Legacy duplicate workspaces now resolve to the V4 page shell.
        # The URL fragment selects the relevant tab client-side.
        for route in ('overview','market','styles'):
            with urlopen(base+'/'+route) as response:
                page=response.read().decode('utf-8')
                assert response.status == 200
                assert '/studio' in response.url
                assert 'QDR Quant Studio' in page
                assert 'v4_ui_fidelity.js' in page
        # Specialized legacy tools are intentionally not removed until the
        # V4 equivalents cover their full write/preflight workflows.
        for route in ('factors','strategies','backtests','signals','paper','data'):
            with urlopen(base+'/'+route) as response:
                page=response.read().decode('utf-8')
                assert response.status == 200 and 'REAL_ONLY' in page and 'blocked-view' in page
        for stale in ('/market.html','/styles.html','/factor_lab.html',
                      '/web.html','/backtests.html','/daily_observation.html'):
            with pytest.raises(HTTPError) as error:
                urlopen(base+stale)
            assert error.value.code==404
        with urlopen(base + "/api/status") as response:
            assert json.load(response)["busy"]
        with urlopen(base + "/api/v1/paper") as response:
            paper = json.load(response)
            assert paper["status"] == "BLOCKED"
            assert paper["account"]["cash"] is None and paper["account"]["fills"] is None
        for query, status in (("", 409), ("?asof=11-06", 400)):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/signals" + query)
            assert error.value.code == status
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/data/close-snapshots")
        assert error.value.code == 409
        assert json.load(error.value)["code"] == "NO_CLOSE_SNAPSHOT"
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/data/close-snapshots?asof=11-06")
        assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/v1/market/research?horizon=5")
        assert error.value.code == 409
        assert json.load(error.value)["code"] == "NO_COMPLETED_MARKET_STUDY"
        for query in ("horizon=2", "horizon=1&horizon=5", "asof=2025-01-02"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/market/research?" + query)
            assert error.value.code == 400
        for path in ("/AGENTS.md", "/outputs/../AGENTS.md", "/outputs/%2e%2e/AGENTS.md"):
            with pytest.raises(HTTPError) as error: urlopen(base + path)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/run/market", method="POST"))
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/api/status", headers={"Host":"evil.example"}))
        assert error.value.code == 403
        request = Request(base + "/api/run/market", method="POST", headers={"X-Console-Token":console.token})
        with pytest.raises(HTTPError) as error: urlopen(request)
        assert error.value.code == 409
    finally:
        console.lock.release()
        server.shutdown()
        server.server_close()
        thread.join()
