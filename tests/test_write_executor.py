from __future__ import annotations

from types import SimpleNamespace

import forward_nautobot.integrations.forward.write_executor as write_executor
from forward_nautobot.integrations.forward.write_executor import ForwardNautobotWriteBackend
from forward_nautobot.integrations.forward.write_executor import ForwardNautobotWriteExecutor
from forward_nautobot.integrations.forward.write_path import ForwardWriteOperation
from forward_nautobot.integrations.forward.write_path import ForwardWritePlan
from forward_nautobot.models import ForwardConnectionProfileRecord


class _FakeRelation:
    def __init__(self):
        self.values: list[object] = []

    def add(self, value):
        self.values.append(value)


class _FakeRecord(SimpleNamespace):
    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.saved = 0
        self.content_types = _FakeRelation()
        self._manager: _FakeManager | None = None

    def save(self):
        self.saved += 1

    def delete(self):
        if self._manager is None:
            return
        for key, value in list(self._manager.records.items()):
            if value is self:
                del self._manager.records[key]
                break


class _FakeManager:
    def __init__(self):
        self.records: dict[tuple[tuple[str, object], ...], _FakeRecord] = {}

    @staticmethod
    def _key(lookup: dict[str, object]) -> tuple[tuple[str, object], ...]:
        normalized = []
        for key, value in lookup.items():
            if isinstance(value, _FakeRecord):
                normalized.append(
                    (key, getattr(value, "name", getattr(value, "position", None)))
                )
            else:
                normalized.append((key, value))
        return tuple(sorted(normalized))

    def get_or_create(self, defaults=None, **lookup):
        key = self._key(lookup)
        if key in self.records:
            return self.records[key], False
        record = _FakeRecord(**lookup, **(defaults or {}))
        record._manager = self
        self.records[key] = record
        return record, True

    def get(self, **lookup):
        key = self._key(lookup)
        if key not in self.records:
            raise LookupError(key)
        return self.records[key]


class _FakeModel:
    def __init__(self):
        self.objects = _FakeManager()


def _fake_model_resolver():
    models = {
        ("dcim", "LocationType"): _FakeModel(),
        ("extras", "Status"): _FakeModel(),
        ("dcim", "Location"): _FakeModel(),
        ("dcim", "Manufacturer"): _FakeModel(),
        ("dcim", "Platform"): _FakeModel(),
        ("dcim", "DeviceType"): _FakeModel(),
        ("extras", "Role"): _FakeModel(),
        ("dcim", "Device"): _FakeModel(),
        ("dcim", "Interface"): _FakeModel(),
        ("ipam", "VLAN"): _FakeModel(),
        ("ipam", "VRF"): _FakeModel(),
        ("ipam", "Prefix"): _FakeModel(),
        ("ipam", "IPAddress"): _FakeModel(),
        ("dcim", "InventoryItem"): _FakeModel(),
        ("dcim", "ModuleBay"): _FakeModel(),
        ("dcim", "ModuleType"): _FakeModel(),
        ("dcim", "Module"): _FakeModel(),
    }

    def resolve(app_label: str, model_name: str):
        lookup_name = {
            "locationtype": "LocationType",
            "status": "Status",
            "location": "Location",
            "manufacturer": "Manufacturer",
            "platform": "Platform",
            "devicetype": "DeviceType",
            "role": "Role",
            "device": "Device",
            "interface": "Interface",
            "vlan": "VLAN",
            "vrf": "VRF",
            "prefix": "Prefix",
            "ipaddress": "IPAddress",
            "inventoryitem": "InventoryItem",
            "modulebay": "ModuleBay",
            "moduletype": "ModuleType",
            "module": "Module",
        }.get(str(model_name).lower(), model_name)
        return models[(app_label, lookup_name)]

    return models, resolve


