from __future__ import annotations

import forward_nautobot.integrations.forward.adapters as adapters
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.models import ForwardConnectionProfileRecord

try:
    from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter
    from forward_nautobot.integrations.forward.client import ForwardClient
    from forward_nautobot.integrations.forward.planner import (
        ForwardIngestionPlanner,
        ForwardIngestionRequest,
    )

    from .test_client import _mock_transport
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    ForwardClient = None
    NautobotTargetAdapter = None
    ForwardIngestionPlanner = None
    ForwardIngestionRequest = None
    _mock_transport = None


def _require_planner():
    if (
        ForwardClient is None
        or NautobotTargetAdapter is None
        or ForwardIngestionPlanner is None
        or ForwardIngestionRequest is None
        or _mock_transport is None
    ):
        import pytest

        pytest.skip("Forward planner tests require the full dependency set.")


def _require_target_tables(*model_names: str):
    table_by_model = {
        "locations": "dcim_location",
        "platforms": "dcim_platform",
        "device_types": "dcim_devicetype",
        "devices": "dcim_device",
        "interfaces": "dcim_interface",
    }
    requested = [table_by_model[model] for model in model_names if model in table_by_model]
    if not requested:
        return

    try:
        from django.db import connection
    except ModuleNotFoundError:
        import pytest

        pytest.skip("Django is not installed.")

    try:
        existing_tables = set(connection.introspection.table_names())
    except Exception:
        return

    missing = [name for name in requested if name not in existing_tables]
    if missing:
        return


def test_planner_syncs_rows_with_diffsync():
    _require_planner()
    _require_target_tables("devices")
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
    assert plan.target.count("devices") == 0
    assert plan.write_summary["create"] == 2
    assert plan.diff_summary["create"] == 2
    assert plan.reports[0].query_reference == "forward_devices.nqe"
    assert plan.reports[0].query_contract_version == "v1"
    assert plan.source_summary["model_counts"]["devices"] == 2
    assert plan.target_summary["planned_counts"]["devices"] == 0
    assert plan.write_plan.slice_policies["devices"]["missing_row_policy"] == "mark_inactive"


def test_planner_loads_existing_target_state_before_diff(monkeypatch):
    _require_planner()
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


def test_planner_uses_diff_rows_for_query_id_backed_slices(monkeypatch):
    _require_planner()
    _require_target_tables("devices")
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

    diff_rows = [
        {
            "type": "updated",
            "before": {
                "name": "device-1",
                "location": "Site A",
                "vendor": "Vendor.CISCO",
                "model": "N9K",
                "device_type": "DeviceType.SWITCH",
            },
            "after": {
                "name": "device-1",
                "location": "Site B",
                "vendor": "Vendor.CISCO",
                "model": "N9K",
                "device_type": "DeviceType.SWITCH",
            },
        },
        {
            "type": "deleted",
            "before": {
                "name": "device-2",
                "location": "Site B",
                "vendor": "Vendor.CISCO",
                "model": "N9K",
                "device_type": "DeviceType.SWITCH",
            },
            "after": {},
        },
    ]

    def _run_nqe_diff(self, **kwargs):
        assert kwargs["before_snapshot_id"] == "snap-1"
        assert kwargs["after_snapshot_id"] == "snap-2"
        assert kwargs["query_id"] == "query-123"
        return diff_rows

    def _run_nqe_query(self, **kwargs):
        raise AssertionError("run_nqe_query should not be used when diff mode is available")

    monkeypatch.setattr(ForwardClient, "run_nqe_diff", _run_nqe_diff)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _run_nqe_query)

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
            connection_profile=ForwardConnectionProfileRecord(
                name="primary",
                network_id="net-1",
                last_snapshot_id="snap-1",
            ),
        )
    )

    assert plan.reports[0].query_mode == "bundled_nqe_query_id_diff"
    assert plan.write_plan.delta_mode is True
    assert plan.write_plan.delta_models == ("devices",)
    assert plan.write_summary["update"] == 1
    assert plan.write_summary["deleted"] == 1
    assert [operation.action for operation in plan.write_plan.operations] == [
        "update",
        "delete",
    ]
    assert plan.diff_detail["mode"] == "delta"
    assert plan.diff_detail["slices"]["devices"]["mode"] == "delta"


