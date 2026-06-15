import pytest
from types import SimpleNamespace
from importlib import import_module

from forward_nautobot import config
from forward_nautobot import menu
from forward_nautobot.integrations.forward import CORE_MODEL_SLUGS
from forward_nautobot.models import ForwardConnectionProfileRecord

try:
    from forward_nautobot.integrations.forward.client import ForwardClient
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    ForwardClient = None

try:
    import forward_nautobot.integrations.forward.jobs as jobs_module
    from forward_nautobot.integrations.forward.jobs import _build_ingestion_request
    from forward_nautobot.integrations.forward.jobs import ForwardInventoryDataSource
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    jobs_module = None
    _build_ingestion_request = None
    ForwardInventoryDataSource = None

try:
    from .test_client import _mock_transport
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    _mock_transport = None


def _require_jobs_module():
    global jobs_module, _build_ingestion_request, ForwardInventoryDataSource

    try:
        jobs_module = import_module("forward_nautobot.integrations.forward.jobs")
        _build_ingestion_request = getattr(jobs_module, "_build_ingestion_request", None)
        ForwardInventoryDataSource = getattr(jobs_module, "ForwardInventoryDataSource", None)
    except ModuleNotFoundError:  # pragma: no cover - environment without optional dependencies
        jobs_module = None
        _build_ingestion_request = None
        ForwardInventoryDataSource = None

    if jobs_module is None or ForwardInventoryDataSource is None or _build_ingestion_request is None:
        pytest.skip("Forward job tests require the full dependency set.")


def _require_httpx():
    if ForwardClient is None or _mock_transport is None:
        pytest.skip("httpx-backed Forward client tests require the full test dependency set.")


def _require_target_tables(*model_names: str):
    table_by_model = {
        "locations": "dcim_location",
        "platforms": "dcim_platform",
        "device_types": "dcim_devicetype",
        "devices": "dcim_device",
        "interfaces": "dcim_interface",
        "ip_addresses": "ipam_ipaddress",
        "vlans": "ipam_vlan",
        "prefixes": "ipam_prefix",
        "modules": "dcim_module",
        "inventory_items": "dcim_inventoryitem",
    }
    requested = [table_by_model[model] for model in model_names if model in table_by_model]
    if not requested:
        return

    try:
        from django.db import connection
    except ModuleNotFoundError:
        pytest.skip("Django is not installed.")

    try:
        existing_tables = set(connection.introspection.table_names())
    except Exception:
        return

    missing = [name for name in requested if name not in existing_tables]
    if missing:
        return


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
    _require_jobs_module()
    assert jobs_module.jobs == [ForwardInventoryDataSource]


def test_ssot_data_source_metadata():
    _require_jobs_module()
    mappings = ForwardInventoryDataSource.data_mappings()

    assert ForwardInventoryDataSource.Meta.name == "Forward Networks inventory"
    assert ForwardInventoryDataSource.Meta.data_source == "Forward Networks"
    assert (
        ForwardInventoryDataSource.class_path
        == "forward_nautobot.integrations.forward.jobs.ForwardInventoryDataSource"
    )
    assert ForwardInventoryDataSource.name == "Forward Networks inventory"
    assert ForwardInventoryDataSource.grouping == "Forward Networks"
    assert ForwardInventoryDataSource.description == (
        "Sync Forward Networks inventory data into Nautobot through the SSoT app."
    )
    assert ForwardInventoryDataSource.console_log_default is False
    assert ForwardInventoryDataSource.dryrun_default is True
    assert ForwardInventoryDataSource.hidden is False
    assert ForwardInventoryDataSource.soft_time_limit == 0
    assert ForwardInventoryDataSource.time_limit == 0
    assert ForwardInventoryDataSource.has_sensitive_variables is True
    assert ForwardInventoryDataSource.is_singleton is False
    assert ForwardInventoryDataSource.task_queues == ()
    assert not hasattr(ForwardInventoryDataSource, "query_mode")
    assert ForwardInventoryDataSource.config_information()["Profile selection"] == (
        "Uses a persisted profile by name or the default saved profile when available."
    )
    assert ForwardInventoryDataSource.config_information()["Query input"] == (
        "Bundled Forward NQE contracts only."
    )
    assert ForwardInventoryDataSource.config_information()["Model selection"] == (
        "Use selected_models to override a saved profile's enabled model set; leave it blank to use the profile defaults."
    )
    assert mappings[0].source_name == "Forward locations"
    assert mappings[0].target_name == "dcim.location"


