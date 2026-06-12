"""Persistent plugin configuration helpers for Forward Nautobot."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from collections.abc import Mapping
from typing import Any

from .integrations.forward.models import ForwardConnectionSettings
from .integrations.forward.models import LATEST_PROCESSED_SNAPSHOT

DELETE_POLICIES: tuple[str, ...] = ("ignore", "mark_inactive", "delete")
WRITE_DEFAULT_FIELD_NAMES: tuple[str, ...] = (
    "default_location_type_name",
    "default_location_status_name",
    "default_device_role_name",
    "default_device_status_name",
)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on", "y"}


def _coerce_models(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value or "").split(",")
    return tuple(
        str(item).strip()
        for item in items
        if str(item).strip()
    )

try:
    from django.db import models
    from nautobot.apps.models import BaseModel
except Exception:  # pragma: no cover - local compatibility import path
    models = None

    class BaseModel:  # type: ignore[too-many-ancestors]
        """Fallback base class when Nautobot is not installed locally."""


@dataclass(slots=True)
class ForwardProfileStatus:
    """Read-only profile readiness summary for the UI."""

    name: str
    last_run: str = "not recorded"
    write_ready: bool = False
    missing_defaults: tuple[str, ...] = ()
    delete_policy: str = "ignore"
    enabled_models: tuple[str, ...] = ()
    network_id: str = ""
    snapshot_id: str = ""
    base_url: str = "https://fwd.app"
    is_default: bool = False
    last_run_at: str = ""
    last_failure: str = ""
    last_support_bundle: str = ""
    last_query_reference: str = ""
    last_query_mode: str = ""
    last_snapshot_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "last_run": self.last_run,
            "write_ready": self.write_ready,
            "missing_defaults": list(self.missing_defaults),
            "delete_policy": self.delete_policy,
            "enabled_models": list(self.enabled_models),
            "network_id": self.network_id,
            "snapshot_id": self.snapshot_id,
            "base_url": self.base_url,
            "is_default": self.is_default,
            "last_run_at": self.last_run_at,
            "last_failure": self.last_failure,
            "last_support_bundle": self.last_support_bundle,
            "last_query_reference": self.last_query_reference,
            "last_query_mode": self.last_query_mode,
            "last_snapshot_id": self.last_snapshot_id,
        }


@dataclass(slots=True)
class ForwardConnectionProfileRecord:
    """Serializable plugin configuration row for a Forward connection."""

    name: str
    base_url: str = "https://fwd.app"
    username: str = ""
    password: str = ""
    network_id: str = ""
    snapshot_id: str = LATEST_PROCESSED_SNAPSHOT
    enabled_models: tuple[str, ...] = ()
    query_contract_version: str = "v1"
    default_location_type_name: str = ""
    default_location_status_name: str = ""
    default_device_role_name: str = ""
    default_device_status_name: str = ""
    delete_policy: str = "ignore"
    is_default: bool = False
    last_run_at: str = ""
    last_failure: str = ""
    last_support_bundle: str = ""
    last_query_reference: str = ""
    last_query_mode: str = ""
    last_snapshot_id: str = ""

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        default_name: str = "job-profile",
        existing: "ForwardConnectionProfileRecord | None" = None,
    ) -> "ForwardConnectionProfileRecord":
        existing = existing or None
        base = existing.as_dict() if existing is not None else {}
        name = str(data.get("name") or base.get("name") or default_name).strip() or default_name
        base_url = str(data.get("base_url") or base.get("base_url") or "https://fwd.app").strip() or "https://fwd.app"
        username = str(data.get("username") or base.get("username") or "").strip()
        password = str(data.get("password") or base.get("password") or "").strip()
        network_id = str(data.get("network_id") or base.get("network_id") or "").strip()
        snapshot_id = str(
            data.get("snapshot_id") or base.get("snapshot_id") or LATEST_PROCESSED_SNAPSHOT
        ).strip() or LATEST_PROCESSED_SNAPSHOT
        enabled_models = _coerce_models(data.get("enabled_models") or base.get("enabled_models") or ())
        query_contract_version = str(
            data.get("query_contract_version")
            or base.get("query_contract_version")
            or "v1"
        ).strip() or "v1"
        default_location_type_name = str(
            data.get("default_location_type_name")
            or base.get("default_location_type_name")
            or ""
        ).strip()
        default_location_status_name = str(
            data.get("default_location_status_name")
            or base.get("default_location_status_name")
            or ""
        ).strip()
        default_device_role_name = str(
            data.get("default_device_role_name")
            or base.get("default_device_role_name")
            or ""
        ).strip()
        default_device_status_name = str(
            data.get("default_device_status_name")
            or base.get("default_device_status_name")
            or ""
        ).strip()
        delete_policy = str(data.get("delete_policy") or base.get("delete_policy") or "ignore").strip() or "ignore"
        is_default = _coerce_bool(data.get("is_default") or base.get("is_default") or False)
        return cls(
            name=name,
            base_url=base_url,
            username=username,
            password=password,
            network_id=network_id,
            snapshot_id=snapshot_id,
            enabled_models=enabled_models,
            query_contract_version=query_contract_version,
            default_location_type_name=default_location_type_name,
            default_location_status_name=default_location_status_name,
            default_device_role_name=default_device_role_name,
            default_device_status_name=default_device_status_name,
            delete_policy=delete_policy,
            is_default=is_default,
            last_run_at=str(data.get("last_run_at") or base.get("last_run_at") or ""),
            last_failure=str(data.get("last_failure") or base.get("last_failure") or ""),
            last_support_bundle=str(
                data.get("last_support_bundle") or base.get("last_support_bundle") or ""
            ),
            last_query_reference=str(
                data.get("last_query_reference")
                or base.get("last_query_reference")
                or base.get("last_support_bundle")
                or ""
            ),
            last_query_mode=str(
                data.get("last_query_mode")
                or base.get("last_query_mode")
                or ""
            ),
            last_snapshot_id=str(data.get("last_snapshot_id") or base.get("last_snapshot_id") or ""),
        )

    def to_connection_settings(self) -> ForwardConnectionSettings:
        return ForwardConnectionSettings(
            base_url=self.base_url,
            username=self.username,
            password=self.password,
            network_id=self.network_id,
            snapshot_id=self.snapshot_id or LATEST_PROCESSED_SNAPSHOT,
        )

    def with_enabled_models(self, enabled_models: tuple[str, ...] | list[str]):
        return replace(
            self,
            enabled_models=tuple(
                str(name).strip()
                for name in enabled_models
                if str(name).strip()
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "username": self.username,
            "password": self.password,
            "network_id": self.network_id,
            "snapshot_id": self.snapshot_id,
            "enabled_models": list(self.enabled_models),
            "query_contract_version": self.query_contract_version,
            "default_location_type_name": self.default_location_type_name,
            "default_location_status_name": self.default_location_status_name,
            "default_device_role_name": self.default_device_role_name,
            "default_device_status_name": self.default_device_status_name,
            "delete_policy": self.delete_policy,
            "is_default": self.is_default,
            "last_run_at": self.last_run_at,
            "last_failure": self.last_failure,
            "last_support_bundle": self.last_support_bundle,
            "last_query_reference": self.last_query_reference,
            "last_query_mode": self.last_query_mode,
            "last_snapshot_id": self.last_snapshot_id,
        }

    def missing_write_defaults(self) -> tuple[str, ...]:
        missing: list[str] = []
        for field_name in WRITE_DEFAULT_FIELD_NAMES:
            if not str(getattr(self, field_name, "") or "").strip():
                missing.append(field_name)
        return tuple(missing)

    @property
    def write_ready(self) -> bool:
        return not self.missing_write_defaults()

    @property
    def effective_delete_policy(self) -> str:
        candidate = str(self.delete_policy or "").strip()
        return candidate if candidate in DELETE_POLICIES else "ignore"

    def status_record(self, *, last_run: str = "not recorded") -> ForwardProfileStatus:
        return ForwardProfileStatus(
            name=self.name,
            last_run=self.last_run_at or last_run,
            write_ready=self.write_ready,
            missing_defaults=self.missing_write_defaults(),
            delete_policy=self.effective_delete_policy,
            enabled_models=self.enabled_models,
            network_id=self.network_id,
            snapshot_id=self.snapshot_id,
            base_url=self.base_url,
            is_default=self.is_default,
            last_run_at=self.last_run_at,
            last_failure=self.last_failure,
            last_support_bundle=self.last_support_bundle,
            last_query_reference=self.last_query_reference,
            last_query_mode=self.last_query_mode,
            last_snapshot_id=self.last_snapshot_id,
        )

    def with_run_history(
        self,
        *,
        last_run_at: str = "",
        last_failure: str = "",
        last_support_bundle: str = "",
        last_query_reference: str = "",
        last_query_mode: str = "",
        last_snapshot_id: str = "",
    ) -> "ForwardConnectionProfileRecord":
        return replace(
            self,
            last_run_at=last_run_at,
            last_failure=last_failure,
            last_support_bundle=last_support_bundle,
            last_query_reference=last_query_reference,
            last_query_mode=last_query_mode,
            last_snapshot_id=last_snapshot_id or self.last_snapshot_id,
        )


@dataclass(slots=True)
class ForwardPluginConfiguration:
    """Container for one or more persisted Forward connection profiles."""

    default_profile_name: str = ""
    profiles: tuple[ForwardConnectionProfileRecord, ...] = ()
    notes: tuple[str, ...] = ()
    last_run_at: str = ""
    last_failure: str = ""
    last_support_bundle: str = ""
    last_query_reference: str = ""
    last_query_mode: str = ""
    last_snapshot_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_profile(self, name: str) -> ForwardConnectionProfileRecord | None:
        lookup = str(name or "").strip()
        for profile in self.profiles:
            if profile.name == lookup:
                return profile
        return None

    def get_default_profile(self) -> ForwardConnectionProfileRecord | None:
        if self.default_profile_name:
            profile = self.get_profile(self.default_profile_name)
            if profile is not None:
                return profile
        for profile in self.profiles:
            if profile.is_default:
                return profile
        return self.profiles[0] if self.profiles else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "default_profile_name": self.default_profile_name,
            "profiles": [profile.as_dict() for profile in self.profiles],
            "notes": list(self.notes),
            "last_run_at": self.last_run_at,
            "last_failure": self.last_failure,
            "last_support_bundle": self.last_support_bundle,
            "last_query_reference": self.last_query_reference,
            "last_query_mode": self.last_query_mode,
            "last_snapshot_id": self.last_snapshot_id,
            "metadata": dict(self.metadata),
        }

    def status_summary(self) -> dict[str, Any]:
        default_profile = self.get_default_profile()
        statuses = [profile.status_record().as_dict() for profile in self.profiles]
        return {
            "default_profile_name": self.default_profile_name
            or (default_profile.name if default_profile is not None else ""),
            "default_profile": default_profile.status_record().as_dict()
            if default_profile is not None
            else {},
            "profiles": statuses,
            "ready_profiles": sum(1 for profile in self.profiles if profile.write_ready),
            "needs_attention_profiles": sum(
                1 for profile in self.profiles if not profile.write_ready
            ),
            "last_run": str(self.last_run_at or self.metadata.get("last_run") or "not recorded"),
            "last_failure": str(self.last_failure or self.metadata.get("last_failure") or ""),
            "last_support_bundle": str(
                self.last_support_bundle
                or self.metadata.get("last_support_bundle")
                or ""
            ),
            "last_query_reference": str(
                self.last_query_reference
                or self.metadata.get("last_query_reference")
                or self.last_support_bundle
                or self.metadata.get("last_support_bundle")
                or (default_profile.last_query_reference if default_profile is not None else "")
                or ""
            ),
            "last_query_mode": str(
                self.last_query_mode
                or self.metadata.get("last_query_mode")
                or (default_profile.last_query_mode if default_profile is not None else "")
            ),
            "last_snapshot_id": str(
                self.last_snapshot_id
                or self.metadata.get("last_snapshot_id")
                or (default_profile.last_snapshot_id if default_profile is not None else "")
            ),
            "current_policy": str(
                self.metadata.get("current_policy")
                or (default_profile.effective_delete_policy if default_profile is not None else "ignore")
            ),
        }

    def with_run_history(
        self,
        *,
        last_run_at: str = "",
        last_failure: str = "",
        last_support_bundle: str = "",
        last_query_reference: str = "",
        last_query_mode: str = "",
        last_snapshot_id: str = "",
    ) -> "ForwardPluginConfiguration":
        updated_profiles = tuple(
            profile.with_run_history(
                last_run_at=last_run_at,
                last_failure=last_failure,
                last_support_bundle=last_support_bundle,
                last_query_reference=last_query_reference,
                last_query_mode=last_query_mode,
                last_snapshot_id=last_snapshot_id,
            )
            if profile.is_default
            else profile
            for profile in self.profiles
        )
        return replace(
            self,
            profiles=updated_profiles,
            last_run_at=last_run_at,
            last_failure=last_failure,
            last_support_bundle=last_support_bundle,
            last_query_reference=last_query_reference,
            last_query_mode=last_query_mode,
            last_snapshot_id=last_snapshot_id or self.last_snapshot_id,
            metadata={
                **self.metadata,
                "last_run": last_run_at,
                "last_failure": last_failure,
                "last_support_bundle": last_support_bundle,
                "last_query_reference": last_query_reference,
                "last_query_mode": last_query_mode,
                "last_snapshot_id": last_snapshot_id or self.last_snapshot_id,
            },
        )


if models is not None:

    class ForwardConnectionProfile(BaseModel):  # type: ignore[too-many-ancestors]
        """Database-backed plugin configuration record for Forward connections."""

        name = models.CharField(max_length=128, unique=True)
        base_url = models.URLField(default="https://fwd.app")
        username = models.CharField(max_length=255, blank=True, default="")
        password = models.CharField(max_length=255, blank=True, default="")
        network_id = models.CharField(max_length=64, blank=True, default="")
        snapshot_id = models.CharField(
            max_length=128,
            blank=True,
            default=LATEST_PROCESSED_SNAPSHOT,
        )
        enabled_models = models.JSONField(default=list, blank=True)
        query_contract_version = models.CharField(max_length=32, default="v1")
        default_location_type_name = models.CharField(max_length=128, blank=True, default="")
        default_location_status_name = models.CharField(max_length=128, blank=True, default="")
        default_device_role_name = models.CharField(max_length=128, blank=True, default="")
        default_device_status_name = models.CharField(max_length=128, blank=True, default="")
        delete_policy = models.CharField(max_length=32, default="ignore")
        is_default = models.BooleanField(default=False)
        last_run_at = models.CharField(max_length=128, blank=True, default="")
        last_failure = models.TextField(blank=True, default="")
        last_support_bundle = models.CharField(max_length=255, blank=True, default="")
        last_query_reference = models.CharField(max_length=255, blank=True, default="")
        last_query_mode = models.CharField(max_length=64, blank=True, default="")
        last_snapshot_id = models.CharField(max_length=128, blank=True, default="")

        class Meta:
            ordering = ["name"]

        def to_record(self) -> ForwardConnectionProfileRecord:
            return ForwardConnectionProfileRecord(
                name=self.name,
                base_url=self.base_url,
                username=self.username,
                password=self.password,
                network_id=self.network_id,
                snapshot_id=self.snapshot_id,
                enabled_models=tuple(
                    str(name).strip()
                    for name in self.enabled_models
                    if str(name).strip()
                ),
                query_contract_version=self.query_contract_version,
                default_location_type_name=self.default_location_type_name,
                default_location_status_name=self.default_location_status_name,
                default_device_role_name=self.default_device_role_name,
                default_device_status_name=self.default_device_status_name,
                delete_policy=self.effective_delete_policy,
                is_default=self.is_default,
                last_run_at=self.last_run_at,
                last_failure=self.last_failure,
                last_support_bundle=self.last_support_bundle,
                last_query_reference=self.last_query_reference,
                last_query_mode=self.last_query_mode,
                last_snapshot_id=self.last_snapshot_id,
            )

        def to_connection_settings(self) -> ForwardConnectionSettings:
            return self.to_record().to_connection_settings()

        @property
        def effective_delete_policy(self) -> str:
            candidate = str(self.delete_policy or "").strip()
            return candidate if candidate in DELETE_POLICIES else "ignore"

else:
    ForwardConnectionProfile = ForwardConnectionProfileRecord
