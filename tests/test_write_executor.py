from __future__ import annotations

from types import SimpleNamespace

import forward_nautobot.integrations.forward.write_executor as write_executor
from forward_nautobot.integrations.forward.write_executor import (
    ForwardNautobotWriteBackend,
    ForwardNautobotWriteExecutor,
)
from forward_nautobot.integrations.forward.write_path import ForwardWriteOperation, ForwardWritePlan
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
    def __init__(self, allowed_fields: tuple[str, ...] | None = None):
        self.records: dict[tuple[tuple[str, object], ...], _FakeRecord] = {}
        self.allowed_fields = set(allowed_fields or ())
        self.get_or_create_calls = 0

    @staticmethod
    def _key(lookup: dict[str, object]) -> tuple[tuple[str, object], ...]:
        normalized = []
        for key, value in lookup.items():
            if isinstance(value, _FakeRecord):
                normalized.append((key, getattr(value, "name", getattr(value, "position", None))))
            else:
                normalized.append((key, value))
        return tuple(sorted(normalized))

    def _validate(self, values: dict[str, object] | None):
        if not self.allowed_fields or not values:
            return
        unknown = sorted(set(values) - self.allowed_fields)
        if unknown:
            raise AssertionError(f"unexpected field(s): {', '.join(unknown)}")

    def get_or_create(self, defaults=None, **lookup):
        self.get_or_create_calls += 1
        self._validate(lookup)
        self._validate(defaults)
        key = self._key(lookup)
        if key in self.records:
            return self.records[key], False
        record = _FakeRecord(**lookup, **(defaults or {}))
        record._manager = self
        self.records[key] = record
        return record, True

    def get(self, **lookup):
        self._validate(lookup)
        key = self._key(lookup)
        if key not in self.records:
            raise LookupError(key)
        return self.records[key]


class _FakeModel:
    def __init__(
        self,
        *,
        field_names: tuple[str, ...] | None = None,
        allowed_fields: tuple[str, ...] | None = None,
    ):
        self.objects = _FakeManager(allowed_fields=allowed_fields)
        if field_names:
            self._meta = _MetaStub(*field_names)


class _FieldStub:
    def __init__(self, name: str):
        self.name = name


class _MetaStub:
    def __init__(self, *field_names: str):
        self.fields = tuple(_FieldStub(name) for name in field_names)


class _SchemaModel:
    def __init__(self, *field_names: str):
        self._meta = _MetaStub(*field_names)


