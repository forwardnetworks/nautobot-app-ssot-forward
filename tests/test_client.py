import json

import pytest

try:
    import httpx

    import forward_nautobot.integrations.forward.client as client_module
    from forward_nautobot.integrations.forward.client import ForwardClient
    from forward_nautobot.integrations.forward.exceptions import (
        ForwardClientError,
        ForwardConfigurationError,
    )
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
            # Forward always sends orgId on a network; confirmed against a live
            # account. The earlier fixture omitting it was the outlier.
            return httpx.Response(200, json=[{"id": "net-1", "name": "Primary", "orgId": "org-1"}])
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
                            "id": "r1",
                            "name": "device-1",
                            "location": "Site A",
                            "vendor": "Vendor.CISCO",
                            "model": "N9K",
                            "platform": "CISCO_NXOS",
                        },
                        {
                            "id": "r2",
                            "name": "device-2",
                            "location": "Site B",
                            "vendor": "Vendor.CISCO",
                            "model": "N9K",
                            "platform": "CISCO_NXOS",
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
                            "id": "location-row",
                            "name": "SITE-A",
                            "city": "Austin",
                            "country": "US",
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
                            "id": "inline-r1",
                            "name": "device-1",
                            "location": "Site A",
                            "vendor": "Vendor.CISCO",
                            "model": "N9K",
                            "platform": "CISCO_NXOS",
                        },
                        {
                            "id": "inline-r2",
                            "name": "device-2",
                            "location": "Site B",
                            "vendor": "Vendor.CISCO",
                            "model": "N9K",
                            "platform": "CISCO_NXOS",
                        },
                    ],
                    "totalNumItems": 2,
                },
            )
        if path.startswith("/api/snapshots/") and path.endswith("/metrics"):
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
                    "items": [{"id": "r1"}],
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
                json={"items": [{"id": "device-row"}], "totalNumItems": 1},
            )
        if path == "/api/networks/net-1/nqe-executions/execution-locations/result":
            return httpx.Response(
                200,
                json={"items": [{"id": "location-row"}], "totalNumItems": 1},
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
            query_spec=ForwardQuerySpec(query_id="query-123"),
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
            query_id="q-1",
            resolved_query_id="q-1",
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
            query_id="q-2",
            resolved_query_id="q-2",
        ),
        network_id="net-1",
        snapshot_id="snap-1",
    )
    assert "sortKeys" not in captured_payload
    assert captured_payload["queryId"] == "q-2"
    assert "query" not in captured_payload


def test_run_nqe_diff_sends_only_supported_identity_and_page_options():
    _require_client()
    captured_payload: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/nqe-diffs/snap-before/snap-after"
        captured_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"rows": [], "totalNumRows": 0})

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(handler),
    )

    assert (
        client.run_nqe_diff(
            query_id="query-123",
            commit_id="commit-abc",
            before_snapshot_id="snap-before",
            after_snapshot_id="snap-after",
            limit=25,
            fetch_all=False,
        )
        == []
    )
    # Identity and paging only: no parameters, no sortKeys. Forward's diff
    # endpoint accepts neither.
    assert captured_payload == {
        "queryId": "query-123",
        "commitId": "commit-abc",
        "options": {"limit": 25, "offset": 0},
    }


def test_run_nqe_diff_rejects_a_non_zero_offset():
    """The SDK pages diffs internally and starts at zero.

    No production caller sets a diff offset, so this fails loudly rather than
    accepting a value it would silently ignore.
    """
    _require_client()
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"rows": []})),
    )

    with pytest.raises(ForwardConfigurationError):
        client.run_nqe_diff(
            query_id="query-123",
            before_snapshot_id="snap-before",
            after_snapshot_id="snap-after",
            offset=5,
        )


