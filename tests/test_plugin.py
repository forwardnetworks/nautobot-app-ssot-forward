from forward_nautobot import config
from forward_nautobot import menu
from forward_nautobot.integrations.forward import CORE_MODEL_MAPPINGS
from forward_nautobot.integrations.forward import CORE_MODEL_SLUGS
from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.jobs import ForwardIngestionPlanJob
from forward_nautobot.integrations.forward.jobs import ForwardInventoryPreview

from .test_client import _mock_transport


def test_plugin_config_metadata():
    assert config.name == "forward_nautobot"
    assert config.base_url == "forward"
    assert config.verbose_name == "Forward Nautobot Plugin"
    assert config.jobs == "integrations.forward.jobs"


def test_navigation_surface_exists():
    assert menu.label == "Forward Networks"
    assert len(menu.groups) == 2


def test_core_model_registry_is_seeded():
    assert CORE_MODEL_SLUGS[:4] == (
        "locations",
        "platforms",
        "device_types",
        "devices",
    )


def test_job_query_building():
    job = ForwardInventoryPreview()
    spec = job._build_spec(
        "preview",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        query_mode="query_path",
        query_repository="org",
        query_path="/queries/devices.nqe",
        query_commit_id="head",
        query_text="",
        query_id="",
        query_parameters_json='{"limit": 10}',
        fetch_all=True,
        limit=0,
        selected_models="devices,interfaces",
    )
    assert spec.connection.base_url == "https://fwd.example"
    assert spec.query is not None
    assert spec.query.execution_mode == "query_path"
    assert spec.query.parameters == {"limit": 10}
    assert spec.model_names == ("devices", "interfaces")


def test_requested_model_mappings_are_deduplicated():
    from forward_nautobot.integrations.forward.registry import get_model_mappings

    mappings = get_model_mappings(["devices", "devices", "interfaces", "devices"])
    assert [mapping.slug for mapping in mappings] == ["devices", "interfaces"]


def test_ingestion_plan_job_runs_on_bundled_nqe(monkeypatch):
    def _client_factory(settings):
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        "forward_nautobot.integrations.forward.jobs.ForwardClient",
        _client_factory,
    )
    job = ForwardIngestionPlanJob()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=2,
        selected_models="devices",
    )
    assert result["source_summary"]["model_counts"]["devices"] == 2
    assert result["target_summary"]["planned_counts"]["devices"] == 2
    assert result["write_summary"]["create"] == 2
    assert result["configuration_status"]["profile_provided"] is False
    assert result["configuration_status"]["delete_policy"] == "ignore"
    assert result["configuration_status"]["missing_defaults"] == []
    assert result["diff_summary"]["create"] == 2
    assert result["reports"][0]["query_reference"] == "forward_devices.nqe"
    assert result["reports"][0]["query_contract_version"] == "v1"
    assert result["support_bundle"]["source_summary"]["model_counts"]["devices"] == 2
    assert result["support_bundle"]["write_summary"]["create"] == 2
    assert result["support_bundle"]["write_policy"]["devices"]["missing_row_policy"] == "mark_inactive"
    assert result["support_bundle"]["configuration_status"]["profile_provided"] is False
    assert result["support_bundle"]["configuration_status"]["delete_policy"] == "ignore"
    assert result["support_bundle"]["configuration_status"]["missing_defaults"] == []
    assert result["support_bundle"]["sharing_profile"] == "external"
    assert result["failure_classification"] == "clean"
    assert result["support_bundle"]["diagnostics"]["diff_summary"]["create"] == 2
    assert result["support_bundle_shared"]["write_summary"]["create"] == 2
    assert result["support_bundle_shared"]["source_url"] == "[REDACTED]"
    assert result["support_bundle_shared"]["sharing_profile"] == "external"
    assert result["profile_status"] == {}


def test_ingestion_plan_job_carries_profile_readiness_fields(monkeypatch):
    def _client_factory(settings):
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        "forward_nautobot.integrations.forward.jobs.ForwardClient",
        _client_factory,
    )
    job = ForwardIngestionPlanJob()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=1,
        selected_models="devices",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        profile_name="primary",
    )

    assert result["configuration_status"]["profile_provided"] is True
    assert result["configuration_status"]["delete_policy"] == "mark_inactive"
    assert result["failure_classification"] == "clean"
    assert result["profile_status"]["last_run_at"].startswith("20")
    assert result["profile_status"]["last_failure"] == "clean"
    assert result["profile_status"]["last_support_bundle"] == "forward_devices.nqe"


def test_ingestion_plan_job_can_share_internal_support_bundle(monkeypatch):
    def _client_factory(settings):
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        "forward_nautobot.integrations.forward.jobs.ForwardClient",
        _client_factory,
    )
    job = ForwardIngestionPlanJob()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=1,
        selected_models="devices",
        support_bundle_sharing_profile="internal",
    )

    assert result["support_bundle"]["sharing_profile"] == "internal"
    assert result["support_bundle_shared"]["source_url"] == "https://fwd.example"
    assert result["support_bundle_shared"]["sharing_profile"] == "internal"


def test_ingestion_plan_job_can_apply_writes(monkeypatch):
    captured = {}

    class _FakeExecution:
        def as_dict(self):
            return {
                "items": [{"model_slug": "devices", "status": "created"}],
                "summary": {"created": 1, "updated": 0, "no-change": 0, "blocked": 0, "skipped": 0, "errors": 0},
                "configuration_status": {"profile_provided": True, "write_ready": True},
                "failure_classification": "clean",
            }

    class _FakeExecutor:
        def execute(self, plan, profile):
            captured["plan"] = plan
            captured["profile"] = profile
            return _FakeExecution()

    def _client_factory(settings):
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        "forward_nautobot.integrations.forward.jobs.ForwardClient",
        _client_factory,
    )
    monkeypatch.setattr(
        "forward_nautobot.integrations.forward.jobs.ForwardNautobotWriteExecutor",
        lambda: _FakeExecutor(),
    )

    job = ForwardIngestionPlanJob()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=1,
        selected_models="devices",
        apply_writes=True,
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        profile_name="primary",
    )

    assert captured["profile"] is not None
    assert result["write_execution"]["summary"]["created"] == 1
    assert result["failure_classification"] == "clean"
