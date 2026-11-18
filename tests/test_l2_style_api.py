import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from quant_research.web import Console, handler, ThreadingHTTPServer



def test_l2_style_overview_api_is_read_only_and_validates_query(tmp_path, monkeypatch):
    from quant_research.workflow import l2_styles

    called = []
    monkeypatch.setattr(
        l2_styles, "calculate",
        lambda root, **kwargs: called.append((root, kwargs)) or {
            "schema": "qdr.l2.style-registry.v1",
            "status": "OBSERVATION_ONLY",
            "latest": [],
        },
    )
    console = Console(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(console))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/l2/styles/overview?asof=2025-04-09&start=2025-01-02") as response:
            payload = json.load(response)
            assert response.status == 200
            assert payload["status"] == "OBSERVATION_ONLY"
        assert len(called) == 1
        assert called[0][1]["asof"] == "2025-04-09"
        assert called[0][1]["start"] == "2025-01-02"
        for query in ("?unknown=1", "?asof=2025-02-30", "?asof=2025-04-09&asof=2025-04-10"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/overview" + query)
            assert error.value.code == 400
        assert len(called) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_l2_rotation_api_exposes_read_only_asof_replay(tmp_path, monkeypatch):
    from quant_research.workflow import l2_styles

    called = []
    def stub(root, **kwargs):
        called.append(kwargs)
        return {
            "schema": "qdr.l2.rotation.v1",
            "status": "OBSERVATION_ONLY",
            "asof_session": kwargs["asof"],
            "historical_decision_eligible": False,
            "real_orders_enabled": False,
            "latest": [{"style_id": "size", "rotation_state": "UNKNOWN",
                        "block_reason": "MISSING_20D_SOURCE_AVAILABILITY"}],
            "history": [], "transitions": [],
        }

    monkeypatch.setattr(l2_styles, "calculate_rotation", stub)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/l2/styles/rotation?asof=2025-04-09") as response:
            result = json.load(response)
            assert response.status == 200
        assert result["schema"] == "qdr.l2.rotation.v1"
        assert result["latest"][0]["rotation_state"] == "UNKNOWN"
        assert result["real_orders_enabled"] is False
        assert called[0]["asof"] == "2025-04-09"
        for query in ("?unknown=1", "?start=not-a-date",
                      "?asof=2025-04-09&asof=2025-04-10"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/rotation" + query)
            assert error.value.code == 400
        assert len(called) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_l2_overview_combines_rotation_without_second_data_read(tmp_path, monkeypatch):
    from quant_research.workflow import l2_styles
    called = []
    def stub(root, **kwargs):
        called.append(kwargs)
        assert kwargs.get("include_rotation") is True
        return {
            "schema": "qdr.l2.style-registry.v1",
            "status": "OBSERVATION_ONLY",
            "latest": [],
            "rotation": {"schema": "qdr.l2.rotation.v1", "latest": []},
        }

    monkeypatch.setattr(l2_styles, "calculate", stub)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/l2/styles/overview?rotation=1&asof=2025-04-09") as response:
            payload = json.load(response)
            assert response.status == 200
        assert payload["rotation"]["schema"] == "qdr.l2.rotation.v1"
        assert len(called) == 1
        assert called[0]["asof"] == "2025-04-09"
        for q in ("?rotation=0", "?rotation=true", "?rotation=1&rotation=1"):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/overview" + q)
            assert error.value.code == 400
        assert len(called) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_l2_forecast_api_is_read_only_and_strictly_validates_query(tmp_path, monkeypatch):
    from quant_research.workflow import l2_forecast

    calls = []
    monkeypatch.setattr(
        l2_forecast, "calculate_forecast",
        lambda root, **kwargs: calls.append(kwargs) or {
            "schema": "qdr.l2.forecast.v1",
            "status": "BLOCKED",
            "code": "L2_VERIFIED_LABEL_BUNDLE_REQUIRED",
            "forecasts": [],
            "real_orders_enabled": False,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/l2/styles/forecast?asof=2025-04-09&horizon=3") as response:
            payload = json.load(response)
            assert response.status == 200
        assert payload["code"] == "L2_VERIFIED_LABEL_BUNDLE_REQUIRED"
        assert calls == [{"asof": "2025-04-09", "horizon": 3, "start": "2017-01-03"}]
        for query in (
            "?horizon=2",
            "?horizon=abc",
            "?unknown=1",
            "?asof=2025-02-30",
            "?horizon=3&horizon=5",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/forecast" + query)
            assert error.value.code == 400
        assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_l2_validation_api_reads_frozen_report_only(tmp_path, monkeypatch):
    from quant_research.workflow import l2_validation

    calls = []
    monkeypatch.setattr(
        l2_validation, "read_latest_validation",
        lambda root, asof=None: calls.append(asof) or {
            "schema": "qdr.l2.validation.v1",
            "status": "BLOCKED",
            "code": "L2_P5_VALIDATION_REPORT_NOT_FOUND",
            "asof_session": asof,
            "qualification": [],
            "real_orders_enabled": False,
        },
    )
    monkeypatch.setattr(
        l2_validation, "build_validation_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("GET must not run P5")
        ),
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/api/v1/l2/styles/validation?asof=2026-01-30") as response:
            payload = json.load(response)
            assert response.status == 200
        assert payload["code"] == "L2_P5_VALIDATION_REPORT_NOT_FOUND"
        assert calls == ["2026-01-30"]
        for query in (
            "?unknown=1",
            "?asof=2026-02-30",
            "?asof=2026-01-30&asof=2026-01-31",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/validation" + query)
            assert error.value.code == 400
        assert calls == ["2026-01-30"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_l2_downstream_context_api_is_read_only_and_validates_asof(tmp_path, monkeypatch):
    from quant_research.workflow import l2_downstream

    calls = []
    monkeypatch.setattr(
        l2_downstream, "build_downstream_context",
        lambda root, asof=None: calls.append(asof) or {
            "schema": "qdr.l2.downstream-context.v1",
            "status": "RESEARCH_ONLY",
            "code": "NO_MODEL_ADMITTED_L2_STYLE_UNITS",
            "asof_session": asof,
            "contexts": [],
            "admitted_units": 0,
            "l3_style_context_available": False,
            "real_orders_enabled": False,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(
            base + "/api/v1/l2/styles/downstream-context?asof=2026-01-30"
        ) as response:
            payload = json.load(response)
            assert response.status == 200
        assert payload["code"] == "NO_MODEL_ADMITTED_L2_STYLE_UNITS"
        assert payload["l3_style_context_available"] is False
        assert calls == ["2026-01-30"]
        for query in (
            "?unknown=1",
            "?asof=2026-02-30",
            "?asof=2026-01-30&asof=2026-01-31",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/l2/styles/downstream-context" + query)
            assert error.value.code == 400
        assert calls == ["2026-01-30"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_v4_layers_api_is_read_only_and_strictly_validates_query(tmp_path, monkeypatch):
    from quant_research.workflow import v4_layer_status

    calls = []
    monkeypatch.setattr(
        v4_layer_status, "four_layer_status",
        lambda root, asof=None, horizon=3: calls.append((asof, horizon)) or {
            "schema": "qdr.v4.layer-status.v1",
            "status": "RESEARCH_ONLY",
            "asof_session": asof,
            "horizon": horizon,
            "blockers": ["L3_L2_STYLE_BINDING_NOT_VERIFIED"],
            "complete_four_layer_context": False,
            "execution_eligible": False,
            "real_orders_enabled": False,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(Console(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(
            base + "/api/v1/v4/layers?asof=2026-01-30&horizon=3"
        ) as response:
            payload = json.load(response)
            assert response.status == 200
        assert payload["complete_four_layer_context"] is False
        assert payload["blockers"] == ["L3_L2_STYLE_BINDING_NOT_VERIFIED"]
        assert calls == [("2026-01-30", 3)]
        for query in (
            "?unknown=1",
            "?horizon=2",
            "?horizon=abc",
            "?asof=2026-02-30",
            "?horizon=3&horizon=5",
        ):
            with pytest.raises(HTTPError) as error:
                urlopen(base + "/api/v1/v4/layers" + query)
            assert error.value.code == 400
        assert calls == [("2026-01-30", 3)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
