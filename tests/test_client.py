import json

import httpx

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.models import ForwardQuerySpec


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
            if payload.get("queryId") == "query-123":
                assert payload["commitId"] == "commit-abc"
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
            assert "query" in payload
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "fields": {
                                "name": "device-1",
                                "location": "Site A",
                                "vendor": "Vendor.CISCO",
                                "model": "N9K",
                                "device_type": "DeviceType.SWITCH",
                            }
                        },
                        {
                            "fields": {
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

    resolved = client.resolve_query_spec(
        ForwardQuerySpec(query_path="/queries/devices.nqe")
    )
    assert resolved.resolved_query_id == "query-123"

    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_path="/queries/devices.nqe"),
        fetch_all=True,
    )
    assert [row["id"] for row in rows] == ["r1", "r2"]
    assert client.get_latest_processed_snapshot_id("net-1") == "snap-2"
    assert client.get_snapshot_metrics("snap-2")["snapshotState"] == "processed"