def test_planner_passes_dependent_scope_parameters(monkeypatch):
    _require_planner()
    _require_target_tables("locations", "devices", "interfaces")
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
    calls: list[tuple[str, dict[str, object]]] = []

    def _resolve_query_spec(self, query_spec):
        reference = query_spec.reference
        if reference.endswith("/forward_locations"):
            return query_spec.with_query_id("query-locations", "commit-abc")
        if reference.endswith("/forward_devices"):
            return query_spec.with_query_id("query-devices", "commit-abc")
        if reference.endswith("/forward_interfaces"):
            return query_spec.with_query_id("query-interfaces", "commit-abc")
        raise AssertionError(f"unexpected query reference: {reference}")

    def _run_nqe_query(self, **kwargs):
        query_spec = kwargs["query_spec"]
        calls.append((query_spec.reference, dict(query_spec.parameters)))
        if query_spec.reference.endswith("/forward_locations"):
            return [
                {
                    "name": "SITE-ALPHA",
                    "city": "Austin",
                    "country": "US",
                }
            ]
        if query_spec.reference.endswith("/forward_devices"):
            assert query_spec.parameters == {"forward_location_names": ["SITE-ALPHA"]}
            return [
                {
                    "name": "device-1",
                    "location": "SITE-ALPHA",
                    "vendor": "Vendor.CISCO",
                    "model": "N9K",
                    "device_type": "DeviceType.SWITCH",
                }
            ]
        if query_spec.reference.endswith("/forward_interfaces"):
            assert query_spec.parameters == {"forward_device_names": ["device-1"]}
            return [
                {
                    "device": "device-1",
                    "name": "eth0",
                    "type": "1000base-t",
                    "lag": "",
                    "mode": "",
                    "untagged_vlan": None,
                    "enabled": True,
                    "mtu": 1500,
                    "description": "",
                    "speed": 1000000000,
                }
            ]
        raise AssertionError(f"unexpected query reference: {query_spec.reference}")

    monkeypatch.setattr(ForwardClient, "resolve_query_spec", _resolve_query_spec)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _run_nqe_query)
    monkeypatch.setattr(
        ForwardClient,
        "resolve_snapshot_id",
        lambda self, network_id, snapshot_id: "snap-2",
    )

    plan = planner.run(
        ForwardIngestionRequest(
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
            ),
            model_names=("locations", "devices", "interfaces"),
            fetch_all=False,
            limit=1,
        )
    )

    assert plan.reports[0].query_reference == "forward_locations.nqe"
    assert calls[0][1] == {}
    assert calls[1][1] == {"forward_location_names": ["SITE-ALPHA"]}
    assert calls[2][1] == {"forward_device_names": ["device-1"]}


def test_planner_scopes_platform_and_device_type_queries_by_location(monkeypatch):
    _require_planner()
    _require_target_tables("locations", "platforms", "device_types", "devices")
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
    calls: list[tuple[str, dict[str, object]]] = []

    def _resolve_query_spec(self, query_spec):
        reference = query_spec.reference
        if reference.endswith("/forward_locations"):
            return query_spec.with_query_id("query-locations", "commit-abc")
        if reference.endswith("/forward_platforms"):
            return query_spec.with_query_id("query-platforms", "commit-abc")
        if reference.endswith("/forward_device_types"):
            return query_spec.with_query_id("query-device-types", "commit-abc")
        if reference.endswith("/forward_devices"):
            return query_spec.with_query_id("query-devices", "commit-abc")
        raise AssertionError(f"unexpected query reference: {reference}")

    def _run_nqe_query(self, **kwargs):
        query_spec = kwargs["query_spec"]
        calls.append((query_spec.reference, dict(query_spec.parameters)))
        if query_spec.reference.endswith("/forward_locations"):
            return [
                {
                    "name": "SITE-ALPHA",
                    "city": "Austin",
                    "country": "US",
                }
            ]
        if query_spec.reference.endswith("/forward_platforms"):
            assert query_spec.parameters == {"forward_location_names": ["SITE-ALPHA"]}
            return [
                {
                    "name": "NX-9000",
                    "manufacturer": "Cisco",
                    "device_type": "NX-9000",
                }
            ]
        if query_spec.reference.endswith("/forward_device_types"):
            assert query_spec.parameters == {"forward_location_names": ["SITE-ALPHA"]}
            return [
                {
                    "name": "NX-9000",
                    "color": "9e9e9e",
                }
            ]
        if query_spec.reference.endswith("/forward_devices"):
            assert query_spec.parameters == {"forward_location_names": ["SITE-ALPHA"]}
            return [
                {
                    "name": "device-1",
                    "location": "SITE-ALPHA",
                    "vendor": "Vendor.CISCO",
                    "model": "N9K",
                    "device_type": "DeviceType.SWITCH",
                }
            ]
        raise AssertionError(f"unexpected query reference: {query_spec.reference}")

    monkeypatch.setattr(ForwardClient, "resolve_query_spec", _resolve_query_spec)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _run_nqe_query)
    monkeypatch.setattr(
        ForwardClient,
        "resolve_snapshot_id",
        lambda self, network_id, snapshot_id: "snap-2",
    )

    plan = planner.run(
        ForwardIngestionRequest(
            connection=ForwardConnectionSettings(
                base_url="https://fwd.example",
                username="alice",
                password="secret",
                network_id="net-1",
            ),
            model_names=("locations", "platforms", "device_types", "devices"),
            fetch_all=False,
            limit=1,
        )
    )

    assert [report.query_reference for report in plan.reports] == [
        "forward_locations.nqe",
        "forward_platforms.nqe",
        "forward_device_types.nqe",
        "forward_devices.nqe",
    ]
    assert calls[0][1] == {}
    assert calls[1][1] == {"forward_location_names": ["SITE-ALPHA"]}
    assert calls[2][1] == {"forward_location_names": ["SITE-ALPHA"]}
    assert calls[3][1] == {"forward_location_names": ["SITE-ALPHA"]}


