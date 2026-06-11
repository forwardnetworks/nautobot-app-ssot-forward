"""DiffSync adapter helpers for the Forward integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
                target_items = list(getattr(target, "get_all", lambda _name: ()) (model_name))
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


from .diffsync_models import ForwardDevice
from .diffsync_models import ForwardDeviceType
from .diffsync_models import ForwardIPAddress
from .diffsync_models import ForwardInterface
from .diffsync_models import ForwardIPv4Prefix
from .diffsync_models import ForwardIPv6Prefix
from .diffsync_models import ForwardInventoryItem
from .diffsync_models import ForwardLocation
from .diffsync_models import ForwardModule
from .diffsync_models import ForwardPlatform
from .diffsync_models import ForwardVLAN
from .diffsync_models import ForwardVRF
from .registry import ForwardModelMapping
from .registry import CORE_MODEL_MAPPINGS
from .registry import CORE_MODEL_SLUGS
from .registry import get_model_mappings


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
        self.model_mappings: tuple[ForwardModelMapping, ...] = get_model_mappings(
            model_names
        )
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
        self.model_mappings: tuple[ForwardModelMapping, ...] = get_model_mappings(
            model_names
        )
        self._mapping_by_slug = {mapping.slug: mapping for mapping in CORE_MODEL_MAPPINGS}
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

    def plan_rows(
        self, model_slug: str, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]
    ):
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

    def count(self, model_slug: str) -> int:
        mapping = self._get_mapping(model_slug)
        return max(
            len(self.planned_writes.get(mapping.slug, {})),
            len(self.get_all(mapping.slug)),
        )

    def as_support_summary(self) -> dict[str, Any]:
        return {
            "planned_counts": {
                slug: max(len(records), len(self.get_all(slug)))
                for slug, records in sorted(self.planned_writes.items())
            },
            "model_slugs": [mapping.slug for mapping in self.model_mappings],
        }
