"""Write-path planning for Forward rows headed into Nautobot."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .adapters import ForwardSourceAdapter
from .adapters import NautobotTargetAdapter
from ...models import ForwardConnectionProfileRecord
from .registry import ForwardModelMapping
from .write_contract import ForwardWriteContractAdvisor


@dataclass(slots=True)
class ForwardWriteOperation:
    """A single planned Nautobot write derived from a Forward row."""

    model_slug: str
    record_key: str
    nautobot_scope: str
    action: str
    fields: dict[str, Any]
    contract_version: str
    blocked_by: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_slug": self.model_slug,
            "record_key": self.record_key,
            "nautobot_scope": self.nautobot_scope,
            "action": self.action,
            "fields": dict(self.fields),
            "contract_version": self.contract_version,
            "blocked_by": list(self.blocked_by),
        }


@dataclass(slots=True)
class ForwardWritePlan:
    """Planned Nautobot writes for a set of Forward model slices."""

    operations: tuple[ForwardWriteOperation, ...] = ()
    summary: dict[str, int] = field(default_factory=dict)
    configuration_status: dict[str, Any] = field(default_factory=dict)
    slice_policies: dict[str, dict[str, str]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "operations": [operation.as_dict() for operation in self.operations],
            "summary": dict(self.summary),
            "configuration_status": dict(self.configuration_status),
            "slice_policies": {slug: dict(policy) for slug, policy in self.slice_policies.items()},
        }


class ForwardWritePlanner:
    """Compute raw Nautobot write intent from source and target adapters."""

    @staticmethod
    def _target_key(mapping: ForwardModelMapping, row: dict[str, Any]) -> str:
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = row.get(field_name)
            if value is None:
                return ""
            value_text = str(value).strip()
            if not value_text:
                return ""
            key_parts.append(value_text)
        return "|".join(key_parts)

    def plan(
        self,
        source: ForwardSourceAdapter,
        target: NautobotTargetAdapter,
        profile: ForwardConnectionProfileRecord | None = None,
    ) -> ForwardWritePlan:
        operations: list[ForwardWriteOperation] = []
        summary = {"create": 0, "update": 0, "no-change": 0, "blocked": 0}
        configuration_status: dict[str, Any] = {
            "profile_provided": profile is not None,
            "write_ready": bool(profile.write_ready) if profile is not None else False,
            "missing_defaults": list(profile.missing_write_defaults()) if profile is not None else [],
            "delete_policy": getattr(profile, "delete_policy", "ignore") if profile is not None else "ignore",
            "slice_policies": {
                mapping.slug: {
                    "write_mode": mapping.write_mode,
                    "missing_row_policy": mapping.missing_row_policy,
                }
                for mapping in source.model_mappings
            },
        }
        advisor = ForwardWriteContractAdvisor()
        for mapping in source.model_mappings:
            target_rows = {
                self._target_key(mapping, dict(item.dict())): dict(item.dict())
                for item in target.get_all(mapping.slug)
            }
            for record_key, record in source.records.get(mapping.slug, {}).items():
                readiness = advisor.readiness_for(
                    mapping,
                    profile=profile,
                    row=record.fields,
                )
                target_fields = target_rows.get(record_key)
                if target_fields is None:
                    action = "create"
                elif target_fields != record.fields:
                    action = "update"
                else:
                    action = "no-change"
                summary[action] += 1
                if readiness.blocked_by:
                    summary["blocked"] += 1
                operations.append(
                    ForwardWriteOperation(
                        model_slug=mapping.slug,
                        record_key=record_key,
                        nautobot_scope=mapping.nautobot_scope,
                        action=action,
                        fields=dict(record.fields),
                        contract_version=mapping.contract_version,
                        blocked_by=readiness.blocked_by,
                    )
                )
        return ForwardWritePlan(
            operations=tuple(operations),
            summary=summary,
            configuration_status=configuration_status,
            slice_policies={
                mapping.slug: {
                    "write_mode": mapping.write_mode,
                    "missing_row_policy": mapping.missing_row_policy,
                }
                for mapping in source.model_mappings
            },
        )
