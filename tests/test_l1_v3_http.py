"""Loopback HTTP contract: V3 GET is offline and cannot train or archive."""
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
from urllib.error import HTTPError
import json

import pytest

from quant_research.web import Console,handler


def test_all_v3_browser_get_routes_are_read_only(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError("Read-only HTTP GET attempted market training or network")
    monkeypatch.setattr("quant_research.workflow.l1_v3.current_l1_v3",forbidden)
    monkeypatch.setattr("quant_research.workflow.l1_v3_pipeline.run_pipeline",forbidden)
    server=ThreadingHTTPServer(("127.0.0.1",0),handler(Console(tmp_path)))
    worker=Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        url="http://127.0.0.1:"+str(server.server_port)
        for endpoint,schema in [
            ("/api/v1/l1/v3/latest","qdr.l1.probability.v3"),
            ("/api/v1/l1/v3/overview","qdr.l1.probability.v3"),
            ("/api/v1/l1/v3/status","qdr.l1.v3.pipeline.status"),
            ("/api/v1/l1/v3/outcomes","qdr.l1.v3.outcomes"),
            ("/api/v1/l1/v3/history","qdr.l1.v3.history"),
        ]:
            with urlopen(url+endpoint,timeout=4) as response:
                assert response.status==200
                data=json.loads(response.read())
                assert data["schema"]==schema
                assert data["execution_eligible"] is False if "execution_eligible" in data else True
        with pytest.raises(HTTPError) as err:
            urlopen(url+"/api/v1/l1/v3/overview?archive=1",timeout=4)
        assert err.value.code==400
        assert json.loads(err.value.read())["code"]=="V3_QUERY_NOT_ALLOWED_READ_ONLY"
        assert not (tmp_path/"outputs"/"l1_v3_research").exists()
        assert not (tmp_path/"outputs"/"l1_v3_models").exists()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=4)