def test_ssot_data_source_uses_persisted_profile_selection(monkeypatch):
    _require_jobs_module()
    _require_httpx()
    _require_target_tables("devices")
    stored_profile = ForwardConnectionProfileRecord(
        name="primary",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="snap-2",
        enabled_models=("devices",),
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        is_default=True,
    )
    captured = {"writes": 0}

    class _FakeManager:
        def all(self):
            return [SimpleNamespace(to_record=lambda: stored_profile)]

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
            return _FakeExecution()

    def _client_factory(settings):
        captured["settings"] = settings
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        jobs_module,
        "ForwardConnectionProfile",
        SimpleNamespace(objects=_FakeManager()),
    )
    monkeypatch.setattr(
        jobs_module,
        "ForwardClient",
        _client_factory,
        raising=True,
    )
    monkeypatch.setattr(
        jobs_module,
        "ForwardNautobotWriteExecutor",
        lambda: _FakeExecutor(),
        raising=True,
    )

    job = ForwardInventoryDataSource()
    result = job.run(
        profile_name="primary",
        selected_models="",
        snapshot_id="snap-2",
        fetch_all=False,
        limit=1,
        dryrun=True,
    )

    assert captured["settings"].base_url == "https://fwd.example"
    assert captured["settings"].network_id == "net-1"
    assert captured["writes"] == 0
    assert result["source_summary"]["model_counts"]["devices"] == 2
    assert result["configuration_status"]["profile_provided"] is True
    assert result["profile_status"]["last_failure"] == "clean"
    assert result["profile_status"]["last_support_bundle"] == "forward_devices.nqe"
    assert result["profile_status"]["last_query_reference"] == "forward_devices.nqe"
    assert result["profile_status"]["last_query_mode"] == "bundled_nqe_query_id"
    assert result["profile_status"]["last_snapshot_id"] == "snap-2"


def test_build_ingestion_request_uses_profile_models_and_selected_overrides(monkeypatch):
    _require_jobs_module()
    stored_profile = ForwardConnectionProfileRecord(
        name="primary",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="latestProcessed",
        enabled_models=("devices", "interfaces"),
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        is_default=True,
    )

    class _FakeManager:
        def all(self):
            return [SimpleNamespace(to_record=lambda: stored_profile)]

    monkeypatch.setattr(
        jobs_module,
        "ForwardConnectionProfile",
        SimpleNamespace(objects=_FakeManager()),
    )

    request = _build_ingestion_request(
        dryrun=True,
        profile_name="primary",
        selected_models="",
        snapshot_id="latestProcessed",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
    )

    assert request.model_names == ("devices", "interfaces")
    assert request.connection.base_url == "https://fwd.example"
    assert request.connection.snapshot_id == "latestProcessed"

    override_request = _build_ingestion_request(
        dryrun=True,
        profile_name="primary",
        selected_models="locations,devices",
        snapshot_id="latestProcessed",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
    )

    assert override_request.model_names == ("locations", "devices")


