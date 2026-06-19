from __future__ import annotations

import json

import pytest

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    httpx = None

try:
    from forward_nautobot.integrations.forward.client import ForwardClient
    from forward_nautobot.integrations.forward.models import (
        ForwardConnectionSettings,
        ForwardQuerySpec,
        ForwardSyncSpec,
    )
    from forward_nautobot.integrations.forward.runner import ForwardSyncRunner

    from .test_client import _mock_transport
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    ForwardClient = None
    ForwardConnectionSettings = None
    ForwardQuerySpec = None
    ForwardSyncSpec = None
    ForwardSyncRunner = None
    _mock_transport = None


def _require_runner():
    if (
        httpx is None
        or ForwardClient is None
        or ForwardConnectionSettings is None
        or ForwardQuerySpec is None
        or ForwardSyncSpec is None
        or ForwardSyncRunner is None
        or _mock_transport is None
    ):
        pytest.skip("Forward runner tests require the full dependency set.")


def _counting_transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
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
        if path == "/api/snapshots/snap-2/metrics":
            return httpx.Response(200, json={"snapshotState": "processed"})
        if path == "/api/nqe/repos/org/commits/head/queries":
            calls["query_lookups"] += 1
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
            calls["nqe_payloads"].append(payload)
            assert payload["queryId"] == "query-123"
            assert payload["commitId"] == "commit-abc"
            assert payload["parameters"] == {"limit": 2}
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
                    "items": [
                        {"fields": {"id": "r1"}},
                        {"fields": {"id": "r2"}},
                    ],
                    "totalNumItems": 2,
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    return httpx.MockTransport(handler)


def test_runner_preview_report():
    _require_runner()
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=_mock_transport(),
    )
    runner = ForwardSyncRunner(client)
    report = runner.preview(
        ForwardSyncSpec(
            mode="preview",
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
            ),
            query=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
            model_names=("locations", "devices"),
        )
    )
    assert report.row_count == 2
    assert report.snapshot_id == "snap-2"
    assert report.planned_models == ("locations", "devices")
    assert report.summary.startswith("preview 2 row(s)")


def test_runner_preview_uses_query_parameters_once():
    _require_runner()
    calls = {"query_lookups": 0, "nqe_payloads": []}
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        transport=_counting_transport(calls),
    )
    runner = ForwardSyncRunner(client)
    report = runner.preview(
        ForwardSyncSpec(
            mode="preview",
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
                snapshot_id="snap-2",
            ),
            query=ForwardQuerySpec(
                query_path="/forward_nautobot_validation/forward_devices",
                parameters={"limit": 2},
            ),
            model_names=("locations", "devices"),
            limit=2,
        )
    )
    assert calls["query_lookups"] == 1
    assert calls["nqe_payloads"][0]["parameters"] == {"limit": 2}
    assert report.row_count == 2


def test_runner_preview_and_sync_reuse_query_resolution_cache():
    _require_runner()
    calls = {"query_lookups": 0, "nqe_payloads": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/networks/net-1/snapshots":
            return httpx.Response(200, json={"snapshots": []})
        if path == "/api/snapshots/snap-2/metrics":
            return httpx.Response(200, json={"snapshotState": "processed"})
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
            payload = json.loads(request.content.decode("utf-8"))
            calls["nqe_payloads"].append(payload)
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
    runner = ForwardSyncRunner(client)
    spec = ForwardSyncSpec(
        mode="preview",
        connection=ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
            snapshot_id="snap-2",
        ),
        query=ForwardQuerySpec(query_path="/forward_nautobot_validation/forward_devices"),
        model_names=("locations", "devices"),
    )

    preview_report = runner.preview(spec)
    sync_report = runner.sync(spec)

    assert preview_report.row_count == sync_report.row_count == 1
    assert calls["query_lookups"] == 1
    assert len(calls["nqe_payloads"]) == 2
    assert all(payload["queryId"] == "query-123" for payload in calls["nqe_payloads"])