def test_write_executor_applies_core_slices_with_fake_backend(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)

    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    profile = ForwardConnectionProfileRecord(
        name="profile",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
    )
    plan = ForwardWritePlan(
        operations=(
            ForwardWriteOperation(
                model_slug="locations",
                record_key="SITE-ALPHA",
                nautobot_scope="dcim.location",
                action="create",
                fields={"name": "SITE-ALPHA", "city": "Metropolis", "country": "US"},
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="platforms",
                record_key="NX-9000",
                nautobot_scope="dcim.platform",
                action="create",
                fields={"name": "NX-9000", "manufacturer": "Cisco"},
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="device_types",
                record_key="NX-9000",
                nautobot_scope="dcim.devicetype",
                action="create",
                fields={
                    "name": "NX-9000",
                    "manufacturer": "Cisco",
                    "model": "NX-9000",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="devices",
                record_key="device-1",
                nautobot_scope="dcim.device",
                action="create",
                fields={
                    "name": "device-1",
                    "location": "SITE-ALPHA",
                    "vendor": "Cisco",
                    "model": "NX-9000",
                    "device_type": "NX-9000",
                },
                contract_version="v1",
            ),
        ),
        summary={"create": 4, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True, "missing_defaults": [], "delete_policy": "ignore"},
    )

    execution = executor.execute(plan, profile)

    assert execution.summary["created"] == 4
    assert execution.summary["blocked"] == 0
    assert execution.failure_classification == "clean"
    assert execution.items[0].status == "created"
    assert execution.items[2].status == "created"
    assert execution.items[3].status == "created"
    assert models[("dcim", "Location")].objects.records
    assert models[("dcim", "Device")].objects.records


def test_write_executor_honors_delete_policy(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)

    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    profile = ForwardConnectionProfileRecord(
        name="profile",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="delete",
    )
    models[("dcim", "Location")].objects.get_or_create(name="SITE-OLD")
    plan = ForwardWritePlan(
        operations=(
            ForwardWriteOperation(
                model_slug="locations",
                record_key="SITE-ALPHA",
                nautobot_scope="dcim.location",
                action="create",
                fields={"name": "SITE-ALPHA"},
                contract_version="v1",
            ),
        ),
        summary={"create": 1, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True, "missing_defaults": [], "delete_policy": "delete"},
    )

    execution = executor.execute(plan, profile)

    assert execution.summary["deleted"] == 1
    assert execution.failure_classification == "clean"
    assert not models[("dcim", "Location")].objects.records.get((("name", "SITE-OLD"),))


def test_write_executor_applies_expanded_slices_with_fake_backend(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)

    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    profile = ForwardConnectionProfileRecord(
        name="profile",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
    )
    plan = ForwardWritePlan(
        operations=(
            ForwardWriteOperation(
                model_slug="locations",
                record_key="SITE-ALPHA",
                nautobot_scope="dcim.location",
                action="create",
                fields={"name": "SITE-ALPHA"},
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="platforms",
                record_key="NX-9000",
                nautobot_scope="dcim.platform",
                action="create",
                fields={"name": "NX-9000", "manufacturer": "Cisco"},
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="device_types",
                record_key="NX-9000",
                nautobot_scope="dcim.devicetype",
                action="create",
                fields={
                    "name": "NX-9000",
                    "manufacturer": "Cisco",
                    "model": "NX-9000",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="devices",
                record_key="device-1",
                nautobot_scope="dcim.device",
                action="create",
                fields={
                    "name": "device-1",
                    "location": "SITE-ALPHA",
                    "vendor": "Cisco",
                    "model": "NX-9000",
                    "device_type": "NX-9000",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="interfaces",
                record_key="device-1|Ethernet1",
                nautobot_scope="dcim.interface",
                action="create",
                fields={
                    "device": "device-1",
                    "name": "Ethernet1",
                    "type": "1000base-t",
                    "enabled": True,
                    "mtu": 1500,
                    "description": "uplink",
                    "speed": 1000000,
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="vlans",
                record_key="SITE-ALPHA|100",
                nautobot_scope="ipam.vlan",
                action="create",
                fields={
                    "site": "SITE-ALPHA",
                    "vid": 100,
                    "name": "Users",
                    "status": "active",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="vrfs",
                record_key="BLUE",
                nautobot_scope="ipam.vrf",
                action="create",
                fields={
                    "name": "BLUE",
                    "rd": "",
                    "description": "",
                    "enforce_unique": False,
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="ipv4_prefixes",
                record_key="10.0.0.0/24|BLUE",
                nautobot_scope="ipam.prefix",
                action="create",
                fields={
                    "prefix": "10.0.0.0/24",
                    "vrf": "BLUE",
                    "status": "active",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="ip_addresses",
                record_key="device-1|Ethernet1|10.0.0.1/24|BLUE",
                nautobot_scope="ipam.ipaddress",
                action="create",
                fields={
                    "device": "device-1",
                    "interface": "Ethernet1",
                    "address": "10.0.0.1/24",
                    "vrf": "BLUE",
                    "status": "active",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="inventory_items",
                record_key="device-1|fan-1",
                nautobot_scope="dcim.inventoryitem",
                action="create",
                fields={
                    "device": "device-1",
                    "manufacturer": "Cisco",
                    "name": "fan-1",
                    "label": "Fan",
                    "part_id": "FAN-1",
                    "serial": "S1",
                    "asset_tag": "A1",
                    "role": "FAN MODULE",
                    "status": "active",
                    "discovered": True,
                    "description": "Cooling fan",
                },
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="modules",
                record_key="device-1|Bay 1",
                nautobot_scope="dcim.module",
                action="create",
                fields={
                    "device": "device-1",
                    "module_bay": "Bay 1",
                    "manufacturer": "Cisco",
                    "model": "Line Card",
                    "part_number": "LC1",
                    "status": "active",
                    "serial": "M1",
                    "asset_tag": "A2",
                    "description": "Line card",
                },
                contract_version="v1",
            ),
        ),
        summary={"create": 10, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True, "missing_defaults": [], "delete_policy": "ignore"},
    )

    execution = executor.execute(plan, profile)

    assert execution.summary["created"] == 11
    assert execution.failure_classification == "clean"
    assert execution.items[4].status == "created"
    assert execution.items[5].status == "created"
    assert execution.items[6].status == "created"
    assert execution.items[7].status == "created"
    assert execution.items[8].status == "created"
    assert execution.items[9].status == "created"
    assert execution.items[10].status == "created"
