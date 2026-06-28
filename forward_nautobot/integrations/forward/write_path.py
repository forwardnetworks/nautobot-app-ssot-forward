"""Write-path planning for Forward rows headed into Nautobot."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from ...models import ForwardConnectionProfileRecord
from .adapters import ForwardSourceAdapter, NautobotTargetAdapter
from .registry import ForwardModelMapping
from .write_contract import ForwardWriteContractAdvisor

# Fields excluded from the changed-field rollup as housekeeping noise rather than
# meaningful drift. (Our planner field dicts carry Forward source attrs, not ORM
# timestamps, so this is usually empty — kept for forward-compatibility.)
_ROLLUP_NOISE_FIELDS = frozenset({"last_updated", "created"})


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
    diff_summary: dict[str, int] = field(default_factory=dict)
    diff_detail: dict[str, Any] = field(default_factory=dict)
    configuration_status: dict[str, Any] = field(default_factory=dict)
    slice_policies: dict[str, dict[str, str]] = field(default_factory=dict)
    delta_mode: bool = False
    delta_models: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "operations": [operation.as_dict() for operation in self.operations],
            "summary": dict(self.summary),
            "diff_summary": dict(self.diff_summary),
            "diff_detail": dict(self.diff_detail),
            "configuration_status": dict(self.configuration_status),
            "slice_policies": {slug: dict(policy) for slug, policy in self.slice_policies.items()},
            "delta_mode": self.delta_mode,
            "delta_models": list(self.delta_models),
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
        diff_summary = {"create": 0, "update": 0, "no-change": 0}
        diff_detail: dict[str, Any] = {"models": {}, "changed_fields": {}}
        all_changed_fields: Counter[str] = Counter()
        configuration_status: dict[str, Any] = {
            "profile_provided": profile is not None,
            "write_ready": bool(profile.write_ready) if profile is not None else False,
            "missing_defaults": list(profile.missing_write_defaults())
            if profile is not None
            else [],
            "delete_policy": getattr(profile, "delete_policy", "ignore")
            if profile is not None
            else "ignore",
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
            model_diff_summary = {"create": 0, "update": 0, "no-change": 0}
            changed_fields: Counter[str] = Counter()
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
                    # Record WHICH fields actually changed (names only — never
                    # values — so the rollup stays redaction-safe).
                    for key, value in record.fields.items():
                        if key in _ROLLUP_NOISE_FIELDS:
                            continue
                        if target_fields.get(key) != value:
                            changed_fields[key] += 1
                else:
                    action = "no-change"
                summary[action] += 1
                diff_summary[action] += 1
                model_diff_summary[action] += 1
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
            diff_detail["models"][mapping.slug] = model_diff_summary
            if changed_fields:
                diff_detail["changed_fields"][mapping.slug] = dict(changed_fields.most_common())
                all_changed_fields.update(changed_fields)
        # Overall "top changed fields across the run" — the scan-by-eye aggregate
        # nautobot-ssot's object-by-object diff cannot produce.
        diff_detail["changed_fields_top"] = dict(all_changed_fields.most_common(20))
        return ForwardWritePlan(
            operations=tuple(operations),
            summary=summary,
            diff_summary=diff_summary,
            diff_detail=diff_detail,
            configuration_status=configuration_status,
            slice_policies={
                mapping.slug: {
                    "write_mode": mapping.write_mode,
                    "missing_row_policy": mapping.missing_row_policy,
                }
                for mapping in source.model_mappings
            },
        )
