import json

import pytest

try:
    import httpx

    import forward_nautobot.integrations.forward.client as client_module
    from forward_nautobot.integrations.forward.client import ForwardClient
    from forward_nautobot.integrations.forward.exceptions import ForwardClientError
    from forward_nautobot.integrations.forward.models import (
        ForwardConnectionSettings,
        ForwardQuerySpec,
    )
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps

    class _HttpxStub:
        class Request:  # pragma: no cover - import-time placeholder only
            pass

        class Response:  # pragma: no cover - import-time placeholder only
            pass

        class MockTransport:  # pragma: no cover - import-time placeholder only
            pass

    httpx = _HttpxStub()
    ForwardClient = None
    client_module = None
    ForwardClientError = None
    ForwardConnectionSettings = None
    ForwardQuerySpec = None


def _require_client():
    if (
        ForwardClient is None
        or client_module is None
        or ForwardClientError is None
        or ForwardConnectionSettings is None
        or ForwardQuerySpec is None
    ):
        pytest.skip("Forward client tests require the full dependency set.")


def _mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks":
            return httpx.Response(200, json=[{"id": "net-1", "name": "Primary"}])
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(
                200,
                json={"id": "snap-2", "state": "processed"},
            )
        if path == "/api/networks/net-1/snapshots":
            return httpx.Response(
                200,
                json={
                    "snapshots": [
                        {
                            "id": "snap-1",
                            "state": "archived",
                            "createdAt": "2026-06-09T00:00:00Z",
                        },
                        {
                            "id": "snap-2",
                            "state": "processed",
                            "processedAt": "2026-06-10T00:00:00Z",
                        },
                    ]
                },
            )
        if path == "/api/nqe/repos/org/commits/head/queries":
            path_param = request.url.params.get("path")
            if path_param is not None:
                assert path_param == "/forward_nautobot_validation/forward_devices"
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        },
                        {
                            "path": "/forward_nautobot_validation/forward_locations",
                            "queryId": "query-456",
                            "lastCommit": {"id": "commit-def"},
                        },
                    ]
                },
            )
        if path == "/api/networks/net-1/nqe-executions":
            payload = json.loads(request.content.decode("utf-8"))
            if payload.get("queryId") == "query-123":
                assert payload["commitId"] == "commit-abc"
                return httpx.Response(
                    200,
                    json={
                        "executionKey": "execution-query-123",
                        "status": "COMPLETED",
                        "outcome": "OK",
                    },
                )
            if payload.get("queryId") == "query-456":
                assert payload["commitId"] == "commit-def"
                return httpx.Response(
                    200,
                    json={
                        "executionKey": "execution-query-456",
                        "status": "COMPLETED",
                        "outcome": "OK",
                    },
                )
            assert "query" in payload
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-inline",
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-query-123/result":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "fields": {
                                "id": "r1",
                                "name": "device-1",
                                "location": "Site A",
                                "vendor": "Vendor.CISCO",
                                "model": "N9K",
                                "device_type": "DeviceType.SWITCH",
                            }
                        },
                        {
                            "fields": {
                                "id": "r2",
                                "name": "device-2",
                                "location": "Site B",
                                "vendor": "Vendor.CISCO",
                                "model": "N9K",
                                "device_type": "DeviceType.SWITCH",
                            }
                        },
                    ],
                    "totalNumItems": 2,
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-query-456/result":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "fields": {
                                "id": "location-row",
                                "name": "SITE-A",
                                "city": "Austin",
                                "country": "US",
                            }
                        },
                    ],
                    "totalNumItems": 1,
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-inline/result":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "fields": {
                                "id": "inline-r1",
                                "name": "device-1",
                                "location": "Site A",
                                "vendor": "Vendor.CISCO",
                                "model": "N9K",
                                "device_type": "DeviceType.SWITCH",
                            }
                        },
                        {
                            "fields": {
                                "id": "inline-r2",
                                "name": "device-2",
                                "location": "Site B",
                                "vendor": "Vendor.CISCO",
                                "model": "N9K",
                                "device_type": "DeviceType.SWITCH",
                            }
                        },
                    ],
                    "totalNumItems": 2,
                },
            )
        if path == "/api/snapshots/snap-2/metrics":
            return httpx.Response(200, json={"snapshotState": "processed"})
        raise AssertionError(f"unexpected path: {path}")

    return httpx.MockTransport(handler)


def test_client_network_snapshot_and_query_flow():
    _require_client()
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=_mock_transport(),
    )

    networks = client.get_networks()
    assert networks[0]["label"] == "Primary (net-1)"

    snapshots = client.get_snapshots("net-1")
    assert snapshots[1]["label"].startswith("snap-2 | processed")