def test_planner_reuses_loaded_target_state_for_each_slice(monkeypatch):
    _require_planner()
    _require_target_tables("locations", "devices")
    load_calls = {"count": 0}
    run_calls = {"count": 0}
    original_load = NautobotTargetAdapter.load

    def _tracked_load(self):
        load_calls["count"] += 1
        return original_load(self)

    def _resolve_query_spec(self, query_spec):
        return query_spec.with_query_id("query-123", "commit-abc")

    def _run_nqe_query(self, **kwargs):
        run_calls["count"] += 1
        if run_calls["count"] == 1:
            return [
                {
                    "name": "SITE-ALPHA",
                    "city": "Austin",
                    "country": "US",
                }
            ]
        if run_calls["count"] == 2:
            return [
                {
                    "name": "device-1",
                    "location": "SITE-ALPHA",
                    "vendor": "Vendor.CISCO",
                    "model": "N9K",
                    "device_type": "DeviceType.SWITCH",
                }
            ]
        raise AssertionError(f"unexpected query call: {run_calls['count']}")

    monkeypatch.setattr(NautobotTargetAdapter, "load", _tracked_load)
    monkeypatch.setattr(ForwardClient, "resolve_query_spec", _resolve_query_spec)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _run_nqe_query)
    monkeypatch.setattr(
        adapters.ForwardSourceAdapter,
        "sync_to",
        lambda self, target: (_ for _ in ()).throw(
            AssertionError("sync_to should not be used in the full-plan path")
        ),
    )

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
            model_names=("locations", "devices"),
            fetch_all=False,
            limit=1,
        )
    )

    assert load_calls["count"] == 1
    assert plan.write_summary["create"] == 2
    assert plan.source.count("locations") == 1
    assert plan.source.count("devices") == 1


def test_planner_skips_nqe_when_snapshot_unchanged(monkeypatch):
    _require_planner()

    nqe_call_count = {"count": 0}

    def _resolve_snapshot(self, network_id, snapshot_id):
        return "snap-2"

    def _should_not_query(self, **kwargs):
        nqe_call_count["count"] += 1
        raise AssertionError("NQE must not be called when snapshot is unchanged")

    monkeypatch.setattr(ForwardClient, "resolve_snapshot_id", _resolve_snapshot)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _should_not_query)
    monkeypatch.setattr(ForwardClient, "run_nqe_diff", _should_not_query)
    monkeypatch.setattr(
        ForwardClient,
        "get_nqe_repository_query_index",
        lambda self, **kwargs: {"by_path": {}},
    )

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
            connection_profile=ForwardConnectionProfileRecord(
                name="primary",
                network_id="net-1",
                last_snapshot_id="snap-2",
            ),
        )
    )

    assert nqe_call_count["count"] == 0
    assert plan.reports == ()
    assert plan.diff_detail["skipped"] is True
    assert plan.diff_detail["current_snapshot_id"] == "snap-2"
    assert plan.diff_detail["baseline_snapshot_id"] == "snap-2"