def test_forward_query_spec_accepts_exactly_one_inline_query_reference():
    _require_client()
    spec = ForwardQuerySpec(
        query_text="foreach device in network.devices select { name: device.name }"
    )

    assert spec.execution_mode == "query"
    assert spec.reference == "<inline query>"
    with pytest.raises(ValueError, match="Exactly one"):
        ForwardQuerySpec(
            query_text="foreach device in network.devices select { name: device.name }",
            query_id="query-123",
        )


def test_client_runs_inline_nqe_through_async_execution():
    _require_client()
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=_mock_transport(),
    )

    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(
            query_text="@query f() = foreach x in [1] select { id: toString(x) };"
        ),
        fetch_all=False,
    )

    assert [row["id"] for row in rows] == ["inline-r1", "inline-r2"]


def test_counters_track_attempts_retries_and_429():
    """Transport-level telemetry is accumulated on the client for the support bundle."""
    _require_client()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/networks":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={"error": "slow down"})
            return httpx.Response(200, json=[{"id": "net-1", "name": "n", "orgId": "org-1"}])
        raise AssertionError(f"unexpected path: {request.url.path}")

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
    client.get_networks()
    usage = client.counters.as_dict()
    assert usage["http_attempts"] == 2  # one 429, one success
    assert usage["http_transient"] == 1
    assert usage["http_429"] == 1
    assert usage["http_retries"] == 1


def test_counters_count_nqe_query_calls():
    _require_client()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots":
            return httpx.Response(200, json={"snapshots": [{"id": "snap-1", "state": "PROCESSED"}]})
        if path == "/api/networks/net-1/nqe-executions":
            return httpx.Response(
                200,
                json={"executionKey": "exec-1", "status": "COMPLETED", "outcome": "OK"},
            )
        if path == "/api/networks/net-1/nqe-executions/exec-1/result":
            return httpx.Response(200, json={"items": [], "totalNumItems": 0})
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
    client.run_nqe_query(
        query_spec=ForwardQuerySpec(
            query_id="query-123",
            resolved_query_id="query-123",
        ),
        fetch_all=False,
    )
    assert client.counters.as_dict()["nqe_query_calls"] == 1


def test_client_fetches_concrete_committed_query_source():
    _require_client()
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, str(request.url.params)))
        # The SDK resolves head to a concrete commit before asking for source,
        # because a listing at head omits it.
        if request.url.path == "/api/nqe/repos/org/commits/head":
            return httpx.Response(200, json={"id": "commit-xyz"})
        if request.url.path == "/api/nqe/repos/org/commits/commit-xyz/queries":
            assert request.url.params["path"] == ("/forward_nautobot_validation/forward_devices")
            assert request.url.params["with"] == "sourceCode"
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/forward_nautobot_validation/forward_devices",
                            "queryId": "query-123",
                            "sourceCode": "@query f() = foreach x in [1] select x;",
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = ForwardClient(
        ForwardConnectionSettings(base_url="https://fwd.example", network_id="net-1"),
        transport=httpx.MockTransport(handler),
    )

    query = client.get_committed_nqe_query(
        query_path="/forward_nautobot_validation/forward_devices",
        require_source_code=True,
    )

    assert query["queryId"] == "query-123"
    assert query["sourceCode"].startswith("@query")
    # Head is resolved to a concrete commit, then source is asked for there.
    # A listing at head omits source, so asking head directly returns nothing.
    assert [path for path, _ in calls] == [
        "/api/nqe/repos/org/commits/head",
        "/api/nqe/repos/org/commits/commit-xyz/queries",
    ]


