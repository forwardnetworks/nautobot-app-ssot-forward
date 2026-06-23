from types import SimpleNamespace

import forward_nautobot.integrations.forward.adapters as adapters
from forward_nautobot.integrations.forward import CORE_MODEL_SLUGS
from forward_nautobot.integrations.forward.adapters import (
    NautobotTargetAdapter,
)


def _assert_record_fields(record, expected):
    data = record.dict()
    assert {key: data[key] for key in expected} == expected


def test_target_adapter_plans_raw_rows_without_normalization():
    adapter = NautobotTargetAdapter(model_names=("devices",))
    rows = [
        {
            "name": "device-1",
            "location": "Site A",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        }
    ]

    planned = adapter.plan_rows("devices", rows)

    assert adapter.count("devices") == 1
    assert planned[0].record_key == "device-1"
    assert planned[0].fields == rows[0]
    assert planned[0].nautobot_scope == "dcim.device"
    assert adapter.get_all("devices")[0].dict()["name"] == "device-1"


def test_target_adapter_loads_current_orm_state_when_available(monkeypatch):
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

    target = NautobotTargetAdapter(model_names=("locations",))

    target.load()

    assert target.count("locations") == 1
    assert target.get_all("locations")[0].dict()["name"] == "SITE-ALPHA"
    assert target.get_all("locations")[0].dict()["city"] == "Austin"
    assert target.get_all("locations")[0].dict()["country"] == "US"


def test_target_adapter_tolerates_db_error_during_load(monkeypatch):
    """A DB read error during load returns an empty target rather than exploding;
    the dangerous mass-DELETE case is guarded separately by the reconcile
    max-delete-fraction safeguard."""

    class _BoomManager:
        def all(self):
            raise adapters.DjangoDatabaseError("unable to open database file")

    class _FakeApps:
        def get_model(self, app_label, model_name):
            return type("LocationModel", (), {"objects": _BoomManager()})

    monkeypatch.setattr(adapters, "django_apps", _FakeApps())
    target = NautobotTargetAdapter(model_names=("locations",))
    target.load()  # must not raise
    assert target.count("locations") == 0


def test_target_adapter_skips_bad_row_without_truncating(monkeypatch):
    """One malformed row is skipped; the rest of the slice still loads."""
    good = adapters.ForwardLocation(name="SITE-GOOD", city="A", country="US")

    class _FakeManager:
        def all(self):
            return ["BAD-NON-MODEL-ROW", good]

    class _FakeApps:
        def get_model(self, app_label, model_name):
            return type("LocationModel", (), {"objects": _FakeManager()})

    monkeypatch.setattr(adapters, "django_apps", _FakeApps())

    # Make the first row blow up in serialization, the second succeed.
    real_serialize = NautobotTargetAdapter._serialize_orm_row

    def _serialize(self, mapping, instance):
        if instance == "BAD-NON-MODEL-ROW":
            raise ValueError("bad row")
        return real_serialize(self, mapping, instance)

    monkeypatch.setattr(NautobotTargetAdapter, "_serialize_orm_row", _serialize)

    target = NautobotTargetAdapter(model_names=("locations",))
    target.load()
    assert target.count("locations") == 1