def test_planner_propagates_sort_keys_to_nqe(monkeypatch):
    """Planner passes mapping.identity_fields as sortKeys for stable pagination."""
    _require_planner()
    captured_sort_keys: list = []

    def _resolve_snapshot(self, network_id, snapshot_id):
        return "snap-99"

    def _mock_run_nqe(self, *, query_spec, **kwargs):
        captured_sort_keys.extend(query_spec.sort_keys)
        return []

    monkeypatch.setattr(ForwardClient, "resolve_snapshot_id", _resolve_snapshot)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _mock_run_nqe)
    monkeypatch.setattr(ForwardClient, "run_nqe_diff", _mock_run_nqe)
    monkeypatch.setattr(
        ForwardClient,
        "resolve_query_spec",
        lambda self, qs: qs,
    )
    monkeypatch.setattr(
        ForwardClient,
        "get_nqe_repository_query_index",
        lambda self, **kwargs: {"by_path": {}},
    )

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        )
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
            model_names=("locations",),
            fetch_all=False,
        )
    )
    assert plan is not None
    assert "name" in captured_sort_keys, f"sort_keys not propagated; captured: {captured_sort_keys}"


def test_planner_diff_fallback_narrows_exception(monkeypatch):
    """Bare Exception in diff fallback replaced with ForwardClientError only."""
    _require_planner()
    from forward_nautobot.integrations.forward.exceptions import ForwardClientError

    def _resolve_snapshot(self, network_id, snapshot_id):
        return "snap-new"

    def _mock_run_nqe(self, *, query_spec, **kwargs):
        return []

    def _mock_run_diff(*args, **kwargs):
        raise ForwardClientError("diff-unavailable")

    def _mock_resolve_query_spec(self, qs):
        from dataclasses import replace

        return replace(qs, resolved_query_id="q-123", query_path=None, query_text="select { x: 1 }")

    monkeypatch.setattr(ForwardClient, "resolve_snapshot_id", _resolve_snapshot)
    monkeypatch.setattr(ForwardClient, "run_nqe_query", _mock_run_nqe)
    monkeypatch.setattr(ForwardClient, "run_nqe_diff", _mock_run_diff)
    monkeypatch.setattr(ForwardClient, "resolve_query_spec", _mock_resolve_query_spec)
    monkeypatch.setattr(
        ForwardClient,
        "get_nqe_repository_query_index",
        lambda self, **kwargs: {"by_path": {}},
    )

    client = ForwardClient(
        ForwardConnectionSettings(
            base_url="https://fwd.example",
            username="alice",
            password="secret",
            network_id="net-1",
        )
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
            model_names=("locations",),
            fetch_all=False,
            connection_profile=ForwardConnectionProfileRecord(
                name="primary",
                network_id="net-1",
                last_snapshot_id="snap-old",
            ),
        )
    )
    assert plan is not None
    loc_slice = plan.diff_detail.get("slices", {}).get("locations", {})
    assert "ForwardClientError" in str(loc_slice), f"Exception type not recorded: {loc_slice}"


def test_compute_tiers_detects_query_parameter_cycle():
    _require_planner()
    from forward_nautobot.integrations.forward.exceptions import ForwardConfigurationError
    from forward_nautobot.integrations.forward.registry import ForwardModelMapping

    a = ForwardModelMapping(
        slug="a",
        forward_query_file="a.nqe",
        description="",
        query_parameters={"x": ("b",)},
    )
    b = ForwardModelMapping(
        slug="b",
        forward_query_file="b.nqe",
        description="",
        query_parameters={"y": ("a",)},
    )
    import pytest

    with pytest.raises(ForwardConfigurationError, match="cycle"):
        ForwardIngestionPlanner._compute_tiers((a, b))


def test_compute_tiers_levels_default_slices():
    _require_planner()
    from forward_nautobot.integrations.forward.registry import get_model_mappings

    mappings = get_model_mappings(("locations", "platforms", "device_types", "devices"))
    tiers = ForwardIngestionPlanner._compute_tiers(mappings)
    slugs_by_tier = [{m.slug for m in tier} for tier in tiers]
    # locations first; platforms/device_types share a tier; devices last.
    assert slugs_by_tier[0] == {"locations"}
    assert {"platforms", "device_types"} <= slugs_by_tier[1]
    assert "devices" in slugs_by_tier[-1]