def test_httpx_client_uses_verify_and_trust_env_settings(monkeypatch):
    _require_client()
    captured = {}
    real_client = client_module.httpx.Client

    def _client_factory(*args, **kwargs):
        captured.update(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", _client_factory)

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            verify_tls=False,
        ),
        transport=_mock_transport(),
    )

    snapshots = client.get_networks()
    assert snapshots == [{"id": "net-1", "name": "Primary", "label": "Primary (net-1)"}]
    assert captured["verify"] is False
    assert captured["trust_env"] is True

    resolved = client.resolve_query_spec(
        ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices")
    )
    assert resolved.resolved_query_id == "query-123"

    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
        fetch_all=True,
    )
    assert [row["id"] for row in rows] == ["r1", "r2"]
    assert rows[0]["name"] == "device-1"
    assert client.get_latest_processed_snapshot_id("net-1") == "snap-2"
    assert client.get_snapshot_metrics("snap-2")["snapshotState"] == "processed"


def test_client_normalizes_query_path_when_resolving():
    _require_client()
    calls = {"lookup_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["lookup_calls"] += 1
            path_param = request.url.params.get("path")
            if path_param is not None:
                assert path_param == "/forward_nautobot_validation/forward_devices"
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        }
                    ]
                },
            )
        if path == "/api/networks/net-1/nqe-executions":
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-query-123",
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-query-123/result":
            return httpx.Response(200, json={"items": [], "totalNumItems": 0})
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(handler),
    )

    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_path="forward_nautobot_validation/forward_devices"),
        fetch_all=False,
    )

    assert rows == []
    assert calls["lookup_calls"] == 1


def test_client_caches_query_resolution_for_repeated_runs():
    _require_client()
    calls = {"snapshot_lookups": 0, "query_lookups": 0, "execution_submits": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            calls["snapshot_lookups"] += 1
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["query_lookups"] += 1
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        },
                        {
                            "path": "/forward_nautobot_validation/forward_locations",
                            "queryId": "query-456",
                            "lastCommit": {"id": "commit-def"},
                        },
                    ]
                },
            )
        if path == "/api/networks/net-1/nqe-executions":
            calls["execution_submits"] += 1
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-query-123",
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-query-123/result":
            return httpx.Response(
                200,
                json={
                    "items": [{"fields": {"id": "r1"}}],
                    "totalNumItems": 1,
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=httpx.MockTransport(handler),
    )

    spec = ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices")
    rows1 = client.run_nqe_query(query_spec=spec, fetch_all=False)
    rows2 = client.run_nqe_query(query_spec=spec, fetch_all=False)

    assert [row["id"] for row in rows1] == [row["id"] for row in rows2] == ["r1"]
    assert calls["snapshot_lookups"] == 0
    assert calls["query_lookups"] == 1
    assert calls["execution_submits"] == 2


def test_client_resolve_query_spec_reuses_repository_index_cache():
    _require_client()
    calls = {"query_lookups": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["query_lookups"] += 1
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(handler),
    )

    spec = ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices")
    resolved_1 = client.resolve_query_spec(spec)
    resolved_2 = client.resolve_query_spec(spec)

    assert resolved_1.resolved_query_id == "query-123"
    assert resolved_2.resolved_query_id == "query-123"
    assert calls["query_lookups"] == 1


def test_client_binds_multiple_query_paths_from_one_repository_index():
    _require_client()
    calls = {"query_lookups": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["query_lookups"] += 1
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-devices",
                            "lastCommit": {"id": "commit-abc"},
                        },
                        {
                            "path": "/forward_nautobot_validation/forward_locations",
                            "queryId": "query-locations",
                            "lastCommit": {"id": "commit-def"},
                        },
                    ]
                },
            )
        if path == "/api/networks/net-1/nqe-executions":
            payload = json.loads(request.content.decode("utf-8"))
            if payload.get("queryId") == "query-devices":
                return httpx.Response(
                    200,
                    json={
                        "executionKey": "execution-devices",
                        "status": "COMPLETED",
                        "outcome": "OK",
                    },
                )
            if payload.get("queryId") == "query-locations":
                return httpx.Response(
                    200,
                    json={
                        "executionKey": "execution-locations",
                        "status": "COMPLETED",
                        "outcome": "OK",
                    },
                )
            raise AssertionError(f"unexpected query payload: {payload}")
        if path == "/api/networks/net-1/nqe-executions/execution-devices/result":
            return httpx.Response(
                200,
                json={"items": [{"fields": {"id": "device-row"}}], "totalNumItems": 1},
            )
        if path == "/api/networks/net-1/nqe-executions/execution-locations/result":
            return httpx.Response(
                200,
                json={"items": [{"fields": {"id": "location-row"}}], "totalNumItems": 1},
            )
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=httpx.MockTransport(handler),
    )

    devices = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
        fetch_all=False,
    )
    locations = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_locations"),
        fetch_all=False,
    )

    assert [row["id"] for row in devices] == ["device-row"]
    assert [row["id"] for row in locations] == ["location-row"]
    assert calls["query_lookups"] == 1