def _fake_model_resolver():
    models = {
        ("dcim", "LocationType"): _FakeModel(field_names=("name",), allowed_fields=("name",)),
        ("extras", "Status"): _FakeModel(field_names=("name",), allowed_fields=("name",)),
        ("dcim", "Location"): _FakeModel(
            field_names=("name", "location_type", "status"),
            allowed_fields=("name", "location_type", "status"),
        ),
        ("dcim", "Manufacturer"): _FakeModel(field_names=("name",), allowed_fields=("name",)),
        ("dcim", "Platform"): _FakeModel(
            field_names=("name", "manufacturer"), allowed_fields=("name", "manufacturer")
        ),
        ("dcim", "DeviceType"): _FakeModel(
            field_names=("manufacturer", "model"), allowed_fields=("manufacturer", "model")
        ),
        ("extras", "Role"): _FakeModel(field_names=("name",), allowed_fields=("name",)),
        ("dcim", "Device"): _FakeModel(
            field_names=("name", "location", "platform", "device_type", "role", "status"),
            allowed_fields=("name", "location", "platform", "device_type", "role", "status"),
        ),
        ("dcim", "Interface"): _FakeModel(
            field_names=("device", "name", "type", "enabled", "mtu", "description", "speed", "lag"),
            allowed_fields=(
                "device",
                "name",
                "type",
                "enabled",
                "mtu",
                "description",
                "speed",
                "lag",
            ),
        ),
        ("ipam", "VLAN"): _FakeModel(
            field_names=("vid", "location", "name", "status"),
            allowed_fields=("vid", "location", "name", "status"),
        ),
        ("ipam", "VRF"): _FakeModel(
            field_names=("name", "rd", "description", "enforce_unique"),
            allowed_fields=("name", "rd", "description", "enforce_unique"),
        ),
        ("ipam", "Prefix"): _FakeModel(
            field_names=("prefix", "vrf", "status"), allowed_fields=("prefix", "vrf", "status")
        ),
        ("ipam", "IPAddress"): _FakeModel(
            field_names=("address", "vrf", "status", "assigned_object"),
            allowed_fields=("address", "vrf", "status", "assigned_object"),
        ),
        ("dcim", "InventoryItem"): _FakeModel(
            field_names=(
                "device",
                "name",
                "label",
                "part_id",
                "serial",
                "asset_tag",
                "status",
                "role",
                "manufacturer",
                "discovered",
                "description",
            ),
            allowed_fields=(
                "device",
                "name",
                "label",
                "part_id",
                "serial",
                "asset_tag",
                "status",
                "role",
                "manufacturer",
                "discovered",
                "description",
            ),
        ),
        ("dcim", "ModuleBay"): _FakeModel(
            field_names=("device", "position"), allowed_fields=("device", "position")
        ),
        ("dcim", "ModuleType"): _FakeModel(
            field_names=("manufacturer", "model", "part_number"),
            allowed_fields=("manufacturer", "model", "part_number"),
        ),
        ("dcim", "Module"): _FakeModel(
            field_names=("device", "module_bay", "module_type", "status", "serial", "asset_tag"),
            allowed_fields=("device", "module_bay", "module_type", "status", "serial", "asset_tag"),
        ),
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
        configuration_status={
            "profile_provided": True,
            "write_ready": True,
            "missing_defaults": [],
            "delete_policy": "ignore",
        },
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


def test_write_executor_routes_via_registry_metadata(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)

    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    captured = {}

    def _fake_upsert_location(operation, profile):
        captured["handler"] = "location"
        captured["operation"] = operation
        captured["profile"] = profile
        return _FakeRecord(name=operation.fields["name"]), True

    monkeypatch.setattr(backend, "_upsert_location", _fake_upsert_location)
    monkeypatch.setattr(
        write_executor,
        "get_model_mapping",
        lambda slug: SimpleNamespace(write_handler="_upsert_location"),
    )

    item = backend.apply_operation(
        ForwardWriteOperation(
            model_slug="locations",
            record_key="SITE-ALPHA",
            nautobot_scope="dcim.location",
            action="create",
            fields={"name": "SITE-ALPHA"},
            contract_version="v1",
        ),
        ForwardConnectionProfileRecord(name="profile"),
    )

    assert captured["handler"] == "location"
    assert item.status == "created"
    assert item.object_label == "SITE-ALPHA"


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
        configuration_status={
            "profile_provided": True,
            "write_ready": True,
            "missing_defaults": [],
            "delete_policy": "delete",
        },
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
        configuration_status={
            "profile_provided": True,
            "write_ready": True,
            "missing_defaults": [],
            "delete_policy": "ignore",
        },
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


def _device_op(name: str) -> ForwardWriteOperation:
    return ForwardWriteOperation(
        model_slug="devices",
        record_key=name,
        nautobot_scope="dcim.device",
        action="create",
        fields={
            "name": name,
            "location": "SITE-ALPHA",
            "vendor": "Cisco",
            "model": "NX-9000",
            "device_type": "NX-9000",
        },
        contract_version="v1",
    )


def _profile(**kw) -> ForwardConnectionProfileRecord:
    base = dict(
        name="profile",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
    )
    base.update(kw)
    return ForwardConnectionProfileRecord(**base)


def test_write_executor_caches_fk_resolution_across_rows(monkeypatch):
    """The run-constant Role/Status and shared Location/Manufacturer are resolved
    once and reused, not re-fetched per device row."""
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)

    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    plan = ForwardWritePlan(
        operations=(_device_op("device-1"), _device_op("device-2"), _device_op("device-3")),
        summary={"create": 3, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True},
    )

    execution = executor.execute(plan, _profile())

    assert execution.summary["created"] == 3
    # Role / Status / Location / Manufacturer are identical across all 3 devices:
    # each named model is resolved exactly once thanks to the per-run cache.
    assert models[("extras", "Role")].objects.get_or_create_calls == 1
    assert models[("dcim", "Location")].objects.get_or_create_calls == 1
    assert models[("dcim", "Manufacturer")].objects.get_or_create_calls == 1
    # Status is shared by all device rows too (one name, one resolution).
    assert models[("extras", "Status")].objects.get_or_create_calls == 1


