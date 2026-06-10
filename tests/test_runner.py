from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.models import ForwardQuerySpec
from forward_nautobot.integrations.forward.models import ForwardSyncSpec
from forward_nautobot.integrations.forward.runner import ForwardSyncRunner

from .test_client import _mock_transport


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

