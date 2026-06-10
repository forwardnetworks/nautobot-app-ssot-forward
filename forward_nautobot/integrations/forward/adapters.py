"""DiffSync adapter scaffolding for the Forward integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from diffsync import Adapter
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
    class Adapter:  # type: ignore[too-many-ancestors]
        """Fallback adapter base when DiffSync is not installed."""


from .diffsync_models import ForwardDevice
from .diffsync_models import ForwardDeviceType
from .diffsync_models import ForwardLocation
from .diffsync_models import ForwardPlatform
from .registry import ForwardModelMapping
from .registry import CORE_MODEL_MAPPINGS
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

    top_level = ("locations", "platforms", "device_types", "devices")
    locations = ForwardLocation
    platforms = ForwardPlatform
    device_types = ForwardDeviceType
    devices = ForwardDevice

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
    """Target-side adapter placeholder for Nautobot inventory."""

    top_level = ("locations", "platforms", "device_types", "devices")
    locations = ForwardLocation
    platforms = ForwardPlatform
    device_types = ForwardDeviceType
    devices = ForwardDevice

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
