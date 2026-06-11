"""UI views for the Forward Nautobot plugin."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from html import escape

try:
    from django.http import HttpResponse
    from django.views import View
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    class HttpResponse:  # type: ignore[too-many-ancestors]
        def __init__(self, content="", status=200, content_type="text/html"):
            self.content = content
            self.status_code = status
            self.content_type = content_type

    class View:  # type: ignore[too-many-ancestors]
        @classmethod
        def as_view(cls, *args, **kwargs):
            def _view(*view_args, **view_kwargs):
                instance = cls()
                if hasattr(instance, "get"):
                    return instance.get(*view_args, **view_kwargs)

            return _view

from .forms import DELETE_POLICY_CHOICES
from .forms import FORWARD_PROFILE_FORM_FIELDS
from .forms import ForwardConnectionProfileForm
from .models import ForwardConnectionProfile
from .models import ForwardConnectionProfileRecord
from .models import ForwardPluginConfiguration


def _iter_persisted_profile_records() -> tuple[ForwardConnectionProfileRecord, ...]:
    manager = getattr(ForwardConnectionProfile, "objects", None)
    if manager is None:
        return ()
    if hasattr(manager, "all"):
        try:
            records = manager.all()
        except Exception:  # pragma: no cover - defensive
            return ()
        return tuple(
            record.to_record() if hasattr(record, "to_record") else record
            for record in records
        )
    return ()


def _iter_profile_records(manager) -> tuple[ForwardConnectionProfileRecord, ...]:
    if manager is None or not hasattr(manager, "all"):
        return ()
    try:
        records = manager.all()
    except Exception:  # pragma: no cover - defensive
        return ()
    return tuple(
        record.to_record() if hasattr(record, "to_record") else record
        for record in records
    )


def _render_profile_editor(
    profile: ForwardConnectionProfileRecord | None = None,
    *,
    values: Mapping[str, object] | None = None,
    message: str = "",
    error: str = "",
) -> str:
    form = ForwardConnectionProfileForm()
    if hasattr(form, "fields"):
        field_names = tuple(form.fields)
    else:
        field_names = getattr(form, "field_names", FORWARD_PROFILE_FORM_FIELDS)
    values = dict(values or (profile.as_dict() if profile is not None else {}))
    if message:
        message_html = f'<p class="success">{escape(message)}</p>'
    else:
        message_html = ""
    if error:
        error_html = f'<p class="error">{escape(error)}</p>'
    else:
        error_html = ""
    controls: list[str] = []
    for field_name in field_names:
        value = values.get(field_name, "")
        if field_name == "password":
            value = ""
        if field_name == "enabled_models" and isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value if str(item).strip())
        if field_name == "delete_policy":
            options = []
            for option_value, option_label in DELETE_POLICY_CHOICES:
                selected = " selected" if str(value or "ignore") == option_value else ""
                options.append(
                    f'<option value="{escape(option_value)}"{selected}>{escape(option_label)}</option>'
                )
            control = f'<select name="{escape(field_name)}">{"".join(options)}</select>'
        elif field_name == "is_default":
            checked = " checked" if bool(value) else ""
            control = (
                f'<input type="checkbox" name="{escape(field_name)}" value="1"{checked}>'
            )
        elif field_name == "password":
            control = f'<input type="password" name="{escape(field_name)}" value="">'
        else:
            control = (
                f'<input type="text" name="{escape(field_name)}" '
                f'value="{escape(str(value or ""))}">'
            )
        controls.append(
            "<label>"
            f"<span>{escape(field_name)}</span>"
            f"{control}"
            "</label>"
        )
    return (
        "<form class=\"forward-profile-form\" method=\"post\">"
        f"{message_html}{error_html}"
        "<p>Profile editing is available here for the persisted connection profile.</p>"
        + "".join(controls)
        + "<button type=\"submit\">Save profile</button>"
        + "</form>"
    )


def _profile_from_payload(
    payload: dict[str, object],
    *,
    existing: ForwardConnectionProfileRecord | None = None,
) -> ForwardConnectionProfileRecord:
    return ForwardConnectionProfileRecord.from_mapping(
        payload,
        default_name="job-profile",
        existing=existing,
    )


def _save_profile_record(
    record: ForwardConnectionProfileRecord,
    *,
    manager=None,
) -> ForwardConnectionProfileRecord | None:
    manager = manager or getattr(ForwardConnectionProfile, "objects", None)
    if manager is None:
        return None
    existing = None
    if hasattr(manager, "get"):
        try:
            existing = manager.get(name=record.name)
        except Exception:  # pragma: no cover - defensive
            existing = None
    if existing is not None and not record.password:
        record = replace(record, password=str(getattr(existing, "password", "") or ""))
    data = record.as_dict()
    data["enabled_models"] = list(record.enabled_models)
    defaults = {key: value for key, value in data.items() if key != "name"}
    if hasattr(manager, "update_or_create"):
        obj, _created = manager.update_or_create(name=record.name, defaults=defaults)
    elif existing is not None:
        obj = existing
        for key, value in defaults.items():
            setattr(obj, key, value)
        if hasattr(obj, "save"):
            obj.save()
    elif hasattr(manager, "create"):
        obj = manager.create(name=record.name, **defaults)
    else:  # pragma: no cover - defensive
        return None

    if record.is_default and hasattr(manager, "all"):
        try:
            for other in manager.all():
                if getattr(other, "name", None) == record.name:
                    continue
                if getattr(other, "is_default", False):
                    setattr(other, "is_default", False)
                    if hasattr(other, "save"):
                        other.save(update_fields=["is_default"])
        except Exception:  # pragma: no cover - defensive
            pass

    return obj.to_record() if hasattr(obj, "to_record") else record


def _render_status_lines(summary: dict[str, object]) -> str:
    profiles = summary.get("profiles", [])
    if not profiles:
        return (
            "<p>Last run: not recorded</p>"
            "<p>Write readiness: no persisted profiles</p>"
            "<p>Current policy: ignore</p>"
        )
    lines = [
        f"<p>Last run: {escape(str(summary.get('last_run') or 'not recorded'))}</p>",
        f"<p>Last failure: {escape(str(summary.get('last_failure') or 'none'))}</p>",
        f"<p>Last support bundle: {escape(str(summary.get('last_support_bundle') or 'none'))}</p>",
        f"<p>Current policy: {escape(str(summary.get('current_policy') or 'ignore'))}</p>",
        f"<p>Ready profiles: {int(summary.get('ready_profiles') or 0)}</p>",
        f"<p>Needs attention: {int(summary.get('needs_attention_profiles') or 0)}</p>",
    ]
    rows = [
        "<tr><th>Name</th><th>Last run</th><th>Last failure</th><th>Support bundle</th><th>Ready</th><th>Missing defaults</th><th>Delete policy</th></tr>"
    ]
    for profile in profiles:
        missing_defaults = ", ".join(profile.get("missing_defaults", [])) or "none"
        rows.append(
            "<tr>"
            f"<td>{escape(str(profile.get('name') or ''))}</td>"
            f"<td>{escape(str(profile.get('last_run') or 'not recorded'))}</td>"
            f"<td>{escape(str(profile.get('last_failure') or 'none'))}</td>"
            f"<td>{escape(str(profile.get('last_support_bundle') or 'none'))}</td>"
            f"<td>{'yes' if profile.get('write_ready') else 'no'}</td>"
            f"<td>{escape(missing_defaults)}</td>"
            f"<td>{escape(str(profile.get('delete_policy') or 'ignore'))}</td>"
            "</tr>"
        )
    return "".join(lines) + "<table>" + "".join(rows) + "</table>"


class ForwardHomeView(View):
    def get(self, request=None, *args, **kwargs):
        return HttpResponse(
            "<h1>Forward Networks</h1>"
            "<p>Forward Nautobot plugin.</p>"
            "<p>Use the jobs page to preview or sync a Forward network.</p>"
        )


class ForwardConfigurationView(View):
    def get(self, request=None, *args, **kwargs):
        profiles = _iter_persisted_profile_records()
        configuration = ForwardPluginConfiguration(
            default_profile_name="",
            profiles=profiles,
        )
        summary = configuration.status_summary()
        default_profile = configuration.get_default_profile()
        return HttpResponse(
            "<h1>Forward Configuration</h1>"
            "<p>Persistent connection profiles are modeled in forward_nautobot.models.</p>"
            "<p>Profile fields: name, base_url, username, password, network_id, snapshot_id, enabled_models, query_contract_version, delete_policy.</p>"
            "<p>Write prerequisites: default_location_type_name, default_location_status_name, default_device_role_name, default_device_status_name.</p>"
            f"<p>Editable form fields: {', '.join(FORWARD_PROFILE_FORM_FIELDS)}</p>"
            "<h2>Profile Editor</h2>"
            f"{_render_profile_editor(default_profile)}"
            "<h2>Profile Status</h2>"
            f"{_render_status_lines(summary)}"
        )

    def post(self, request=None, *args, **kwargs):
        payload = getattr(request, "POST", None) or {}
        form = ForwardConnectionProfileForm(payload)
        existing_profiles = _iter_persisted_profile_records()
        existing = None
        profile_name = str(payload.get("name") or "job-profile").strip() or "job-profile"
        for profile in existing_profiles:
            if profile.name == profile_name:
                existing = profile
                break
        saved = None
        message = ""
        error = ""
        if form.is_valid():
            record = _profile_from_payload(form.cleaned_data, existing=existing)
            saved = _save_profile_record(record)
            message = (
                f"Saved profile {saved.name}."
                if saved is not None
                else "Profile save is unavailable in this environment."
            )
        else:
            error_parts: list[str] = []
            for field_name, field_errors in form.errors.items():
                joined = ", ".join(field_errors)
                error_parts.append(f"{field_name}: {joined}")
            error = "; ".join(error_parts) or "Profile validation failed."
        profiles = _iter_persisted_profile_records()
        configuration = ForwardPluginConfiguration(
            default_profile_name=saved.name if saved is not None else "",
            profiles=profiles,
            metadata={
                "current_policy": saved.effective_delete_policy if saved is not None else "ignore",
            },
        )
        summary = configuration.status_summary()
        return HttpResponse(
            "<h1>Forward Configuration</h1>"
            f"{_render_profile_editor(saved if saved is not None else None, values=payload, message=message, error=error)}"
            "<h2>Profile Status</h2>"
            f"{_render_status_lines(summary)}"
        )
