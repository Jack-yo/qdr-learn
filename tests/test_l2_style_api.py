

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