def test_ssot_lookup_object_resolves_real_objects(monkeypatch):
    _require_jobs_module()
    class _FakeManager:
        def __init__(self, *records):
            self.records = list(records)

        @staticmethod
        def _resolve_value(record, key):
            value = record
            for part in str(key).split("__"):
                value = getattr(value, part)
            return value

        def get(self, **lookup):
            for record in self.records:
                if all(self._resolve_value(record, key) == value for key, value in lookup.items()):
                    return record
            raise LookupError(lookup)

    class _FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[(app_label, model_name)]

    location = SimpleNamespace(name="SITE-ALPHA")
    location_type = SimpleNamespace(name="Building")
    platform = SimpleNamespace(name="NX-9000")
    device_type = SimpleNamespace(name="NX-9000", model="NX-9000")
    device = SimpleNamespace(name="device-alpha-01")
    interface = SimpleNamespace(device=device, name="Ethernet1/1")
    role = SimpleNamespace(name="Access Switch")
    status = SimpleNamespace(name="Active")
    manufacturer = SimpleNamespace(name="Cisco")
    module_type = SimpleNamespace(name="Line Card", model="Line Card")
    vlan = SimpleNamespace(location=location, vid=100)
    vrf = SimpleNamespace(name="BLUE")
    prefix = SimpleNamespace(prefix="10.0.0.0/24")
    ip_address = SimpleNamespace(address="10.10.10.1/24", vrf=vrf)
    ip_address_default = SimpleNamespace(address="10.10.10.2/24")
    inventory_item = SimpleNamespace(device=device, name="Chassis")
    module = SimpleNamespace(device=device, module_bay=SimpleNamespace(position="Bay 1"))

    models = {
        ("dcim", "Location"): SimpleNamespace(objects=_FakeManager(location)),
        ("dcim", "LocationType"): SimpleNamespace(objects=_FakeManager(location_type)),
        ("dcim", "Platform"): SimpleNamespace(objects=_FakeManager(platform)),
        ("dcim", "DeviceType"): SimpleNamespace(objects=_FakeManager(device_type)),
        ("dcim", "Device"): SimpleNamespace(objects=_FakeManager(device)),
        ("dcim", "Interface"): SimpleNamespace(objects=_FakeManager(interface)),
        ("dcim", "Manufacturer"): SimpleNamespace(objects=_FakeManager(manufacturer)),
        ("dcim", "ModuleType"): SimpleNamespace(objects=_FakeManager(module_type)),
        ("extras", "Role"): SimpleNamespace(objects=_FakeManager(role)),
        ("extras", "Status"): SimpleNamespace(objects=_FakeManager(status)),
        ("ipam", "VLAN"): SimpleNamespace(objects=_FakeManager(vlan)),
        ("ipam", "VRF"): SimpleNamespace(objects=_FakeManager(vrf)),
        ("ipam", "Prefix"): SimpleNamespace(objects=_FakeManager(prefix)),
        ("ipam", "IPAddress"): SimpleNamespace(objects=_FakeManager(ip_address)),
        ("dcim", "InventoryItem"): SimpleNamespace(objects=_FakeManager(inventory_item)),
        ("dcim", "Module"): SimpleNamespace(objects=_FakeManager(module)),
    }
    models[("ipam", "IPAddress")].objects.records.append(ip_address_default)
    monkeypatch.setattr(jobs_module, "django_apps", _FakeApps(models))

    job = ForwardInventoryDataSource()

    assert job.lookup_object("locations", "SITE-ALPHA") is location
    assert job.lookup_object("location_type", "Building") is location_type
    assert job.lookup_object("dcim.locationtype", "Building") is location_type
    assert job.lookup_object("platforms", "NX-9000") is platform
    assert job.lookup_object("dcim.platform", "NX-9000") is platform
    assert job.lookup_object("device_types", "NX-9000") is device_type
    assert job.lookup_object("dcim.devicetype", "NX-9000") is device_type
    assert job.lookup_object("manufacturer", "Cisco") is manufacturer
    assert job.lookup_object("dcim.manufacturer", "Cisco") is manufacturer
    assert job.lookup_object("role", "Access Switch") is role
    assert job.lookup_object("extras.role", "Access Switch") is role
    assert job.lookup_object("status", "Active") is status
    assert job.lookup_object("extras.status", "Active") is status
    assert job.lookup_object("module_type", "Line Card") is module_type
    assert job.lookup_object("dcim.moduletype", "Line Card") is module_type
    assert job.lookup_object("devices", "device-alpha-01") is device
    assert job.lookup_object("interfaces", "device-alpha-01|Ethernet1/1") is interface
    assert job.lookup_object("vlans", "SITE-ALPHA|100") is vlan
    assert job.lookup_object("ipam.vlan", "SITE-ALPHA|100") is vlan
    assert (
        job.lookup_object("ip_addresses", "device-alpha-01|Ethernet1/1|10.10.10.1/24|BLUE")
        is ip_address
    )
    assert job.lookup_object("ipv4_prefixes", "10.0.0.0/24|default") is prefix
    assert job.lookup_object("inventory_items", "device-alpha-01|Chassis") is inventory_item
    assert job.lookup_object("dcim.inventoryitem", "device-alpha-01|Chassis") is inventory_item
    assert job.lookup_object("modules", "device-alpha-01|Bay 1") is module
    assert job.lookup_object("dcim.module", "device-alpha-01|Bay 1") is module
    assert (
        job.lookup_object("ip_addresses", "device-alpha-01|Ethernet1/1|10.10.10.2/24|default")
        is ip_address_default
    )


