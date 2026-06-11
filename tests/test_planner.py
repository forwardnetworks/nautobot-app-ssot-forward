from __future__ import annotations

import forward_nautobot.integrations.forward.adapters as adapters

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter
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
    assert plan.write_summary["create"] == 2
    assert plan.diff_summary["create"] == 2
    assert plan.reports[0].query_reference == "forward_devices.nqe"
    assert plan.reports[0].query_contract_version == "v1"
    assert plan.source_summary["model_counts"]["devices"] == 2
    assert plan.target_summary["planned_counts"]["devices"] == 2
    assert plan.write_plan.slice_policies["devices"]["missing_row_policy"] == "mark_inactive"


def test_planner_loads_existing_target_state_before_diff(monkeypatch):
    location = adapters.ForwardLocation(name="SITE-ALPHA", city="Austin", country="US")

    class _FakeManager:
        def all(self):
            return [location]

    class _FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[(app_label, model_name)]

    models = {
        ("dcim", "location"): type("LocationModel", (), {"objects": _FakeManager()}),
    }
    monkeypatch.setattr(adapters, "django_apps", _FakeApps(models))

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
    rows = [
        {
            "name": "SITE-ALPHA",
            "city": "Austin",
            "country": "US",
        }
    ]
    monkeypatch.setattr(
        ForwardClient,
        "run_nqe_query",
        lambda self, **_kwargs: rows,
    )

    plan = planner.run(
        ForwardIngestionRequest(
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
            ),
            model_names=("locations",),
            fetch_all=False,
            limit=1,
        )
    )

    assert plan.target_summary["loaded_counts"]["locations"] == 1
    assert plan.target.count("locations") == 1
