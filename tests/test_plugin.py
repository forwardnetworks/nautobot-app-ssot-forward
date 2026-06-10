from forward_nautobot import config
from forward_nautobot import menu
from forward_nautobot.integrations.forward import CORE_MODEL_MAPPINGS
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
    assert [mapping.slug for mapping in CORE_MODEL_MAPPINGS[:4]] == [
        "locations",
        "platforms",
        "device_types",
        "devices",
    ]


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
    assert spec.model_names == ("devices", "interfaces")


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
    assert result["diff_summary"]["create"] == 2
    assert result["reports"][0]["query_reference"] == "forward_devices.nqe"
    assert result["support_bundle"]["source_summary"]["model_counts"]["devices"] == 2
    assert result["support_bundle"]["diagnostics"]["diff_summary"]["create"] == 2
