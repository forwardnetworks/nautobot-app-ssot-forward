from types import SimpleNamespace

from forward_nautobot import config
from forward_nautobot import menu
from forward_nautobot.integrations.forward import CORE_MODEL_SLUGS
from forward_nautobot.integrations.forward.client import ForwardClient
import forward_nautobot.integrations.forward.jobs as jobs_module
from forward_nautobot.integrations.forward.jobs import ForwardInventoryDataSource

from .test_client import _mock_transport


def test_plugin_config_metadata():
    assert config.name == "forward_nautobot"
    assert config.base_url == "forward"
    assert config.verbose_name == "Forward Networks SSoT"
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


def test_ssot_job_module_registers_only_one_sync_job():
    assert jobs_module.jobs == [ForwardInventoryDataSource]


def test_ssot_data_source_metadata():
    mappings = ForwardInventoryDataSource.data_mappings()

    assert ForwardInventoryDataSource.Meta.name == "Forward Networks inventory"
    assert ForwardInventoryDataSource.Meta.data_source == "Forward Networks"
    assert not hasattr(ForwardInventoryDataSource, "query_mode")
    assert ForwardInventoryDataSource.config_information()["Query input"] == (
        "Bundled Forward NQE contracts only."
    )
    assert mappings[0].source_name == "Forward locations"
    assert mappings[0].target_name == "dcim.location"


def test_ssot_lookup_object_resolves_real_objects(monkeypatch):
    class _FakeManager:
        def __init__(self, *records):
            self.records = list(records)

        def get(self, **lookup):
            for record in self.records:
                if all(getattr(record, key) == value for key, value in lookup.items()):
                    return record
            raise LookupError(lookup)

    class _FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[(app_label, model_name)]

    location = SimpleNamespace(name="SITE-ALPHA")
    device = SimpleNamespace(name="device-alpha-01")
    interface = SimpleNamespace(device=device, name="Ethernet1/1")
    vrf = SimpleNamespace(name="BLUE")
    ip_address = SimpleNamespace(address="10.10.10.1/24", vrf=vrf)

    models = {
        ("dcim", "Location"): SimpleNamespace(objects=_FakeManager(location)),
        ("dcim", "Device"): SimpleNamespace(objects=_FakeManager(device)),
        ("dcim", "Interface"): SimpleNamespace(objects=_FakeManager(interface)),
        ("ipam", "VRF"): SimpleNamespace(objects=_FakeManager(vrf)),
        ("ipam", "IPAddress"): SimpleNamespace(objects=_FakeManager(ip_address)),
    }
    monkeypatch.setattr(jobs_module, "django_apps", _FakeApps(models))

    job = ForwardInventoryDataSource()

    assert job.lookup_object("locations", "SITE-ALPHA") is location
    assert job.lookup_object("devices", "device-alpha-01") is device
    assert job.lookup_object("interfaces", "device-alpha-01|Ethernet1/1") is interface
    assert (
        job.lookup_object("ip_addresses", "device-alpha-01|Ethernet1/1|10.10.10.1/24|BLUE")
        is ip_address
    )


def test_ssot_data_source_dryrun_uses_bundled_contracts_and_persists_diff(monkeypatch):
    captured = {"writes": 0}

    class _FakeExecutor:
        def execute(self, plan, profile):
            captured["writes"] += 1
            captured["profile"] = profile
            return None

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

    job = ForwardInventoryDataSource()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=1,
        selected_models="devices",
        dryrun=True,
    )

    assert result["write_execution"] == {}
    assert captured["writes"] == 0
    assert result["diff_summary"]["create"] == 2
    assert job.sync.summary["create"] == 2
    assert job.sync.diff == result["support_bundle"]["diagnostics"]["diff_detail"]
    assert result["configuration_status"]["profile_provided"] is False
    assert result["failure_classification"] == "clean"


def test_ssot_data_source_non_dryrun_applies_writes_and_persists_diff(monkeypatch):
    captured = {"writes": 0}

    class _FakeExecution:
        def as_dict(self):
            return {
                "items": [{"model_slug": "devices", "status": "created"}],
                "summary": {
                    "created": 2,
                    "updated": 0,
                    "no-change": 0,
                    "blocked": 0,
                    "skipped": 0,
                    "errors": 0,
                },
                "configuration_status": {"profile_provided": True, "write_ready": True},
                "failure_classification": "clean",
            }

    class _FakeExecutor:
        def execute(self, plan, profile):
            captured["writes"] += 1
            captured["profile"] = profile
            captured["plan"] = plan
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

    job = ForwardInventoryDataSource()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        fetch_all=False,
        limit=1,
        selected_models="devices",
        dryrun=False,
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        profile_name="primary",
    )

    assert captured["writes"] == 1
    assert captured["profile"] is not None
    assert result["write_execution"]["summary"]["created"] == 2
    assert result["failure_classification"] == "clean"
    assert job.sync.summary["create"] == 2
    assert job.sync.diff == result["support_bundle"]["diagnostics"]["diff_detail"]
    assert result["profile_status"]["last_failure"] == "clean"
    assert result["profile_status"]["last_support_bundle"] == "forward_devices.nqe"


def test_requested_model_mappings_are_deduplicated():
    from forward_nautobot.integrations.forward.registry import get_model_mappings

    mappings = get_model_mappings(["devices", "devices", "interfaces", "devices"])
    assert [mapping.slug for mapping in mappings] == ["devices", "interfaces"]
