"""Editable configuration form helpers for the Forward plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import SYNC_MODES, WRITE_DEFAULT_FIELD_NAMES

FORWARD_PROFILE_FORM_FIELDS: tuple[str, ...] = (
    "name",
    "base_url",
    "username",
    "password",
    "network_id",
    "verify_tls",
    "snapshot_id",
    "enabled_models",
    "sync_mode",
    "device_vendors",
    "device_types",
    "device_models",
    "cloud_types",
    "cloud_account_ids",
    "query_contract_version",
    "default_location_type_name",
    "default_location_status_name",
    "default_device_role_name",
    "default_device_status_name",
    "delete_policy",
    "is_default",
)

FORWARD_PROFILE_PREREQUISITE_FIELDS: tuple[str, ...] = (
    "username",
    "password",
    "network_id",
    "snapshot_id",
    "query_contract_version",
    *WRITE_DEFAULT_FIELD_NAMES,
    "delete_policy",
)

DELETE_POLICY_CHOICES: tuple[tuple[str, str], ...] = (
    ("ignore", "Ignore missing rows"),
    ("mark_inactive", "Mark missing rows inactive"),
    ("delete", "Delete missing rows"),
)

SYNC_MODE_CHOICES: tuple[tuple[str, str], ...] = (
    ("network", "Network inventory only"),
    ("cloud", "Cloud inventory only"),
    ("all", "Network and cloud inventory"),
)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "t", "yes", "on", "y"}


def _coerce_csv(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        values = value
    else:
        values = str(value or "").split(",")
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


try:
    from django import forms
    from django.apps import apps as _django_apps

    if not _django_apps.ready:
        raise ModuleNotFoundError("Django app registry is not ready")
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    forms = None

    @dataclass(slots=True)
    class ForwardConnectionProfileForm:  # type: ignore[too-many-ancestors]
        """Fallback description of the editable Forward connection profile form."""

        data: dict[str, object] | None = None
        field_names: tuple[str, ...] = FORWARD_PROFILE_FORM_FIELDS
        cleaned_data: dict[str, object] = field(init=False, default_factory=dict)
        errors: dict[str, list[str]] = field(init=False, default_factory=dict)

        def __post_init__(self) -> None:
            self.data = dict(self.data or {})

        def is_valid(self) -> bool:
            self.cleaned_data = {}
            self.errors = {}
            name = str(self.data.get("name") or "").strip()
            if not name:
                self.errors.setdefault("name", []).append("This field is required.")
            else:
                self.cleaned_data["name"] = name

            base_url = str(self.data.get("base_url") or "https://fwd.app").strip()
            if not base_url:
                self.errors.setdefault("base_url", []).append("This field is required.")
            elif "://" not in base_url:
                self.errors.setdefault("base_url", []).append("Enter a valid URL.")
            else:
                self.cleaned_data["base_url"] = base_url

            for field_name in FORWARD_PROFILE_PREREQUISITE_FIELDS:
                self.cleaned_data[field_name] = str(self.data.get(field_name) or "").strip()
            self.cleaned_data["verify_tls"] = _coerce_bool(self.data.get("verify_tls"))
            if not self.cleaned_data["snapshot_id"]:
                self.cleaned_data["snapshot_id"] = "latestProcessed"
            if not self.cleaned_data["query_contract_version"]:
                self.cleaned_data["query_contract_version"] = "v2"
            if not self.cleaned_data["delete_policy"]:
                self.cleaned_data["delete_policy"] = "ignore"
            sync_mode = str(self.data.get("sync_mode") or "network").strip().lower()
            self.cleaned_data["sync_mode"] = sync_mode
            if sync_mode not in SYNC_MODES:
                self.errors.setdefault("sync_mode", []).append("Select a valid choice.")
            for field_name in (
                "enabled_models",
                "device_vendors",
                "device_types",
                "device_models",
                "cloud_types",
                "cloud_account_ids",
            ):
                self.cleaned_data[field_name] = _coerce_csv(self.data.get(field_name))
            self.cleaned_data["is_default"] = str(
                self.data.get("is_default") or ""
            ).strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
                "y",
            }
            if self.cleaned_data["delete_policy"] not in {
                value for value, _ in DELETE_POLICY_CHOICES
            }:
                self.errors.setdefault("delete_policy", []).append("Select a valid choice.")
            return not self.errors

        def as_dict(self) -> dict[str, list[str]]:
            return {"field_names": list(self.field_names)}

else:

    class ForwardConnectionProfileForm(forms.Form):  # type: ignore[too-many-ancestors]
        name = forms.CharField(max_length=128)
        base_url = forms.URLField(initial="https://fwd.app")
        username = forms.CharField(required=False)
        password = forms.CharField(required=False, widget=forms.PasswordInput)
        network_id = forms.CharField(required=False)
        verify_tls = forms.BooleanField(required=False, initial=True)
        snapshot_id = forms.CharField(required=False, initial="latestProcessed")
        enabled_models = forms.CharField(
            required=False,
            help_text="Comma-separated Forward model slugs.",
        )
        sync_mode = forms.ChoiceField(
            required=False,
            choices=SYNC_MODE_CHOICES,
            initial="network",
        )
        device_vendors = forms.CharField(
            required=False,
            help_text="Comma-separated Forward manufacturer enum values.",
        )
        device_types = forms.CharField(
            required=False,
            help_text="Comma-separated Forward functional device-class enum values.",
        )
        device_models = forms.CharField(
            required=False,
            help_text="Comma-separated exact hardware model values.",
        )
        cloud_types = forms.CharField(
            required=False,
            help_text="Comma-separated Forward cloud-type values.",
        )
        cloud_account_ids = forms.CharField(
            required=False,
            help_text="Comma-separated Forward cloud account IDs.",
        )
        query_contract_version = forms.CharField(required=False, initial="v2")
        default_location_type_name = forms.CharField(required=False)
        default_location_status_name = forms.CharField(required=False)
        default_device_role_name = forms.CharField(required=False)
        default_device_status_name = forms.CharField(required=False)
        delete_policy = forms.ChoiceField(
            required=False,
            choices=DELETE_POLICY_CHOICES,
            initial="ignore",
        )
        is_default = forms.BooleanField(required=False)

        def clean_enabled_models(self):
            return _coerce_csv(self.cleaned_data.get("enabled_models", ""))

        def clean_device_vendors(self):
            return _coerce_csv(self.cleaned_data.get("device_vendors", ""))

        def clean_device_types(self):
            return _coerce_csv(self.cleaned_data.get("device_types", ""))

        def clean_device_models(self):
            return _coerce_csv(self.cleaned_data.get("device_models", ""))

        def clean_cloud_types(self):
            return _coerce_csv(self.cleaned_data.get("cloud_types", ""))

        def clean_cloud_account_ids(self):
            return _coerce_csv(self.cleaned_data.get("cloud_account_ids", ""))

        def clean_verify_tls(self):
            raw_value = self.data.get("verify_tls", "")
            return _coerce_bool(raw_value)
