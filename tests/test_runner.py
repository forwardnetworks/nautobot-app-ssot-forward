import json

import httpx

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.models import ForwardQuerySpec
from forward_nautobot.integrations.forward.models import ForwardSyncSpec
from forward_nautobot.integrations.forward.runner import ForwardSyncRunner

from .test_client import _mock_transport


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
            assert request.url.params.get("path") == "/queries/devices.nqe"
            return httpx.Response(
                200,
                json={
                    "queries": [
                        {
                            "path": "/queries/devices.nqe",
                            "queryId": "query-123",
                            "lastCommit": {"id": "commit-abc"},
                        }
                    ]
                },
            )
        if path == "/api/nqe":
            payload = json.loads(request.content.decode("utf-8"))
            calls["nqe_payloads"].append(payload)
            assert payload["queryId"] == "query-123"
            assert payload["commitId"] == "commit-abc"
            assert payload["parameters"] == {"limit": 2}
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
            query=ForwardQuerySpec(query_path="/queries/devices.nqe"),
            model_names=("locations", "devices"),
        )
    )
    assert report.row_count == 2
    assert report.snapshot_id == "snap-2"
    assert report.planned_models == ("locations", "devices")
    assert report.summary.startswith("preview 2 row(s)")


def test_runner_preview_uses_query_parameters_once():
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
                query_path="/queries/devices.nqe",
                parameters={"limit": 2},
            ),
            model_names=("locations", "devices"),
            limit=2,
        )
    )
    assert calls["query_lookups"] == 1
    assert calls["nqe_payloads"][0]["parameters"] == {"limit": 2}
    assert report.row_count == 2