def test_write_executor_summary_has_single_error_key(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    plan = ForwardWritePlan(
        operations=(_device_op("device-1"),),
        summary={"create": 1, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True},
    )
    execution = executor.execute(plan, _profile())
    assert "error" in execution.summary
    assert "errors" not in execution.summary


def test_write_executor_builds_delete_index_once(monkeypatch):
    """Multiple deletes against one slice materialize the existing-instance set a
    single time instead of a full-table scan per delete."""
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)

    scans = {"count": 0}
    real_iter = backend._iter_existing_instances

    def _counting_iter(slug):
        scans["count"] += 1
        return real_iter(slug)

    monkeypatch.setattr(backend, "_iter_existing_instances", _counting_iter)

    loc = models[("dcim", "Location")].objects
    loc.get_or_create(name="SITE-OLD-1")
    loc.get_or_create(name="SITE-OLD-2")

    executor = ForwardNautobotWriteExecutor(backend=backend)
    plan = ForwardWritePlan(
        operations=(
            ForwardWriteOperation(
                model_slug="locations",
                record_key="SITE-OLD-1",
                nautobot_scope="dcim.location",
                action="delete",
                fields={"name": "SITE-OLD-1"},
                contract_version="v1",
            ),
            ForwardWriteOperation(
                model_slug="locations",
                record_key="SITE-OLD-2",
                nautobot_scope="dcim.location",
                action="delete",
                fields={"name": "SITE-OLD-2"},
                contract_version="v1",
            ),
        ),
        summary={"create": 0, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True},
    )

    execution = executor.execute(plan, _profile(delete_policy="delete"))

    assert execution.summary.get("deleted") == 2
    # Two deletes, but the existing-instance set is materialized only once.
    assert scans["count"] == 1


def test_write_executor_savepoint_isolates_failing_row(monkeypatch):
    """A row that raises is recorded as error and does not abort sibling rows."""
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    plan = ForwardWritePlan(
        operations=(
            _device_op("device-1"),
            # missing required `location` -> handler raises ValueError
            ForwardWriteOperation(
                model_slug="devices",
                record_key="device-bad",
                nautobot_scope="dcim.device",
                action="create",
                fields={
                    "name": "device-bad",
                    "vendor": "Cisco",
                    "model": "NX-9000",
                    "device_type": "NX-9000",
                },
                contract_version="v1",
            ),
            _device_op("device-2"),
        ),
        summary={"create": 3, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True},
    )
    execution = executor.execute(plan, _profile())
    assert execution.summary["created"] == 2
    assert execution.summary["error"] == 1
    assert [item.status for item in execution.items] == ["created", "error", "created"]


def _location_op(name: str) -> ForwardWriteOperation:
    return ForwardWriteOperation(
        model_slug="locations",
        record_key=name,
        nautobot_scope="dcim.location",
        action="create",
        fields={"name": name},
        contract_version="v1",
    )


def test_write_executor_dedups_location_name_variants(monkeypatch):
    """Formatting variants of one physical site collapse to a single Location;
    a genuinely different address stays distinct."""
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)
    executor = ForwardNautobotWriteExecutor(backend=backend)
    plan = ForwardWritePlan(
        operations=(
            _location_op("8ng5+500 W 30TH ST+NEW YORK+NY+10001"),
            _location_op("8ng5+500 W 30TH STREET+NEW YORK+NY+10001"),
            _location_op("8ng5+500 W 33rd St+NY+NY+10001"),
        ),
        summary={"create": 3, "update": 0, "no-change": 0, "blocked": 0},
        configuration_status={"profile_provided": True, "write_ready": True},
    )

    executor.execute(plan, _profile())

    # Two ST/STREET variants -> one Location; the 33rd address -> a second.
    assert len(models[("dcim", "Location")].objects.records) == 2


def test_reconcile_missing_guards_partial_collection(monkeypatch):
    """Reconcile refuses to remove more than the configured fraction of a table,
    so an under-collected slice cannot wipe most of the inventory."""
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)

    loc = models[("dcim", "Location")].objects
    for n in ("A", "B", "C", "D"):
        loc.get_or_create(name=n)

    # Source only knows "A"; reconcile would remove B/C/D = 3/4 = 75% > 50%.
    items = backend.reconcile_missing("locations", {"A"}, "delete", max_delete_fraction=0.5)

    assert len(items) == 1
    assert items[0].status == "skipped"
    assert "safeguard" in items[0].message
    # Nothing was deleted.
    assert len(loc.records) == 4


def test_reconcile_missing_proceeds_under_threshold(monkeypatch):
    models, resolve = _fake_model_resolver()
    monkeypatch.setattr(write_executor, "django_apps", object())
    monkeypatch.setattr(write_executor, "ContentType", None)
    backend = ForwardNautobotWriteBackend(model_resolver=resolve)

    loc = models[("dcim", "Location")].objects
    for n in ("A", "B", "C", "D"):
        loc.get_or_create(name=n)

    # Source knows A/B/C; reconcile removes only D = 1/4 = 25% < 50%.
    items = backend.reconcile_missing(
        "locations", {"A", "B", "C"}, "delete", max_delete_fraction=0.5
    )

    assert [i.status for i in items] == ["deleted"]
    assert len(loc.records) == 3
