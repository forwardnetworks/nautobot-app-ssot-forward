"""Write-contract policy for Forward-to-Nautobot planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import DELETE_POLICIES
from ...models import ForwardConnectionProfileRecord
from .registry import ForwardModelMapping


@dataclass(slots=True)
class ForwardWriteReadiness:
    """Per-slice readiness result for Nautobot persistence."""

    model_slug: str
    write_ready: bool
    blocked_by: tuple[str, ...]
    missing_contract_fields: tuple[str, ...]
    missing_profile_fields: tuple[str, ...]
    delete_policy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_slug": self.model_slug,
            "write_ready": self.write_ready,
            "blocked_by": list(self.blocked_by),
            "missing_contract_fields": list(self.missing_contract_fields),
            "missing_profile_fields": list(self.missing_profile_fields),
            "delete_policy": self.delete_policy,
        }


class ForwardWriteContractAdvisor:
    """Determine whether a slice is ready for Nautobot writes."""

    def readiness_for(
        self,
        mapping: ForwardModelMapping,
        *,
        profile: ForwardConnectionProfileRecord | None = None,
        row: dict[str, Any] | None = None,
    ) -> ForwardWriteReadiness:
        row = dict(row or {})
        profile_fields: list[str] = []
        contract_fields: list[str] = []

        if mapping.slug == "locations":
            profile_fields.extend(
                [
                    "default_location_type_name",
                    "default_location_status_name",
                ]
            )
        elif mapping.slug == "devices":
            profile_fields.extend(
                [
                    "default_device_role_name",
                    "default_device_status_name",
                ]
            )
        elif mapping.slug == "device_types":
            contract_fields.append("manufacturer")
        elif mapping.slug == "platforms":
            contract_fields.extend([])

        if profile is not None:
            missing_profile_fields = tuple(
                field_name
                for field_name in profile_fields
                if not str(getattr(profile, field_name, "") or "").strip()
            )
            delete_policy = getattr(profile, "effective_delete_policy", None) or getattr(
                profile, "delete_policy", "ignore"
            )
        else:
            missing_profile_fields = tuple(profile_fields)
            delete_policy = "ignore"
        if delete_policy not in DELETE_POLICIES:
            delete_policy = "ignore"

        missing_contract_fields = tuple(
            field_name
            for field_name in contract_fields
            if not str(row.get(field_name, "") or "").strip()
        )
        blocked_by = (*missing_profile_fields, *missing_contract_fields)
        return ForwardWriteReadiness(
            model_slug=mapping.slug,
            write_ready=not blocked_by,
            blocked_by=blocked_by,
            missing_contract_fields=missing_contract_fields,
            missing_profile_fields=missing_profile_fields,
            delete_policy=delete_policy,
        )
