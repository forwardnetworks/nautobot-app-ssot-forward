"""Editable configuration form helpers for the Forward plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import WRITE_DEFAULT_FIELD_NAMES

FORWARD_PROFILE_FORM_FIELDS: tuple[str, ...] = (
    "name",
    "base_url",
    "username",
    "password",
    "network_id",
    "verify_tls",
    "snapshot_id",
    "enabled_models",
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


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "t", "yes", "on", "y"}


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
                self.cleaned_data["query_contract_version"] = "v1"
            if not self.cleaned_data["delete_policy"]:
                self.cleaned_data["delete_policy"] = "ignore"
            self.cleaned_data["enabled_models"] = tuple(
                part.strip()
                for part in str(self.data.get("enabled_models") or "").split(",")
                if part.strip()
            )
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
        query_contract_version = forms.CharField(required=False, initial="v1")
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
            raw_value = self.cleaned_data.get("enabled_models", "")
            if isinstance(raw_value, (list, tuple)):
                return tuple(str(item).strip() for item in raw_value if str(item).strip())
                return tuple(
                    part.strip() for part in str(raw_value or "").split(",") if part.strip()
                )

        def clean_verify_tls(self):
            raw_value = self.data.get("verify_tls", "")
            return _coerce_bool(raw_value)
