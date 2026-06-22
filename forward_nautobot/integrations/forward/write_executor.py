"""Nautobot write execution for Forward rows."""

from __future__ import annotations

import re
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

try:
    from django.apps import apps as django_apps
    from django.contrib.contenttypes.models import ContentType
    from django.db import transaction as django_transaction
    from django.utils.text import slugify
except Exception:  # pragma: no cover - local compatibility import path
    django_apps = None
    ContentType = None
    django_transaction = None
    slugify = None

from ...models import ForwardConnectionProfileRecord
from .registry import get_model_mapping
from .support import classify_failure
from .write_path import ForwardWriteOperation, ForwardWritePlan


def _slugify(value: str) -> str:
    if slugify is not None:
        return slugify(value)
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower())
    return re.sub(r"-+", "-", value).strip("-")


@dataclass(slots=True)
class ForwardWriteExecutionItem:
    """A single Nautobot write attempt."""

    model_slug: str
    record_key: str
    planned_action: str
    status: str
    object_label: str = ""
    blocked_by: tuple[str, ...] = ()
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_slug": self.model_slug,
            "record_key": self.record_key,
            "planned_action": self.planned_action,
            "status": self.status,
            "object_label": self.object_label,
            "blocked_by": list(self.blocked_by),
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(slots=True)
class ForwardWriteExecution:
    """Summary of a Nautobot write attempt."""

    items: tuple[ForwardWriteExecutionItem, ...] = ()
    summary: dict[str, int] = field(default_factory=dict)
    configuration_status: dict[str, Any] = field(default_factory=dict)
    failure_classification: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "items": [item.as_dict() for item in self.items],
            "summary": dict(self.summary),
            "configuration_status": dict(self.configuration_status),
            "failure_classification": self.failure_classification,
        }