def test_target_adapter_loads_current_orm_state_for_supported_models(monkeypatch):
    class _FakeManager:
        def __init__(self, *records):
            self.records = list(records)

        def all(self):
            return list(self.records)

    class _FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[(app_label, model_name)]

    manufacturer = SimpleNamespace(name="Cisco")
    location = SimpleNamespace(name="SITE-ALPHA", city="Austin", country="US")
    platform = SimpleNamespace(
        name="NX-9000",
        manufacturer=manufacturer,
        cf={"device_type": "NX-9000"},
    )
    device_type = SimpleNamespace(
        model="NX-9000",
        manufacturer=manufacturer,
        cf={"color": "9e9e9e"},
    )
    device = SimpleNamespace(
        name="device-1",
        location=location,
        platform=platform,
        device_type=device_type,
    )
    vlan = SimpleNamespace(
        location=location,
        vid=100,
        name="Users",
        status=SimpleNamespace(name="Active"),
    )
    vrf = SimpleNamespace(
        name="BLUE",
        rd="65000:1",
        description="Blue VRF",
        enforce_unique=True,
    )
    prefix = SimpleNamespace(
        prefix="10.0.0.0/24",
        vrf=vrf,
        status=SimpleNamespace(name="Active"),
    )
    interface = SimpleNamespace(
        device=device,
        name="Ethernet1/1",
        type=SimpleNamespace(value="1000base-t"),
        lag=SimpleNamespace(name="Port-Channel1"),
        mode="access",
        untagged_vlan=SimpleNamespace(vid=100),
        enabled=True,
        mtu=1500,
        description="uplink",
        speed=1000000000,
    )
    ip_address = SimpleNamespace(
        assigned_object=interface,
        address="10.0.0.1/24",
        vrf=vrf,
        status=SimpleNamespace(name="Active"),
    )
    inventory_item = SimpleNamespace(
        device=device,
        name="Chassis",
        manufacturer=manufacturer,
        label="Chassis",
        part_id="PID1",
        serial="SER1",
        asset_tag="AT1",
        role=SimpleNamespace(name="Chassis"),
        status=SimpleNamespace(name="Active"),
        discovered=True,
        description="Inventory item",
    )
    module_type = SimpleNamespace(
        manufacturer=manufacturer,
        model="Line Card",
        part_number="LC1",
    )
    module = SimpleNamespace(
        device=device,
        module_bay=SimpleNamespace(position="Bay 1"),
        module_type=module_type,
        status=SimpleNamespace(name="Active"),
        serial="MSN1",
        asset_tag="MAT1",
        description="Module",
    )

    models = {
        ("dcim", "location"): type("LocationModel", (), {"objects": _FakeManager(location)}),
        ("dcim", "platform"): type("PlatformModel", (), {"objects": _FakeManager(platform)}),
        ("dcim", "devicetype"): type("DeviceTypeModel", (), {"objects": _FakeManager(device_type)}),
        ("dcim", "device"): type("DeviceModel", (), {"objects": _FakeManager(device)}),
        ("dcim", "interface"): type("InterfaceModel", (), {"objects": _FakeManager(interface)}),
        ("ipam", "vlan"): type("VLANModel", (), {"objects": _FakeManager(vlan)}),
        ("ipam", "vrf"): type("VRFModel", (), {"objects": _FakeManager(vrf)}),
        ("ipam", "prefix"): type("PrefixModel", (), {"objects": _FakeManager(prefix)}),
        ("ipam", "ipaddress"): type("IPAddressModel", (), {"objects": _FakeManager(ip_address)}),
        ("dcim", "inventoryitem"): type(
            "InventoryItemModel", (), {"objects": _FakeManager(inventory_item)}
        ),
        ("dcim", "module"): type("ModuleModel", (), {"objects": _FakeManager(module)}),
    }
    monkeypatch.setattr(adapters, "django_apps", _FakeApps(models))

    target = NautobotTargetAdapter(model_names=CORE_MODEL_SLUGS)
    target.load()

    assert target.count("locations") == 1
    assert target.count("platforms") == 1
    assert target.count("device_types") == 1
    assert target.count("devices") == 1
    assert target.count("interfaces") == 1
    assert target.count("vlans") == 1
    assert target.count("vrfs") == 1
    assert target.count("ipv4_prefixes") == 1
    assert target.count("ipv6_prefixes") == 1
    assert target.count("ip_addresses") == 1
    assert target.count("inventory_items") == 1
    assert target.count("modules") == 1
    _assert_record_fields(
        target.get_all("locations")[0],
        {
            "name": "SITE-ALPHA",
            "city": "Austin",
            "country": "US",
        },
    )
    _assert_record_fields(
        target.get_all("platforms")[0],
        {
            "name": "NX-9000",
            "manufacturer": "Cisco",
            "device_type": "NX-9000",
        },
    )
    _assert_record_fields(
        target.get_all("device_types")[0],
        {
            "name": "NX-9000",
            "color": "9e9e9e",
        },
    )
    _assert_record_fields(
        target.get_all("devices")[0],
        {
            "name": "device-1",
            "location": "SITE-ALPHA",
            "vendor": "Cisco",
            "model": "NX-9000",
            "device_type": "NX-9000",
        },
    )
    _assert_record_fields(
        target.get_all("interfaces")[0],
        {
            "device": "device-1",
            "name": "Ethernet1/1",
            "type": "1000base-t",
            "lag": "Port-Channel1",
            "mode": "access",
            "untagged_vlan": 100,
            "enabled": True,
            "mtu": 1500,
            "description": "uplink",
            "speed": 1000000000,
        },
    )
    _assert_record_fields(
        target.get_all("vlans")[0],
        {
            "site": "SITE-ALPHA",
            "vid": 100,
            "name": "Users",
            "status": "Active",
        },
    )
    _assert_record_fields(
        target.get_all("vrfs")[0],
        {
            "name": "BLUE",
            "rd": "65000:1",
            "description": "Blue VRF",
            "enforce_unique": True,
        },
    )
    _assert_record_fields(
        target.get_all("ipv4_prefixes")[0],
        {
            "prefix": "10.0.0.0/24",
            "vrf": "BLUE",
            "status": "Active",
        },
    )
    _assert_record_fields(
        target.get_all("ipv6_prefixes")[0],
        {
            "prefix": "10.0.0.0/24",
            "vrf": "BLUE",
            "status": "Active",
        },
    )
    _assert_record_fields(
        target.get_all("ip_addresses")[0],
        {
            "device": "device-1",
            "interface": "Ethernet1/1",
            "address": "10.0.0.1/24",
            "host_ip": "10.0.0.1",
            "prefix_length": 24,
            "vrf": "BLUE",
            "status": "Active",
        },
    )
    _assert_record_fields(
        target.get_all("inventory_items")[0],
        {
            "device": "device-1",
            "name": "Chassis",
            "manufacturer": "Cisco",
            "label": "Chassis",
            "part_id": "PID1",
            "serial": "SER1",
            "asset_tag": "AT1",
            "role": "Chassis",
            "status": "Active",
            "discovered": True,
            "description": "Inventory item",
        },
    )
    _assert_record_fields(
        target.get_all("modules")[0],
        {
            "device": "device-1",
            "module_bay": "Bay 1",
            "manufacturer": "Cisco",
            "model": "Line Card",
            "part_number": "LC1",
            "status": "Active",
            "serial": "MSN1",
            "asset_tag": "MAT1",
            "description": "Module",
        },
    )


def test_target_adapter_slice_for_model_reuses_loaded_rows():
    adapter = NautobotTargetAdapter(model_names=("devices",))
    rows = [
        {
            "name": "device-1",
            "location": "Site A",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        }
    ]

    adapter.load_rows("devices", rows)
    sliced = adapter.slice_for_model("devices")

    assert sliced.count("devices") == 1
    assert sliced.get_all("devices")[0].dict()["name"] == "device-1"
    assert sliced.get_all("devices")[0].dict()["location"] == "Site A"