def test_client_async_nqe_execution_flow(monkeypatch):
    _require_client()
    calls = {
        "query_lookups": 0,
        "execution_submits": 0,
        "execution_statuses": 0,
        "execution_results": 0,
    }
    sleep_calls: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["query_lookups"] += 1
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        }
                    ]
                },
            )
        if path == "/api/networks/net-1/nqe-executions":
            calls["execution_submits"] += 1
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["queryId"] == "query-123"
            assert payload["commitId"] == "commit-abc"
            assert "parameters" not in payload
            assert "options" not in payload
            assert request.url.params["snapshotId"] == "snap-2"
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-1",
                    "status": "SUBMITTED",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-1":
            calls["execution_statuses"] += 1
            if calls["execution_statuses"] == 1:
                return httpx.Response(200, json={"status": "EXECUTING"})
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-1/result":
            calls["execution_results"] += 1
            assert request.headers.get("accept") == client_module.NQE_ASYNC_RESULT_ACCEPT
            return httpx.Response(
                200,
                json={
                    "items": [{"fields": {"id": "r1"}}, {"fields": {"id": "r2"}}],
                    "totalNumItems": 2,
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=httpx.MockTransport(handler),
    )

    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
        fetch_all=True,
        limit=1,
        poll_interval_seconds=0.01,
    )

    assert rows == [{"id": "r1"}, {"id": "r2"}]
    assert calls["query_lookups"] == 1
    assert calls["execution_submits"] == 1
    assert calls["execution_statuses"] == 2
    assert calls["execution_results"] == 1
    assert sleep_calls == [0.01]


def test_client_async_nqe_execution_result_prefers_ndjson_payload(monkeypatch):
    _require_client()
    calls = {
        "execution_submits": 0,
        "execution_statuses": 0,
        "execution_results": 0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/networks/net-1/nqe-executions":
            calls["execution_submits"] += 1
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["queryId"] == "query-123"
            assert payload["commitId"] == "commit-abc"
            assert "parameters" not in payload
            assert "options" not in payload
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-ndjson",
                    "status": "SUBMITTED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-ndjson":
            calls["execution_statuses"] += 1
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-ndjson/result":
            calls["execution_results"] += 1
            assert request.headers.get("accept") == client_module.NQE_ASYNC_RESULT_ACCEPT
            return httpx.Response(
                200,
                text='{"fields": {"id": "r1", "name": "device-1"}}\n'
                '{"fields": {"id": "r2", "name": "device-2"}}\n',
                headers={"content-type": "application/x-ndjson"},
            )
        if path == "/api/nqe/repos/org/commits/head/queries":
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(
        client_module.time,
        "sleep",
        lambda _seconds: pytest.fail("async polling should not run for completed execution"),
    )

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=httpx.MockTransport(handler),
    )

    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
        fetch_all=False,
    )

    assert rows == [{"id": "r1", "name": "device-1"}, {"id": "r2", "name": "device-2"}]
    assert calls["execution_submits"] == 1
    assert calls["execution_statuses"] == 1
    assert calls["execution_results"] == 1


def test_client_respects_request_min_interval(monkeypatch):
    _require_client()
    slept = []
    timestamps = iter([10.0, 10.1, 10.2])

    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(timestamps))
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: slept.append(seconds))

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            request_min_interval_seconds=0.5,
        ),
        transport=_mock_transport(),
    )

    client.get_networks()
    client.get_networks()

    assert len(slept) == 1
    assert abs(slept[0] - 0.4) < 1e-9


def test_client_caches_snapshot_listing_and_latest_processed_snapshot():
    _require_client()
    calls = {"snapshot_listings": 0, "latest_processed": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots":
            calls["snapshot_listings"] += 1
            return httpx.Response(
                200,
                json={
                    "snapshots": [
                        {
                            "id": "snap-1",
                            "state": "archived",
                            "createdAt": "2026-06-09T00:00:00Z",
                        }
                    ]
                },
            )
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            calls["latest_processed"] += 1
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(handler),
    )

    snapshots_1 = client.get_snapshots("net-1")
    snapshots_2 = client.get_snapshots("net-1")
    latest_1 = client.get_latest_processed_snapshot_id("net-1")
    latest_2 = client.get_latest_processed_snapshot_id("net-1")

    assert (
        snapshots_1
        == snapshots_2
        == [
            {
                "id": "snap-1",
                "state": "archived",
                "created_at": "2026-06-09T00:00:00Z",
                "processed_at": "",
                "label": "snap-1 | archived | 2026-06-09T00:00:00Z",
            }
        ]
    )
    assert latest_1 == latest_2 == "snap-2"
    assert calls["snapshot_listings"] == 1
    assert calls["latest_processed"] == 1