def test_client_uses_org_nqe_change_and_commit_contracts():
    _require_client()
    actions: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/nqe/queries/query-123/history":
            return httpx.Response(200, json={"commits": [{"id": "commit-abc"}]})
        if path == "/api/users/current/nqe/changes":
            action = request.url.params["action"]
            actions.append(action)
            if action == "addDir":
                assert request.url.params["path"] == "/forward_nautobot_validation/"
                assert not request.content
                return httpx.Response(204)
            assert request.url.params["path"].startswith("/forward_nautobot_validation/")
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["sourceCode"].startswith("@query")
            if action == "editQuery":
                assert payload["basis"] == {
                    "queryId": "query-123",
                    "commitId": "commit-abc",
                }
            return httpx.Response(204)
        if path == "/api/nqe/repos/org/commits":
            actions.append("commit")
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["paths"] == [
                "/forward_nautobot_validation/forward_devices",
                "/forward_nautobot_validation/forward_locations",
            ]
            assert payload["accessSettings"] == []
            assert payload["message"] == {"title": "Publish queries", "body": "details"}
            return httpx.Response(204)
        if path == "/api/nqe/repos/org/commits/head":
            return httpx.Response(200, json={"id": "commit-new"})
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(base_url="https://fwd.example", network_id="net-1"),
        transport=httpx.MockTransport(handler),
    )

    assert client.get_nqe_query_history("query-123") == [{"id": "commit-abc"}]
    client.add_org_nqe_directory(directory_path="/forward_nautobot_validation")
    client.add_org_nqe_query(
        query_path="/forward_nautobot_validation/forward_locations",
        source_code="@query f() = foreach x in [1] select x;",
    )
    client.edit_org_nqe_query(
        query_path="/forward_nautobot_validation/forward_devices",
        source_code="@query f() = foreach x in [2] select x;",
        query_id="query-123",
        commit_id="commit-abc",
    )
    commit_id = client.commit_org_nqe_queries(
        query_paths=[
            "/forward_nautobot_validation/forward_devices",
            "/forward_nautobot_validation/forward_locations",
        ],
        message="Publish queries\ndetails",
    )

    assert commit_id == "commit-new"
    assert actions == ["addDir", "addQuery", "editQuery", "commit"]


def test_client_uses_snapshot_aware_nqe_commit_dry_run_and_exact_discard():
    _require_client()
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/nqe/repos/org/commits":
            assert request.method == "POST"
            assert dict(request.url.params) == {
                "dryRun": "true",
                "snapshotId": "snap-current",
            }
            assert json.loads(request.content.decode("utf-8")) == {
                "paths": ["/forward_nautobot_validation/forward_devices"],
                "accessSettings": [],
            }
            calls.append(("dry-run", "snap-current"))
            return httpx.Response(
                200,
                json={
                    "newErrors": {},
                    "uses": [],
                    "unauthorizedQueryChanges": [],
                    "unauthorizedAccessSettingChanges": [],
                },
            )
        if path == "/api/users/current/nqe/changes" and request.method == "GET":
            calls.append(("changes", ""))
            return httpx.Response(200, json={"changes": [{"type": "QUERY_ADD", "path": "/q"}]})
        if path == "/api/users/current/nqe/changes" and request.method == "DELETE":
            assert request.url.params["path"] == "/forward_nautobot_validation/forward_devices"
            calls.append(("discard", request.url.params["path"]))
            return httpx.Response(204)
        raise AssertionError(f"unexpected path: {path}")

    client = ForwardClient(
        ForwardConnectionSettings(base_url="https://fwd.example", network_id="net-1"),
        transport=httpx.MockTransport(handler),
    )

    assert client.get_org_nqe_draft_changes() == [{"type": "QUERY_ADD", "path": "/q"}]
    result = client.dry_run_org_nqe_queries(
        query_paths=["/forward_nautobot_validation/forward_devices"],
        snapshot_id="snap-current",
    )
    client.discard_org_nqe_draft_change(path="/forward_nautobot_validation/forward_devices")

    assert result["newErrors"] == {}
    assert calls == [
        ("changes", ""),
        ("dry-run", "snap-current"),
        ("discard", "/forward_nautobot_validation/forward_devices"),
    ]


def _snapshot_listing() -> dict:
    return {
        "snapshots": [
            {"id": "snap-1", "state": "archived", "createdAt": "2026-06-09T00:00:00Z"},
            {"id": "snap-2", "state": "PROCESSED", "processedAt": "2026-06-10T00:00:00Z"},
        ]
    }


