from __future__ import annotations

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.planner import ForwardIngestionPlanner
from forward_nautobot.integrations.forward.planner import ForwardIngestionRequest

from .test_client import _mock_transport


def test_planner_syncs_rows_with_diffsync():
    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        ),
        transport=_mock_transport(),
    )
    planner = ForwardIngestionPlanner(client)
    plan = planner.run(
        ForwardIngestionRequest(
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
            ),
            model_names=("devices",),
            fetch_all=False,
            limit=2,
        )
    )

    assert plan.source.count("devices") == 2
    assert plan.target.count("devices") == 2
    assert plan.diff_summary["create"] == 2
    assert plan.reports[0].query_reference == "forward_devices.nqe"
    assert plan.source_summary["model_counts"]["devices"] == 2
    assert plan.target_summary["planned_counts"]["devices"] == 2