def test_ssot_data_source_run_preserves_job_inputs_for_sync(monkeypatch):
    _require_jobs_module()
    captured = {}

    def _sync_data(self, memory_profiling=False):
        captured["memory_profiling"] = memory_profiling
        captured["dryrun"] = self.dryrun
        captured["job_data"] = dict(getattr(self, "_forward_job_data", {}))
        return {"ok": True}

    monkeypatch.setattr(ForwardInventoryDataSource, "sync_data", _sync_data)

    job = ForwardInventoryDataSource()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        selected_models="devices,interfaces",
        profile_name="primary",
        dryrun=False,
        memory_profiling=True,
    )

    assert result == {"ok": True}
    assert captured["memory_profiling"] is True
    assert captured["dryrun"] is False
    assert captured["job_data"]["selected_models"] == "devices,interfaces"
    assert captured["job_data"]["profile_name"] == "primary"
    assert "dryrun" in captured["job_data"]


def test_ssot_data_source_dryrun_uses_bundled_contracts_and_persists_diff(monkeypatch):
    _require_jobs_module()
    _require_httpx()
    _require_target_tables("devices")
    captured = {"writes": 0}

    class _FakeExecutor:
        def execute(self, plan, profile):
            captured["writes"] += 1
            captured["profile"] = profile
            return None

    def _client_factory(settings):
        return ForwardClient(settings, transport=_mock_transport())

    monkeypatch.setattr(
        jobs_module,
        "ForwardClient",
        _client_factory,
        raising=True,
    )
    monkeypatch.setattr(
        jobs_module,
        "ForwardNautobotWriteExecutor",
        lambda: _FakeExecutor(),
        raising=True,
    )

    job = ForwardInventoryDataSource()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="snap-2",
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
    _require_jobs_module()
    _require_httpx()
    _require_target_tables("devices")
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
        jobs_module,
        "ForwardClient",
        _client_factory,
        raising=True,
    )
    monkeypatch.setattr(
        jobs_module,
        "ForwardNautobotWriteExecutor",
        lambda: _FakeExecutor(),
        raising=True,
    )

    job = ForwardInventoryDataSource()
    result = job.run(
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-1",
        snapshot_id="snap-2",
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
    assert result["profile_status"]["last_query_reference"] == "forward_devices.nqe"
    assert result["profile_status"]["last_query_mode"] == "bundled_nqe_query_id"
    assert result["profile_status"]["last_snapshot_id"] == "snap-2"


def test_requested_model_mappings_are_deduplicated():
    from forward_nautobot.integrations.forward.registry import get_model_mappings

    mappings = get_model_mappings(["devices", "devices", "interfaces", "devices"])
    assert [mapping.slug for mapping in mappings] == ["devices", "interfaces"]