class ForwardNautobotWriteBackend:
    """Nautobot ORM backend for the first Forward write slices."""

    def __init__(self, model_resolver=None):
        self.model_resolver = model_resolver or self._default_model_resolver
        # Per-run resolution caches, reset by reset_run_caches() at execute() start.
        # _named_cache: committed (app_label, model_name, name) -> obj
        # _pending_named: objects resolved during the current operation's savepoint;
        #   merged into _named_cache on success, discarded on rollback so a
        #   rolled-back FK object is never served to a later row.
        # _existing_index: slug -> {record_key -> instance}, built once per slice.
        self._named_cache: dict[tuple[str, str, str], Any] = {}
        self._pending_named: dict[tuple[str, str, str], Any] = {}
        self._existing_index: dict[str, dict[str, Any]] = {}

    def reset_run_caches(self) -> None:
        self._named_cache = {}
        self._pending_named = {}
        self._existing_index = {}

    @staticmethod
    def _savepoint():
        """A nested transaction savepoint when Django is available, else a no-op.

        Used per write operation so an IntegrityError in one row rolls back only
        that row's partial FK creations (not the whole run) and does not poison
        the surrounding transaction.
        """
        if django_transaction is not None:
            return django_transaction.atomic()
        return nullcontext()

    def _begin_op(self) -> None:
        self._pending_named = {}

    def _commit_op(self) -> None:
        self._named_cache.update(self._pending_named)
        self._pending_named = {}

    def _rollback_op(self) -> None:
        self._pending_named = {}

    @staticmethod
    def _default_model_resolver(app_label: str, model_name: str):
        if django_apps is None:
            return None
        return django_apps.get_model(app_label, model_name)

    @property
    def available(self) -> bool:
        return self.model_resolver is not None and django_apps is not None

    def resolve_model(self, app_label: str, model_name: str):
        model = self.model_resolver(app_label, model_name)
        if model is None:
            raise LookupError(f"Unable to resolve Nautobot model {app_label}.{model_name}.")
        return model

    def _get_or_create_named(
        self,
        app_label: str,
        model_name: str,
        value: str,
        *,
        content_type_target: tuple[str, str] | None = None,
    ):
        cache_key = (app_label, model_name, str(value))
        cached = self._pending_named.get(cache_key)
        if cached is None:
            cached = self._named_cache.get(cache_key)
        if cached is not None:
            # Cache hit also short-circuits the content_types.add m2m write, which
            # is established the first time a given name is resolved this run.
            return cached
        model = self.resolve_model(app_label, model_name)
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError(f"Nautobot model {app_label}.{model_name} has no manager.")
        obj, _created = manager.get_or_create(name=value)
        if (
            content_type_target is not None
            and hasattr(obj, "content_types")
            and ContentType is not None
        ):
            target_model = self.resolve_model(*content_type_target)
            content_type = ContentType.objects.get_for_model(target_model)
            ct_manager = obj.content_types
            if hasattr(ct_manager, "add"):
                ct_manager.add(content_type)
        self._pending_named[cache_key] = obj
        return obj

    @staticmethod
    def _model_field_names(model) -> set[str]:
        meta = getattr(model, "_meta", None)
        fields = getattr(meta, "fields", None)
        if not fields:
            return set()
        names: set[str] = set()
        for model_field in fields:
            name = getattr(model_field, "name", "")
            if name:
                names.add(str(name))
        return names

    @classmethod
    def _filtered_updates(cls, model, updates: dict[str, Any]) -> dict[str, Any]:
        field_names = cls._model_field_names(model)
        if not field_names:
            return dict(updates)
        return {
            field_name: value for field_name, value in updates.items() if field_name in field_names
        }

    @classmethod
    def _first_existing_field(cls, model, *field_names: str) -> str | None:
        available = cls._model_field_names(model)
        if not available:
            return next((name for name in field_names if name), None)
        for field_name in field_names:
            if field_name in available:
                return field_name
        return None

    @staticmethod
    def _sync_fields(instance, updates: dict[str, Any]) -> bool:
        allowed_fields = ForwardNautobotWriteBackend._model_field_names(instance)
        changed_fields: list[str] = []
        for field_name, value in updates.items():
            if allowed_fields and field_name not in allowed_fields:
                continue
            if getattr(instance, field_name, None) != value:
                setattr(instance, field_name, value)
                changed_fields.append(field_name)
        if changed_fields:
            # Limit the write (and the signal/changelog surface) to the fields that
            # actually changed. Safe because get_or_create already saved the row, so
            # the instance has a pk, and changed_fields are concrete model fields.
            try:
                instance.save(update_fields=changed_fields)
            except (TypeError, ValueError):  # managers/instances without update_fields
                instance.save()
        return bool(changed_fields)

    @staticmethod
    def _instance_value(value: Any) -> Any:
        if hasattr(value, "name"):
            return value.name
        return value

    def _mapping_for_slug(self, model_slug: str):
        try:
            return get_model_mapping(model_slug)
        except Exception:
            return None

    def _record_key_for_instance(self, model_slug: str, instance) -> str:
        mapping = self._mapping_for_slug(model_slug)
        if mapping is None:
            return ""
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = self._instance_value(getattr(instance, field_name, None))
            if value is None:
                return ""
            value_text = str(value).strip()
            if not value_text:
                return ""
            key_parts.append(value_text)
        return "|".join(key_parts)

    def _iter_existing_instances(self, model_slug: str):
        mapping = self._mapping_for_slug(model_slug)
        if mapping is None:
            return ()
        model = self.resolve_model(*mapping.nautobot_scope.split(".", 1))
        manager = getattr(model, "objects", None)
        if manager is None:
            return ()
        if hasattr(manager, "all"):
            try:
                return list(manager.all())
            except Exception:
                return ()
        if hasattr(manager, "records"):
            return list(manager.records.values())
        return ()

    def _existing_index_for(self, model_slug: str) -> dict[str, Any]:
        """record_key -> instance for a slice, materialized once per run.

        Replaces the previous per-delete full-table scan (O(deletes x table))
        with a single pass; reused by both explicit deletes and reconcile_missing.
        """
        index = self._existing_index.get(model_slug)
        if index is None:
            index = {}
            for instance in self._iter_existing_instances(model_slug):
                record_key = self._record_key_for_instance(model_slug, instance)
                if record_key:
                    index.setdefault(record_key, instance)
            self._existing_index[model_slug] = index
        return index

    def _mark_inactive(self, instance):
        if not hasattr(instance, "status"):
            raise ValueError("Model does not expose a status field for mark_inactive.")
        inactive = self._get_or_create_named("extras", "Status", "Inactive")
        self._sync_fields(instance, {"status": inactive})
        return inactive

    def reconcile_missing(
        self,
        model_slug: str,
        source_keys: set[str],
        delete_policy: str,
    ) -> tuple[ForwardWriteExecutionItem, ...]:
        if delete_policy not in {"delete", "mark_inactive"}:
            return ()
        items: list[ForwardWriteExecutionItem] = []
        for record_key, instance in self._existing_index_for(model_slug).items():
            if not record_key or record_key in source_keys:
                continue
            try:
                if delete_policy == "delete":
                    if hasattr(instance, "delete"):
                        instance.delete()
                        items.append(
                            ForwardWriteExecutionItem(
                                model_slug=model_slug,
                                record_key=record_key,
                                planned_action="delete",
                                status="deleted",
                                object_label=str(getattr(instance, "name", "") or record_key),
                            )
                        )
                    else:
                        items.append(
                            ForwardWriteExecutionItem(
                                model_slug=model_slug,
                                record_key=record_key,
                                planned_action="delete",
                                status="skipped",
                                message="Model does not expose delete().",
                            )
                        )
                else:
                    self._mark_inactive(instance)
                    items.append(
                        ForwardWriteExecutionItem(
                            model_slug=model_slug,
                            record_key=record_key,
                            planned_action="mark_inactive",
                            status="deactivated",
                            object_label=str(getattr(instance, "name", "") or record_key),
                        )
                    )
            except Exception as exc:  # pragma: no cover - defensive
                items.append(
                    ForwardWriteExecutionItem(
                        model_slug=model_slug,
                        record_key=record_key,
                        planned_action=delete_policy,
                        status="error",
                        message=str(exc),
                    )
                )
        return tuple(items)

    def _apply_delete_policy(
        self,
        *,
        model_slug: str,
        record_key: str,
        instance: Any,
        delete_policy: str,
        planned_action: str = "delete",
    ) -> ForwardWriteExecutionItem:
        if delete_policy not in {"delete", "mark_inactive"}:
            return ForwardWriteExecutionItem(
                model_slug=model_slug,
                record_key=record_key,
                planned_action=planned_action,
                status="skipped",
                object_label=str(getattr(instance, "name", "") or record_key),
                message="Delete policy is ignore; explicit delete was skipped.",
            )
        try:
            if delete_policy == "delete":
                if hasattr(instance, "delete"):
                    instance.delete()
                    return ForwardWriteExecutionItem(
                        model_slug=model_slug,
                        record_key=record_key,
                        planned_action=planned_action,
                        status="deleted",
                        object_label=str(getattr(instance, "name", "") or record_key),
                    )
                return ForwardWriteExecutionItem(
                    model_slug=model_slug,
                    record_key=record_key,
                    planned_action=planned_action,
                    status="skipped",
                    object_label=str(getattr(instance, "name", "") or record_key),
                    message="Model does not expose delete().",
                )
            self._mark_inactive(instance)
            return ForwardWriteExecutionItem(
                model_slug=model_slug,
                record_key=record_key,
                planned_action=planned_action,
                status="deactivated",
                object_label=str(getattr(instance, "name", "") or record_key),
            )
        except Exception as exc:  # pragma: no cover - defensive
            return ForwardWriteExecutionItem(
                model_slug=model_slug,
                record_key=record_key,
                planned_action=planned_action,
                status="error",
                object_label=str(getattr(instance, "name", "") or record_key),
                message=str(exc),
            )

    def _delete_instance_by_record_key(
        self,
        model_slug: str,
        record_key: str,
        delete_policy: str,
        *,
        planned_action: str = "delete",
    ) -> ForwardWriteExecutionItem:
        instance = self._existing_index_for(model_slug).get(record_key)
        if instance is not None:
            return self._apply_delete_policy(
                model_slug=model_slug,
                record_key=record_key,
                instance=instance,
                delete_policy=delete_policy,
                planned_action=planned_action,
            )
        return ForwardWriteExecutionItem(
            model_slug=model_slug,
            record_key=record_key,
            planned_action=planned_action,
            status="skipped",
            message="No matching Nautobot object exists for the delete operation.",
        )

    def _upsert_location(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError("Location row is missing `name`.")
        location_type = self._get_or_create_named(
            "dcim",
            "LocationType",
            profile.default_location_type_name,
            content_type_target=("dcim", "Location"),
        )
        status = self._get_or_create_named(
            "extras",
            "Status",
            profile.default_location_status_name,
            content_type_target=("dcim", "Location"),
        )
        model = self.resolve_model("dcim", "Location")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Location model has no manager.")
        obj, created = manager.get_or_create(
            name=name,
            defaults={
                "location_type": location_type,
                "status": status,
            },
        )
        self._sync_fields(
            obj,
            {
                "location_type": location_type,
                "status": status,
            },
        )
        return obj, created

    def _upsert_platform(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        name = str(row.get("name") or "").strip()
        manufacturer_name = str(row.get("manufacturer") or row.get("vendor") or "").strip()
        if not name:
            raise ValueError("Platform row is missing `name`.")
        if not manufacturer_name:
            raise ValueError("Platform row is missing `manufacturer`.")
        manufacturer = self._get_or_create_named("dcim", "Manufacturer", manufacturer_name)
        model = self.resolve_model("dcim", "Platform")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Platform model has no manager.")
        obj, created = manager.get_or_create(
            name=name,
            defaults={"manufacturer": manufacturer},
        )
        self._sync_fields(obj, {"manufacturer": manufacturer})
        return obj, created

    def _upsert_device_type(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        manufacturer_name = str(row.get("manufacturer") or row.get("vendor") or "").strip()
        model_name = str(row.get("model") or row.get("name") or "").strip()
        if not manufacturer_name:
            raise ValueError("Device type row is missing `manufacturer`.")
        if not model_name:
            raise ValueError("Device type row is missing `model`.")
        manufacturer = self._get_or_create_named("dcim", "Manufacturer", manufacturer_name)
        device_type_model = self.resolve_model("dcim", "DeviceType")
        manager = getattr(device_type_model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot DeviceType model has no manager.")
        slug = str(row.get("slug") or _slugify(f"{manufacturer_name}-{model_name}"))
        defaults = self._filtered_updates(device_type_model, {"slug": slug})
        obj, created = manager.get_or_create(
            manufacturer=manufacturer,
            model=model_name,
            defaults=defaults,
        )
        self._sync_fields(obj, defaults)
        return obj, created

    def _upsert_device(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        name = str(row.get("name") or "").strip()
        location_name = str(row.get("location") or "").strip()
        vendor_name = str(row.get("vendor") or row.get("manufacturer") or "").strip()
        platform_name = str(row.get("model") or "").strip()
        device_type_name = str(row.get("device_type") or row.get("model") or "").strip()
        if not name:
            raise ValueError("Device row is missing `name`.")
        if not location_name:
            raise ValueError("Device row is missing `location`.")
        if not vendor_name:
            raise ValueError("Device row is missing `vendor`.")
        if not platform_name:
            raise ValueError("Device row is missing `model`.")
        if not device_type_name:
            raise ValueError("Device row is missing `device_type`.")
        location = self._get_or_create_named("dcim", "Location", location_name)
        platform = self._get_or_create_named("dcim", "Platform", platform_name)
        manufacturer = self._get_or_create_named("dcim", "Manufacturer", vendor_name)
        device_type = self._lookup_device_type(manufacturer, device_type_name)
        device_role = self._get_or_create_named(
            "extras",
            "Role",
            profile.default_device_role_name,
            content_type_target=("dcim", "Device"),
        )
        status = self._get_or_create_named(
            "extras",
            "Status",
            profile.default_device_status_name,
            content_type_target=("dcim", "Device"),
        )
        device_model = self.resolve_model("dcim", "Device")
        manager = getattr(device_model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Device model has no manager.")
        role_field_name = self._first_existing_field(device_model, "role", "device_role")
        if role_field_name is None:
            raise LookupError("Nautobot Device model has no role field.")
        defaults = self._filtered_updates(
            device_model,
            {
                "location": location,
                "platform": platform,
                "device_type": device_type,
                role_field_name: device_role,
                "status": status,
            },
        )
        obj, created = manager.get_or_create(
            name=name,
            defaults=defaults,
        )
        self._sync_fields(obj, defaults)
        return obj, created

    def _lookup_device_type(self, manufacturer, device_type_name: str):
        device_type_model = self.resolve_model("dcim", "DeviceType")
        manager = getattr(device_type_model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot DeviceType model has no manager.")
        defaults = self._filtered_updates(
            device_type_model,
            {"slug": _slugify(device_type_name)},
        )
        try:
            return manager.get(manufacturer=manufacturer, model=device_type_name)
        except Exception:
            return manager.get_or_create(
                manufacturer=manufacturer,
                model=device_type_name,
                defaults=defaults,
            )[0]

    @staticmethod
    def _status_name(value: Any) -> str:
        text = str(value or "").strip()
        return text.title() if text else "Active"

    def _get_existing(self, app_label: str, model_name: str, **lookup):
        model = self.resolve_model(app_label, model_name)
        manager = getattr(model, "objects", None)
        if manager is None:
            return None
        try:
            return manager.get(**lookup)
        except Exception:
            return None

    def _resolve_status(self, name: str):
        return self._get_or_create_named("extras", "Status", self._status_name(name))

    def _resolve_device(self, device_name: str):
        device = self._get_existing("dcim", "Device", name=device_name)
        if device is None:
            raise ValueError(f"Device `{device_name}` was not found.")
        return device

    def _resolve_interface(self, device, interface_name: str):
        interface = self._get_existing("dcim", "Interface", device=device, name=interface_name)
        if interface is None:
            return None
        return interface

    def _resolve_vrf(self, vrf_name: str):
        vrf_name = str(vrf_name or "").strip()
        if not vrf_name or vrf_name == "default":
            return None
        model = self.resolve_model("ipam", "VRF")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot VRF model has no manager.")
        obj, _created = manager.get_or_create(
            name=vrf_name,
            defaults={
                "rd": "",
                "description": "",
                "enforce_unique": False,
            },
        )
        self._sync_fields(
            obj,
            {
                "rd": "",
                "description": "",
                "enforce_unique": False,
            },
        )
        return obj

    def _resolve_location(self, location_name: str, profile: ForwardConnectionProfileRecord):
        location_name = str(location_name or "").strip()
        if not location_name:
            return None
        location_type_name = str(profile.default_location_type_name or "").strip()
        location_status_name = str(profile.default_location_status_name or "").strip()
        if not location_type_name or not location_status_name:
            return self._get_existing("dcim", "Location", name=location_name)
        location_type = self._get_or_create_named(
            "dcim",
            "LocationType",
            location_type_name,
            content_type_target=("dcim", "Location"),
        )
        status = self._resolve_status(location_status_name)
        model = self.resolve_model("dcim", "Location")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Location model has no manager.")
        obj, _created = manager.get_or_create(
            name=location_name,
            defaults={
                "location_type": location_type,
                "status": status,
            },
        )
        self._sync_fields(
            obj,
            {
                "location_type": location_type,
                "status": status,
            },
        )
        return obj

    def _resolve_vlan(self, row: dict[str, Any], profile: ForwardConnectionProfileRecord):
        vid = int(row["vid"])
        location = self._resolve_location(row.get("site"), profile)
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "VLAN")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot VLAN model has no manager.")
        lookup = {"vid": vid}
        if location is not None:
            lookup["location"] = location
        obj, _created = manager.get_or_create(
            **lookup,
            defaults={
                "name": str(row.get("name") or ""),
                "status": status,
            },
        )
        self._sync_fields(
            obj,
            {
                "name": str(row.get("name") or ""),
                "status": status,
                **({"location": location} if location is not None else {}),
            },
        )
        return obj

    def _resolve_prefix(self, row: dict[str, Any]):
        prefix_value = str(row.get("prefix") or "").strip()
        if not prefix_value:
            raise ValueError("Prefix row is missing `prefix`.")
        vrf = self._resolve_vrf(row.get("vrf") or "")
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "Prefix")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Prefix model has no manager.")
        lookup = {"prefix": prefix_value}
        if vrf is not None:
            lookup["vrf"] = vrf
        obj, _created = manager.get_or_create(
            **lookup,
            defaults={"status": status},
        )
        self._sync_fields(
            obj,
            {
                "status": status,
                **({"vrf": vrf} if vrf is not None else {}),
            },
        )
        return obj

    def _resolve_ip_address(self, row: dict[str, Any]):
        device = self._resolve_device(row["device"])
        interface = self._resolve_interface(device, row["interface"])
        if interface is None:
            raise ValueError(
                f"Interface `{row['interface']}` was not found on device `{device.name}`."
            )
        address_value = str(row.get("address") or "").strip()
        if not address_value:
            raise ValueError("IP address row is missing `address`.")
        vrf = self._resolve_vrf(row.get("vrf") or "")
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "IPAddress")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot IPAddress model has no manager.")
        lookup = {"address": address_value}
        if vrf is not None:
            lookup["vrf"] = vrf
        obj, _created = manager.get_or_create(
            **lookup,
            defaults={
                "status": status,
                "assigned_object": interface,
            },
        )
        self._sync_fields(
            obj,
            {
                "status": status,
                "assigned_object": interface,
                **({"vrf": vrf} if vrf is not None else {}),
            },
        )
        return obj

    def _resolve_inventory_item(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        device = self._resolve_device(row["device"])
        role = self._get_or_create_named(
            "extras",
            "Role",
            str(row.get("role") or "").strip(),
            content_type_target=("dcim", "InventoryItem"),
        )
        manufacturer_name = str(row.get("manufacturer") or "").strip()
        manufacturer = (
            self._get_or_create_named("dcim", "Manufacturer", manufacturer_name)
            if manufacturer_name
            else None
        )
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("dcim", "InventoryItem")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot InventoryItem model has no manager.")
        lookup = {"device": device, "name": str(row.get("name") or "").strip()}
        obj, created = manager.get_or_create(
            **lookup,
            defaults={
                "label": str(row.get("label") or ""),
                "part_id": str(row.get("part_id") or ""),
                "serial": str(row.get("serial") or ""),
                "asset_tag": row.get("asset_tag") or None,
                "status": status,
                "role": role,
                "manufacturer": manufacturer,
                "discovered": bool(row.get("discovered", True)),
                "description": str(row.get("description") or ""),
            },
        )
        self._sync_fields(
            obj,
            {
                "label": str(row.get("label") or ""),
                "part_id": str(row.get("part_id") or ""),
                "serial": str(row.get("serial") or ""),
                "asset_tag": row.get("asset_tag") or None,
                "status": status,
                "role": role,
                "manufacturer": manufacturer,
                "discovered": bool(row.get("discovered", True)),
                "description": str(row.get("description") or ""),
            },
        )
        return obj, created

    def _resolve_module(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        device = self._resolve_device(row["device"])
        module_bay_name = str(row.get("module_bay") or "").strip()
        if not module_bay_name:
            raise ValueError("Module row is missing `module_bay`.")
        manufacturer_name = str(row.get("manufacturer") or "").strip()
        if not manufacturer_name:
            raise ValueError("Module row is missing `manufacturer`.")
        manufacturer = self._get_or_create_named("dcim", "Manufacturer", manufacturer_name)
        module_type_model = self.resolve_model("dcim", "ModuleType")
        module_type_manager = getattr(module_type_model, "objects", None)
        if module_type_manager is None:
            raise LookupError("Nautobot ModuleType model has no manager.")
        module_type, _created = module_type_manager.get_or_create(
            manufacturer=manufacturer,
            model=str(row.get("model") or module_bay_name),
            defaults={"part_number": str(row.get("part_number") or "")},
        )
        self._sync_fields(
            module_type,
            {
                "part_number": str(row.get("part_number") or ""),
            },
        )
        module_bay_model = self.resolve_model("dcim", "ModuleBay")
        module_bay_manager = getattr(module_bay_model, "objects", None)
        if module_bay_manager is None:
            raise LookupError("Nautobot ModuleBay model has no manager.")
        module_bay, _created = module_bay_manager.get_or_create(
            device=device,
            position=module_bay_name,
            defaults={},
        )
        status = self._resolve_status(row.get("status") or "active")
        module_model = self.resolve_model("dcim", "Module")
        module_manager = getattr(module_model, "objects", None)
        if module_manager is None:
            raise LookupError("Nautobot Module model has no manager.")
        lookup = {"device": device, "module_bay": module_bay}
        obj, created = module_manager.get_or_create(
            **lookup,
            defaults={
                "module_type": module_type,
                "status": status,
                "serial": str(row.get("serial") or ""),
                "asset_tag": row.get("asset_tag") or None,
            },
        )
        self._sync_fields(
            obj,
            {
                "module_type": module_type,
                "status": status,
                "serial": str(row.get("serial") or ""),
                "asset_tag": row.get("asset_tag") or None,
            },
        )
        return obj, created

    def _upsert_interface(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        device = self._resolve_device(row["device"])
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError("Interface row is missing `name`.")
        model = self.resolve_model("dcim", "Interface")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Interface model has no manager.")
        defaults = {
            "type": str(row.get("type") or "other"),
            "enabled": bool(row.get("enabled", True)),
            "mtu": row.get("mtu") or None,
            "description": str(row.get("description") or ""),
            "speed": row.get("speed") or None,
        }
        lag_name = str(row.get("lag") or "").strip()
        if lag_name:
            lag = self._resolve_interface(device, lag_name)
            if lag is not None:
                defaults["lag"] = lag
        obj, created = manager.get_or_create(
            device=device,
            name=name,
            defaults=defaults,
        )
        self._sync_fields(obj, defaults)
        return obj, created

    def _upsert_vlan(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        vid = int(row.get("vid"))
        location = self._resolve_location(row.get("site"), profile)
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "VLAN")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot VLAN model has no manager.")
        lookup = {"vid": vid}
        if location is not None:
            lookup["location"] = location
        defaults = {"name": str(row.get("name") or ""), "status": status}
        obj, created = manager.get_or_create(**lookup, defaults=defaults)
        updates = dict(defaults)
        if location is not None:
            updates["location"] = location
        self._sync_fields(obj, updates)
        return obj, created

    def _upsert_vrf(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        name = str(row.get("name") or "").strip()
        if not name:
            raise ValueError("VRF row is missing `name`.")
        model = self.resolve_model("ipam", "VRF")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot VRF model has no manager.")
        defaults = {
            "rd": str(row.get("rd") or ""),
            "description": str(row.get("description") or ""),
            "enforce_unique": bool(row.get("enforce_unique", False)),
        }
        obj, created = manager.get_or_create(name=name, defaults=defaults)
        self._sync_fields(obj, defaults)
        return obj, created

    def _upsert_prefix(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        prefix_value = str(row.get("prefix") or "").strip()
        if not prefix_value:
            raise ValueError("Prefix row is missing `prefix`.")
        vrf = self._resolve_vrf(row.get("vrf") or "")
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "Prefix")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot Prefix model has no manager.")
        lookup = {"prefix": prefix_value}
        if vrf is not None:
            lookup["vrf"] = vrf
        defaults = {"status": status}
        obj, created = manager.get_or_create(**lookup, defaults=defaults)
        updates = {"status": status}
        if vrf is not None:
            updates["vrf"] = vrf
        self._sync_fields(obj, updates)
        return obj, created

    def _upsert_ip_address(
        self, operation: ForwardWriteOperation, profile: ForwardConnectionProfileRecord
    ):
        row = dict(operation.fields)
        device = self._resolve_device(row["device"])
        interface = self._resolve_interface(device, row["interface"])
        if interface is None:
            raise ValueError(
                f"Interface `{row['interface']}` was not found on device `{device.name}`."
            )
        address_value = str(row.get("address") or "").strip()
        if not address_value:
            raise ValueError("IP address row is missing `address`.")
        vrf = self._resolve_vrf(row.get("vrf") or "")
        status = self._resolve_status(row.get("status") or "active")
        model = self.resolve_model("ipam", "IPAddress")
        manager = getattr(model, "objects", None)
        if manager is None:
            raise LookupError("Nautobot IPAddress model has no manager.")
        lookup = {"address": address_value}
        if vrf is not None:
            lookup["vrf"] = vrf
        defaults = {"status": status, "assigned_object": interface}
        obj, created = manager.get_or_create(**lookup, defaults=defaults)
        updates = {"status": status, "assigned_object": interface}
        if vrf is not None:
            updates["vrf"] = vrf
        self._sync_fields(obj, updates)
        return obj, created

    def apply_operation(
        self,
        operation: ForwardWriteOperation,
        profile: ForwardConnectionProfileRecord,
    ) -> ForwardWriteExecutionItem:
        if operation.blocked_by:
            return ForwardWriteExecutionItem(
                model_slug=operation.model_slug,
                record_key=operation.record_key,
                planned_action=operation.action,
                status="blocked",
                blocked_by=operation.blocked_by,
                message="Operation blocked by write readiness constraints.",
            )
        if not self.available:
            return ForwardWriteExecutionItem(
                model_slug=operation.model_slug,
                record_key=operation.record_key,
                planned_action=operation.action,
                status="skipped",
                message="Nautobot ORM is unavailable in the current environment.",
            )
        if operation.action == "delete":
            return self._delete_instance_by_record_key(
                operation.model_slug,
                operation.record_key,
                getattr(profile, "effective_delete_policy", "ignore"),
                planned_action=operation.action,
            )
        mapping = self._mapping_for_slug(operation.model_slug)
        handler_name = getattr(mapping, "write_handler", "") if mapping is not None else ""
        handler = getattr(self, handler_name, None) if handler_name else None
        if handler is None:
            return ForwardWriteExecutionItem(
                model_slug=operation.model_slug,
                record_key=operation.record_key,
                planned_action=operation.action,
                status="skipped",
                message="No Nautobot writer is registered for this slice yet.",
            )
        # Run the handler inside a savepoint so a failure rolls back this row's
        # partial FK scaffolding instead of leaving orphans (and so a caught
        # IntegrityError does not poison the surrounding run-level transaction).
        self._begin_op()
        try:
            with self._savepoint():
                obj, created = handler(operation, profile)
        except Exception as exc:  # pragma: no cover - exercised via targeted tests
            self._rollback_op()
            return ForwardWriteExecutionItem(
                model_slug=operation.model_slug,
                record_key=operation.record_key,
                planned_action=operation.action,
                status="error",
                message=str(exc),
            )
        self._commit_op()
        status = "created" if created else "updated"
        if operation.action == "no-change":
            status = "no-change"
        return ForwardWriteExecutionItem(
            model_slug=operation.model_slug,
            record_key=operation.record_key,
            planned_action=operation.action,
            status=status,
            object_label=getattr(obj, "name", "") or str(getattr(obj, "pk", "")),
            details={"id": str(getattr(obj, "pk", ""))},
        )


class ForwardNautobotWriteExecutor:
    """Execute a planned write against Nautobot."""

    def __init__(self, backend: ForwardNautobotWriteBackend | None = None):
        self.backend = backend or ForwardNautobotWriteBackend()

    def execute(
        self,
        plan: ForwardWritePlan,
        profile: ForwardConnectionProfileRecord | None,
    ) -> ForwardWriteExecution:
        summary = {
            "created": 0,
            "updated": 0,
            "no-change": 0,
            "blocked": 0,
            "skipped": 0,
            "deleted": 0,
            "deactivated": 0,
            "error": 0,
        }
        items: list[ForwardWriteExecutionItem] = []
        resolved_profile = profile or ForwardConnectionProfileRecord(name="runtime")
        source_keys_by_slug: dict[str, set[str]] = {}

        def _tally(item: ForwardWriteExecutionItem) -> None:
            summary[item.status] = summary.get(item.status, 0) + 1
            items.append(item)

        # One run-level transaction so a hard failure (crash/OOM/IntegrityError that
        # escapes a savepoint) rolls the whole sync back instead of leaving Nautobot
        # half-written; per-operation savepoints inside apply_operation give per-row
        # isolation within it. No-op context when Django is unavailable (unit tests).
        self.backend.reset_run_caches()
        run_atomic = (
            django_transaction.atomic() if django_transaction is not None else nullcontext()
        )
        with run_atomic:
            for operation in plan.operations:
                if operation.action != "delete":
                    source_keys_by_slug.setdefault(operation.model_slug, set()).add(
                        operation.record_key
                    )
                _tally(self.backend.apply_operation(operation, resolved_profile))
            delete_policy = getattr(resolved_profile, "effective_delete_policy", "ignore")
            delta_models = set(getattr(plan, "delta_models", ()) or ())
            if plan.delta_mode and not delta_models:
                delta_models = set(source_keys_by_slug)
            if delete_policy in {"delete", "mark_inactive"}:
                for model_slug, source_keys in source_keys_by_slug.items():
                    if model_slug in delta_models:
                        continue
                    for item in self.backend.reconcile_missing(
                        model_slug,
                        source_keys,
                        delete_policy,
                    ):
                        _tally(item)
        failure_classification = (
            "clean"
            if summary["error"] == 0 and summary["blocked"] == 0
            else "row-blocked"
            if summary["blocked"]
            else "error"
        )
        if profile is not None and not profile.write_ready:
            failure_classification = classify_failure(
                write_summary=plan.summary,
                configuration_status=plan.configuration_status,
            )
        return ForwardWriteExecution(
            items=tuple(items),
            summary=summary,
            configuration_status=dict(plan.configuration_status),
            failure_classification=failure_classification,
        )


ForwardNautobotWriteExecutionItem = ForwardWriteExecutionItem
ForwardNautobotWriteExecution = ForwardWriteExecution