def test_client_async_nqe_execution_returns_rows_without_polling_a_finished_run():
    """A submit response that is already terminal costs no status request."""
    _require_client()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path == "/api/networks/net-1/nqe-executions":
            return httpx.Response(
                200, json={"executionKey": "ek-1", "status": "COMPLETED", "outcome": "OK"}
            )
        if path == "/api/networks/net-1/nqe-executions/ek-1/result":
            return httpx.Response(
                200, json={"items": [{"id": "r1"}, {"id": "r2"}], "totalNumItems": 2}
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
    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(query_id="query-123"), network_id="net-1", fetch_all=True
    )
    assert rows == [{"id": "r1"}, {"id": "r2"}]
    assert not [p for p in seen if p.endswith("/ek-1")], "a finished run was polled anyway"


def test_client_async_nqe_result_negotiates_ndjson_and_parses_it():
    """The streaming result path asks for ndjson and reads it line by line."""
    _require_client()
    accepts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/nqe-executions":
            return httpx.Response(
                200, json={"executionKey": "ek-1", "status": "COMPLETED", "outcome": "OK"}
            )
        if path == "/api/networks/net-1/nqe-executions/ek-1/result":
            accepts.append(request.headers.get("accept", ""))
            return httpx.Response(
                200,
                text='{"id": "r1", "name": "device-1"}\n{"id": "r2", "name": "device-2"}\n',
                headers={"content-type": "application/x-ndjson"},
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
    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(query_id="query-123"), network_id="net-1", fetch_all=True
    )
    assert rows == [
        {"id": "r1", "name": "device-1"},
        {"id": "r2", "name": "device-2"},
    ]
    assert accepts and "ndjson" in accepts[0]


def test_request_min_interval_becomes_a_rate_limit_on_the_sdk_client():
    """Pacing is the SDK's now; the plugin only has to configure it.

    ``request_min_interval_seconds`` is a minimum gap between requests, which
    the SDK expresses as requests per minute.
    """
    _require_client()
    paced = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            request_min_interval_seconds=0.5,
        )
    )
    assert paced._rate_limit() == 120

    unpaced = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        )
    )
    assert unpaced._rate_limit() == "auto"


def test_client_caches_snapshot_listing_and_resolution():
    """Snapshots are immutable within a run, so one listing serves the run.

    The planner resolves a snapshot once per slice across a thread pool, so a
    cache miss here would cost a request per slice.
    """
    _require_client()
    calls = {"listings": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/networks/net-1/snapshots":
            calls["listings"] += 1
            return httpx.Response(200, json=_snapshot_listing())
        raise AssertionError(f"unexpected path: {request.url.path}")

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=httpx.MockTransport(handler),
    )
    assert client.get_snapshots("net-1") == client.get_snapshots("net-1")
    first = client.resolve_snapshot_id("net-1", "latestProcessed")
    second = client.resolve_snapshot_id("net-1", "latestProcessed")
    assert first == second == "snap-2"
    assert calls["listings"] == 2, "listing and resolution should each be cached once"


def test_client_retries_a_transient_error_then_succeeds():
    """Retry is the SDK's, but it must still be reached through this client."""
    _require_client()
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/networks/net-1/snapshots":
            attempts["n"] += 1
            if attempts["n"] == 1:
                return httpx.Response(503, json={"message": "try again"})
            return httpx.Response(200, json=_snapshot_listing())
        raise AssertionError(f"unexpected path: {request.url.path}")

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
    snapshots = client.get_snapshots("net-1")
    assert [row["id"] for row in snapshots] == ["snap-1", "snap-2"]
    assert attempts["n"] == 2


def test_client_surfaces_a_non_transient_error_without_retrying():
    """A 401 is not retried, and reaches callers as the plugin's error type."""
    _require_client()
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(401, json={"message": "bad credentials"})

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            retries=3,
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ForwardClientError):
        client.get_snapshots("net-1")
    assert attempts["n"] == 1