def test_client_retries_transient_http_errors_before_succeeding(monkeypatch):
    _require_client()
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: slept.append(seconds))
    calls = {"nqe_runs": 0, "execution_results": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/networks/net-1/nqe-executions":
            calls["nqe_runs"] += 1
            if calls["nqe_runs"] == 1:
                return httpx.Response(503, text="temporarily unavailable")
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["query"] == "select { id: string }"
            assert "parameters" not in payload
            return httpx.Response(
                200,
                json={
                    "executionKey": "execution-inline",
                    "status": "COMPLETED",
                    "outcome": "OK",
                },
            )
        if path == "/api/networks/net-1/nqe-executions/execution-inline/result":
            calls["execution_results"] += 1
            return httpx.Response(
                200,
                json={
                    "items": [{"fields": {"id": "r1"}}],
                    "totalNumItems": 1,
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            retries=1,
        ),
        transport=httpx.MockTransport(handler),
    )

    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_text="select { id: string }"),
        fetch_all=False,
    )

    assert rows == [{"id": "r1"}]
    assert calls["nqe_runs"] == 2
    assert calls["execution_results"] == 1
    # The 503 retry backed off once before the successful attempt.
    assert len(slept) == 1
    assert slept[0] > 0


def test_client_honors_retry_after_header(monkeypatch):
    _require_client()
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: slept.append(seconds))
    calls = {"nqe_runs": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/networks/net-1/nqe-executions":
            calls["nqe_runs"] += 1
            if calls["nqe_runs"] == 1:
                return httpx.Response(429, text="slow down", headers={"Retry-After": "7"})
            return httpx.Response(
                200, json={"executionKey": "e", "status": "COMPLETED", "outcome": "OK"}
            )
        if path == "/api/networks/net-1/nqe-executions/e/result":
            return httpx.Response(
                200, json={"items": [{"fields": {"id": "r1"}}], "totalNumItems": 1}
            )
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            retries=1,
        ),
        transport=httpx.MockTransport(handler),
    )
    client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_text="select { id: string }"), fetch_all=False
    )
    # Retry-After: 7 is honored verbatim (not the exponential default).
    assert slept == [7.0]


def test_client_rejects_auth_failures_without_retry():
    _require_client()
    calls = {"nqe_runs": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots/latestProcessed":
            return httpx.Response(200, json={"id": "snap-2", "state": "processed"})
        if path == "/api/networks/net-1/nqe-executions":
            calls["nqe_runs"] += 1
            return httpx.Response(401, text="unauthorized")
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            retries=2,
        ),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ForwardClientError, match="HTTP 401"):
        client.run_nqe_query(
            query_spec=ForwardQuerySpec(query_text="select { id: string }"),
            fetch_all=False,
        )

    assert calls["nqe_runs"] == 1


def test_request_nqe_execution_sends_sort_keys(monkeypatch):
    _require_client()
    captured_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/nqe-executions":
            captured_payload.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"executionKey": "exec-1", "status": "SUBMITTED"})
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-1",
        ),
        transport=httpx.MockTransport(handler),
    )
    client.request_nqe_execution(
        query_spec=ForwardQuerySpec(
            query_text="foreach device in network.devices select { name: device.name }",
            sort_keys=("name",),
        ),
        network_id="net-1",
        snapshot_id="snap-1",
    )
    assert captured_payload.get("sortKeys") == [{"columnName": "name", "order": "ASC"}]
    assert "parameters" not in captured_payload


def test_request_nqe_execution_omits_sort_keys_when_empty(monkeypatch):
    _require_client()
    captured_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/networks/net-1/nqe-executions":
            captured_payload.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(200, json={"executionKey": "exec-2", "status": "SUBMITTED"})
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-1",
        ),
        transport=httpx.MockTransport(handler),
    )
    client.request_nqe_execution(
        query_spec=ForwardQuerySpec(
            query_text="foreach device in network.devices select { name: device.name }"
        ),
        network_id="net-1",
        snapshot_id="snap-1",
    )
    assert "sortKeys" not in captured_payload
