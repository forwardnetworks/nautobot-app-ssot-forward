"""DiffSync adapter helpers for the Forward integration."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_interface
from typing import Any

try:
    from django.db import OperationalError as DjangoOperationalError
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path

    class DjangoOperationalError(Exception):
        """Fallback for environments without Django."""

        pass


try:
    from django.apps import apps as django_apps
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    django_apps = None

try:
    from diffsync import Adapter
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path

    class Adapter:  # type: ignore[too-many-ancestors]
        """Fallback adapter base when DiffSync is not installed."""

        def __init__(self, *args, **kwargs):
            self.name = str(kwargs.get("name") or "")
            self._records: dict[str, list[Any]] = {}

        def add(self, item):
            model_name = str(getattr(item, "_modelname", "") or item.__class__.__name__)
            self._records.setdefault(model_name, []).append(item)
            return item

        def get_all(self, model_name):
            return tuple(self._records.get(str(model_name), ()))

        @staticmethod
        def _item_key(item: Any) -> tuple[tuple[str, Any], ...] | None:
            identifiers = tuple(getattr(item, "_identifiers", ()) or ())
            if not identifiers:
                return None
            key_parts: list[tuple[str, Any]] = []
            for field_name in identifiers:
                if not hasattr(item, field_name):
                    return None
                key_parts.append((field_name, getattr(item, field_name)))
            return tuple(key_parts)

        @classmethod
        def _item_data(cls, item: Any) -> dict[str, Any]:
            if hasattr(item, "dict"):
                try:
                    data = item.dict()
                    if isinstance(data, dict):
                        return dict(data)
                except Exception:
                    pass
            return {
                key: value
                for key, value in getattr(item, "__dict__", {}).items()
                if not str(key).startswith("_")
            }

        def sync_to(self, target):
            summary = {"create": 0, "update": 0, "no-change": 0, "blocked": 0}
            detail: dict[str, Any] = {"models": {}}
            model_names = sorted(set(self._records) | set(getattr(target, "_records", {})))
            for model_name in model_names:
                source_items = list(self.get_all(model_name))
                target_items = list(getattr(target, "get_all", lambda _name: ())(model_name))
                source_by_key: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
                target_by_key: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
                for item in source_items:
                    key = self._item_key(item)
                    if key is None:
                        continue
                    source_by_key[key] = self._item_data(item)
                for item in target_items:
                    key = self._item_key(item)
                    if key is None:
                        continue
                    target_by_key[key] = self._item_data(item)
                model_detail = {"create": 0, "update": 0, "no-change": 0}
                for key, source_row in source_by_key.items():
                    target_row = target_by_key.get(key)
                    if target_row is None:
                        summary["create"] += 1
                        model_detail["create"] += 1
                    elif target_row != source_row:
                        summary["update"] += 1
                        model_detail["update"] += 1
                    else:
                        summary["no-change"] += 1
                        model_detail["no-change"] += 1
                detail["models"][model_name] = model_detail
                if hasattr(target, "_records"):
                    target._records[model_name] = list(source_items)

            class _FallbackDiff:
                def __init__(self, summary: dict[str, int], detail: dict[str, Any]):
                    self._summary = dict(summary)
                    self._detail = dict(detail)

                def summary(self) -> dict[str, int]:
                    return dict(self._summary)

                def dict(self) -> dict[str, Any]:
                    return dict(self._detail)

            return _FallbackDiff(summary, detail)


from .diffsync_models import (
    ForwardDevice,
    ForwardDeviceType,
    ForwardInterface,
    ForwardInventoryItem,
    ForwardIPAddress,
    ForwardIPv4Prefix,
    ForwardIPv6Prefix,
    ForwardLocation,
    ForwardModule,
    ForwardPlatform,
    ForwardVLAN,
    ForwardVRF,
)
from .registry import CORE_MODEL_MAPPINGS, CORE_MODEL_SLUGS, ForwardModelMapping, get_model_mappings


def _string_value(value: Any, *attrs: str) -> str:
    if value is None:
        return ""
    for attr_name in attrs:
        attr_value = getattr(value, attr_name, None)
        if attr_value is None:
            continue
        text = str(attr_value).strip()
        if text:
            return text
    return str(value).strip()


def _int_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class ForwardLoadedRecord:
    """Raw row loaded from a Forward query contract."""

    model_slug: str
    record_key: str
    fields: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ForwardPlannedWrite:
    """Raw row prepared for a future Nautobot write."""

    model_slug: str
    record_key: str
    fields: dict[str, Any]
    nautobot_scope: str


class ForwardSourceAdapter(Adapter):
    """Source-side adapter that stores raw Forward rows by model slice."""

    top_level = CORE_MODEL_SLUGS
    locations = ForwardLocation
    platforms = ForwardPlatform
    device_types = ForwardDeviceType
    devices = ForwardDevice
    interfaces = ForwardInterface
    vlans = ForwardVLAN
    vrfs = ForwardVRF
    ipv4_prefixes = ForwardIPv4Prefix
    ipv6_prefixes = ForwardIPv6Prefix
    ip_addresses = ForwardIPAddress
    inventory_items = ForwardInventoryItem
    modules = ForwardModule

    def __init__(self, model_names: tuple[str, ...] | list[str] | None = None):
        super().__init__(name="forward_source")
        self.model_mappings: tuple[ForwardModelMapping, ...] = get_model_mappings(model_names)
        self._mapping_by_slug = {mapping.slug: mapping for mapping in CORE_MODEL_MAPPINGS}
        self.records: dict[str, dict[str, ForwardLoadedRecord]] = {
            mapping.slug: {} for mapping in self.model_mappings
        }

    def _get_mapping(self, model_slug: str) -> ForwardModelMapping:
        model_slug = str(model_slug or "").strip()
        if model_slug not in self._mapping_by_slug:
            raise KeyError(f"Unknown Forward model slice: {model_slug}")
        mapping = self._mapping_by_slug[model_slug]
        if mapping.slug not in self.records:
            self.records[mapping.slug] = {}
        return mapping

    @staticmethod
    def _row_key(mapping: ForwardModelMapping, row: dict[str, Any]) -> str:
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = row.get(field_name)
            if value is None:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` is missing identity field `{field_name}`."
                )
            value_text = str(value).strip()
            if not value_text:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` has an empty identity field `{field_name}`."
                )
            key_parts.append(value_text)
        return "|".join(key_parts)

    def load_rows(self, model_slug: str, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]):
        mapping = self._get_mapping(model_slug)
        loaded: list[ForwardLoadedRecord] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_key = self._row_key(mapping, row)
            model_class = getattr(self, mapping.slug, None)
            if model_class is not None:
                self.add(model_class(**dict(row)))
            record = ForwardLoadedRecord(
                model_slug=mapping.slug,
                record_key=record_key,
                fields=dict(row),
            )
            self.records[mapping.slug][record_key] = record
            loaded.append(record)
        return tuple(loaded)

    def slice_for_model(self, model_slug: str) -> ForwardSourceAdapter:
        mapping = self._get_mapping(model_slug)
        slice_adapter = ForwardSourceAdapter(model_names=(mapping.slug,))
        slice_rows = tuple(
            dict(record.fields) for record in self.records.get(mapping.slug, {}).values()
        )
        if slice_rows:
            slice_adapter.load_rows(mapping.slug, slice_rows)
        return slice_adapter

    def count(self, model_slug: str) -> int:
        mapping = self._get_mapping(model_slug)
        return max(
            len(self.records.get(mapping.slug, {})),
            len(self.get_all(mapping.slug)),
        )

    def as_support_summary(self) -> dict[str, Any]:
        return {
            "model_counts": {
                slug: max(len(records), len(self.get_all(slug)))
                for slug, records in sorted(self.records.items())
            },
            "model_slugs": [mapping.slug for mapping in self.model_mappings],
        }


class NautobotTargetAdapter(Adapter):
    """Target-side adapter for Nautobot inventory."""

    top_level = CORE_MODEL_SLUGS
    locations = ForwardLocation
    platforms = ForwardPlatform
    device_types = ForwardDeviceType
    devices = ForwardDevice
    interfaces = ForwardInterface
    vlans = ForwardVLAN
    vrfs = ForwardVRF
    ipv4_prefixes = ForwardIPv4Prefix
    ipv6_prefixes = ForwardIPv6Prefix
    ip_addresses = ForwardIPAddress
    inventory_items = ForwardInventoryItem
    modules = ForwardModule

    def __init__(self, model_names: tuple[str, ...] | list[str] | None = None):
        super().__init__(name="nautobot_target")
        self.model_mappings: tuple[ForwardModelMapping, ...] = get_model_mappings(model_names)
        self._mapping_by_slug = {mapping.slug: mapping for mapping in CORE_MODEL_MAPPINGS}
        self.loaded_records: dict[str, dict[str, ForwardPlannedWrite]] = {
            mapping.slug: {} for mapping in self.model_mappings
        }
        self.planned_writes: dict[str, dict[str, ForwardPlannedWrite]] = {
            mapping.slug: {} for mapping in self.model_mappings
        }

    def _get_mapping(self, model_slug: str) -> ForwardModelMapping:
        model_slug = str(model_slug or "").strip()
        if model_slug not in self._mapping_by_slug:
            raise KeyError(f"Unknown Forward model slice: {model_slug}")
        mapping = self._mapping_by_slug[model_slug]
        if mapping.slug not in self.planned_writes:
            self.planned_writes[mapping.slug] = {}
        return mapping

    @staticmethod
    def _row_key(mapping: ForwardModelMapping, row: dict[str, Any]) -> str:
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = row.get(field_name)
            if value is None:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` is missing identity field `{field_name}`."
                )
            value_text = str(value).strip()
            if not value_text:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` has an empty identity field `{field_name}`."
                )
            key_parts.append(value_text)
        return "|".join(key_parts)

    def plan_rows(self, model_slug: str, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]):
        mapping = self._get_mapping(model_slug)
        planned: list[ForwardPlannedWrite] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_key = self._row_key(mapping, row)
            model_class = getattr(self, mapping.slug, None)
            if model_class is not None:
                self.add(model_class(**dict(row)))
            write = ForwardPlannedWrite(
                model_slug=mapping.slug,
                record_key=record_key,
                fields=dict(row),
                nautobot_scope=mapping.nautobot_scope,
            )
            self.planned_writes[mapping.slug][record_key] = write
            planned.append(write)
        return tuple(planned)

    def load_rows(self, model_slug: str, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]):
        mapping = self._get_mapping(model_slug)
        loaded: list[ForwardPlannedWrite] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            record_key = self._row_key(mapping, row)
            model_class = getattr(self, mapping.slug, None)
            if model_class is not None:
                self.add(model_class(**dict(row)))
            loaded_record = ForwardPlannedWrite(
                model_slug=mapping.slug,
                record_key=record_key,
                fields=dict(row),
                nautobot_scope=mapping.nautobot_scope,
            )
            self.loaded_records[mapping.slug][record_key] = loaded_record
            loaded.append(loaded_record)
        return tuple(loaded)

    @staticmethod
    def _cf_value(instance: Any, key: str) -> Any:
        custom_fields = getattr(instance, "cf", None)
        if isinstance(custom_fields, dict):
            return custom_fields.get(key)
        return None

    def _serialize_location(self, instance: Any) -> dict[str, Any]:
        return {
            "name": _string_value(getattr(instance, "name", "")),
            "city": _string_value(getattr(instance, "city", "")),
            "country": _string_value(getattr(instance, "country", "")),
        }

    def _serialize_platform(self, instance: Any) -> dict[str, Any]:
        return {
            "name": _string_value(getattr(instance, "name", "")),
            "manufacturer": _string_value(getattr(instance, "manufacturer", None), "name"),
            "device_type": _string_value(self._cf_value(instance, "device_type")),
        }

    def _serialize_device_type(self, instance: Any) -> dict[str, Any]:
        return {
            "name": _string_value(getattr(instance, "model", ""), "name"),
            "color": _string_value(self._cf_value(instance, "color")) or "9e9e9e",
        }

    def _serialize_device(self, instance: Any) -> dict[str, Any]:
        location = getattr(instance, "location", None)
        platform = getattr(instance, "platform", None)
        device_type = getattr(instance, "device_type", None)
        vendor = _string_value(getattr(getattr(device_type, "manufacturer", None), "name", ""))
        if not vendor:
            vendor = _string_value(getattr(platform, "manufacturer", None), "name")
        model = _string_value(getattr(platform, "name", ""), "name")
        device_type_name = _string_value(getattr(device_type, "model", ""), "name")
        if not device_type_name:
            device_type_name = _string_value(self._cf_value(instance, "device_type"))
        return {
            "name": _string_value(getattr(instance, "name", "")),
            "location": _string_value(location, "name"),
            "vendor": vendor,
            "model": model,
            "device_type": device_type_name,
        }

    def _serialize_interface(self, instance: Any) -> dict[str, Any]:
        device = getattr(instance, "device", None)
        lag = getattr(instance, "lag", None)
        untagged_vlan = getattr(instance, "untagged_vlan", None)
        return {
            "device": _string_value(device, "name"),
            "name": _string_value(getattr(instance, "name", "")),
            "type": _string_value(getattr(instance, "type", "other"), "value", "name") or "other",
            "lag": _string_value(lag, "name"),
            "mode": _string_value(getattr(instance, "mode", "")),
            "untagged_vlan": _int_value(getattr(untagged_vlan, "vid", untagged_vlan)),
            "enabled": bool(getattr(instance, "enabled", True)),
            "mtu": _int_value(getattr(instance, "mtu", None)),
            "description": _string_value(getattr(instance, "description", "")),
            "speed": _int_value(getattr(instance, "speed", None)),
        }

    def _serialize_vlan(self, instance: Any) -> dict[str, Any]:
        location = getattr(instance, "location", None)
        status = getattr(instance, "status", None)
        return {
            "site": _string_value(location, "name"),
            "vid": _int_value(getattr(instance, "vid", None)) or 0,
            "name": _string_value(getattr(instance, "name", "")),
            "status": _string_value(status, "name") or "active",
        }

    def _serialize_vrf(self, instance: Any) -> dict[str, Any]:
        return {
            "name": _string_value(getattr(instance, "name", "")),
            "rd": _string_value(getattr(instance, "rd", "")),
            "description": _string_value(getattr(instance, "description", "")),
            "enforce_unique": bool(getattr(instance, "enforce_unique", False)),
        }

    def _serialize_prefix(self, instance: Any) -> dict[str, Any]:
        vrf = getattr(instance, "vrf", None)
        status = getattr(instance, "status", None)
        return {
            "prefix": _string_value(getattr(instance, "prefix", "")),
            "vrf": _string_value(vrf, "name") or "default",
            "status": _string_value(status, "name") or "active",
        }

    def _serialize_ip_address(self, instance: Any) -> dict[str, Any]:
        assigned_object = getattr(instance, "assigned_object", None)
        device = getattr(assigned_object, "device", None)
        vrf = getattr(instance, "vrf", None)
        status = getattr(instance, "status", None)
        address = _string_value(getattr(instance, "address", ""))
        host_ip = ""
        prefix_length = None
        if address:
            try:
                parsed = ip_interface(address)
            except ValueError:
                parsed = None
            if parsed is not None:
                host_ip = str(parsed.ip)
                prefix_length = int(parsed.network.prefixlen)
        return {
            "device": _string_value(device, "name"),
            "interface": _string_value(assigned_object, "name"),
            "address": address,
            "host_ip": host_ip,
            "prefix_length": prefix_length,
            "vrf": _string_value(vrf, "name") or "default",
            "status": _string_value(status, "name") or "active",
        }

    def _serialize_inventory_item(self, instance: Any) -> dict[str, Any]:
        device = getattr(instance, "device", None)
        manufacturer = getattr(instance, "manufacturer", None)
        role = getattr(instance, "role", None)
        status = getattr(instance, "status", None)
        return {
            "device": _string_value(device, "name"),
            "name": _string_value(getattr(instance, "name", "")),
            "manufacturer": _string_value(manufacturer, "name"),
            "label": _string_value(getattr(instance, "label", "")),
            "part_id": _string_value(getattr(instance, "part_id", "")),
            "serial": _string_value(getattr(instance, "serial", "")),
            "asset_tag": _string_value(getattr(instance, "asset_tag", "")),
            "role": _string_value(role, "name"),
            "status": _string_value(status, "name") or "active",
            "discovered": bool(getattr(instance, "discovered", True)),
            "description": _string_value(getattr(instance, "description", "")),
        }

    def _serialize_module(self, instance: Any) -> dict[str, Any]:
        device = getattr(instance, "device", None)
        module_bay = getattr(instance, "module_bay", None)
        module_type = getattr(instance, "module_type", None)
        manufacturer = getattr(module_type, "manufacturer", None)
        status = getattr(instance, "status", None)
        return {
            "device": _string_value(device, "name"),
            "module_bay": _string_value(module_bay, "position"),
            "manufacturer": _string_value(manufacturer, "name"),
            "model": _string_value(getattr(module_type, "model", "")),
            "part_number": _string_value(getattr(module_type, "part_number", "")),
            "status": _string_value(status, "name") or "active",
            "serial": _string_value(getattr(instance, "serial", "")),
            "asset_tag": _string_value(getattr(instance, "asset_tag", "")),
            "description": _string_value(getattr(instance, "description", "")),
        }

    def _serialize_orm_row(
        self, mapping: ForwardModelMapping, instance: Any
    ) -> dict[str, Any] | None:
        serializer_name = {
            "locations": "_serialize_location",
            "platforms": "_serialize_platform",
            "device_types": "_serialize_device_type",
            "devices": "_serialize_device",
            "interfaces": "_serialize_interface",
            "vlans": "_serialize_vlan",
            "vrfs": "_serialize_vrf",
            "ipv4_prefixes": "_serialize_prefix",
            "ipv6_prefixes": "_serialize_prefix",
            "ip_addresses": "_serialize_ip_address",
            "inventory_items": "_serialize_inventory_item",
            "modules": "_serialize_module",
        }.get(mapping.slug)
        serializer = getattr(self, serializer_name, None) if serializer_name else None
        if serializer is None:
            return None
        row = serializer(instance)
        return row if isinstance(row, dict) else None

    def _load_from_orm_model(self, mapping: ForwardModelMapping) -> int:
        if django_apps is None:
            return 0
        app_label, model_name = mapping.nautobot_scope.split(".", 1)
        loaded = 0
        try:
            model = django_apps.get_model(app_label, model_name)
        except Exception:
            return 0
        if model is None:
            return 0
        manager = getattr(model, "objects", None)
        if manager is None or not hasattr(manager, "all"):
            return 0
        try:
            # Materialize inside the guard: the queryset is lazy, so the DB query
            # executes here, not at .all(). When the ORM is unavailable (no DB in
            # the unit env, transient error), return what we have rather than
            # exploding — the mass-DELETE hazard from an under-loaded target is
            # handled separately by the reconcile max-delete-fraction guard.
            instances = list(manager.all())
        except DjangoOperationalError:
            return loaded
        for instance in instances:
            # Skip and continue on a single malformed row (e.g. a blank identity
            # field) rather than truncating the rest of the slice's target load,
            # which would also make the remaining objects look absent.
            try:
                row = self._serialize_orm_row(mapping, instance)
                if not row:
                    continue
                loaded += len(self.load_rows(mapping.slug, (row,)))
            except (ValueError, KeyError, TypeError):
                continue
        return loaded

    def slice_for_model(self, model_slug: str) -> NautobotTargetAdapter:
        mapping = self._get_mapping(model_slug)
        slice_adapter = NautobotTargetAdapter(model_names=(mapping.slug,))
        slice_rows = tuple(
            dict(record.fields) for record in self.loaded_records.get(mapping.slug, {}).values()
        )
        if slice_rows:
            slice_adapter.load_rows(mapping.slug, slice_rows)
        return slice_adapter

    def load(self):
        """Load current Nautobot ORM state into the adapter when available."""
        if django_apps is None:
            return self
        for mapping in self.model_mappings:
            self._load_from_orm_model(mapping)
        return self

    def count(self, model_slug: str) -> int:
        mapping = self._get_mapping(model_slug)
        return max(
            len(self.loaded_records.get(mapping.slug, {})),
            len(self.planned_writes.get(mapping.slug, {})),
            len(self.get_all(mapping.slug)),
        )

    def as_support_summary(self) -> dict[str, Any]:
        return {
            "planned_counts": {
                slug: max(
                    len(self.loaded_records.get(slug, {})),
                    len(records),
                    len(self.get_all(slug)),
                )
                for slug, records in sorted(self.planned_writes.items())
            },
            "loaded_counts": {
                slug: len(records) for slug, records in sorted(self.loaded_records.items())
            },
            "model_slugs": [mapping.slug for mapping in self.model_mappings],
        }
