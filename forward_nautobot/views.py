"""UI views for the Forward Networks SSoT integration."""

from __future__ import annotations

import json
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
from .fixture_support import fixture_coverage
from .integrations.forward.registry import CORE_MODEL_MAPPINGS
from .models import ForwardConnectionProfile
from .models import ForwardConnectionProfileRecord
from .models import ForwardPluginConfiguration
from .models import WRITE_DEFAULT_FIELD_NAMES


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
        f"<p>Run outcome: {escape(str(summary.get('last_failure') or 'none'))}</p>",
        f"<p>Last support bundle: {escape(str(summary.get('last_support_bundle') or 'none'))}</p>",
        f"<p>Last query reference: {escape(str(summary.get('last_query_reference') or 'none'))}</p>",
        f"<p>Last query mode: {escape(str(summary.get('last_query_mode') or 'none'))}</p>",
        f"<p>Last snapshot: {escape(str(summary.get('last_snapshot_id') or 'none'))}</p>",
        f"<p>Current policy: {escape(str(summary.get('current_policy') or 'ignore'))}</p>",
        f"<p>Ready profiles: {int(summary.get('ready_profiles') or 0)}</p>",
        f"<p>Needs attention: {int(summary.get('needs_attention_profiles') or 0)}</p>",
    ]
    rows = [
        "<tr><th>Name</th><th>Last run</th><th>Run outcome</th><th>Support bundle</th><th>Query reference</th><th>Query mode</th><th>Ready</th><th>Missing defaults</th><th>Delete policy</th></tr>"
    ]
    for profile in profiles:
        missing_defaults = ", ".join(profile.get("missing_defaults", [])) or "none"
        rows.append(
            "<tr>"
            f"<td>{escape(str(profile.get('name') or ''))}</td>"
            f"<td>{escape(str(profile.get('last_run') or 'not recorded'))}</td>"
            f"<td>{escape(str(profile.get('last_failure') or 'none'))}</td>"
            f"<td>{escape(str(profile.get('last_support_bundle') or 'none'))}</td>"
            f"<td>{escape(str(profile.get('last_query_reference') or profile.get('last_support_bundle') or 'none'))}</td>"
            f"<td>{escape(str(profile.get('last_query_mode') or 'none'))}</td>"
            f"<td>{'yes' if profile.get('write_ready') else 'no'}</td>"
            f"<td>{escape(missing_defaults)}</td>"
            f"<td>{escape(str(profile.get('delete_policy') or 'ignore'))}</td>"
            "</tr>"
        )
    return "".join(lines) + "<table>" + "".join(rows) + "</table>"


def _render_style_block() -> str:
    return """
<style>
.forward-shell {
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  color: #102033;
  background: linear-gradient(180deg, #f6f8fb 0%, #edf3f8 100%);
  border: 1px solid #d9e2ec;
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 18px 40px rgba(16, 32, 51, 0.08);
}
.forward-hero {
  display: grid;
  gap: 14px;
  margin-bottom: 20px;
}
.forward-hero h1,
.forward-hero h2,
.forward-section h3,
.forward-section h4,
.forward-card h3 {
  margin: 0;
}
.forward-kicker {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 12px;
  color: #5f7386;
}
.forward-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.forward-card {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid #d9e2ec;
  border-radius: 16px;
  padding: 16px;
}
.forward-card .metric {
  font-size: 30px;
  font-weight: 700;
  line-height: 1;
  margin-top: 8px;
}
.forward-card .subtle,
.forward-section .subtle {
  color: #5f7386;
}
.forward-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.forward-action {
  display: inline-block;
  text-decoration: none;
  background: #102033;
  color: #fff !important;
  padding: 10px 14px;
  border-radius: 999px;
}
.forward-action.secondary {
  background: #e4ebf2;
  color: #102033 !important;
}
.forward-section {
  margin-top: 20px;
}
.forward-table {
  width: 100%;
  border-collapse: collapse;
  overflow: hidden;
}
.forward-table th,
.forward-table td {
  text-align: left;
  padding: 10px 8px;
  border-bottom: 1px solid #d9e2ec;
  vertical-align: top;
}
.forward-taglist {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.forward-tag {
  display: inline-block;
  border-radius: 999px;
  padding: 5px 10px;
  background: #dce7f5;
  color: #102033;
  font-size: 12px;
}
.forward-panel {
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #d9e2ec;
  border-radius: 16px;
  padding: 16px;
}
.forward-stack {
  display: grid;
  gap: 12px;
}
.forward-json {
  background: #102033;
  color: #f5fbff;
  padding: 12px;
  border-radius: 12px;
  overflow-x: auto;
}
.forward-note-list {
  margin: 0;
  padding-left: 18px;
}
@media (max-width: 720px) {
  .forward-shell {
    padding: 16px;
    border-radius: 16px;
  }
}
</style>
"""


def _render_page(title: str, body: str, *, kicker: str = "Forward Networks SSoT") -> str:
    return (
        _render_style_block()
        + '<div class="forward-shell">'
        + '<div class="forward-hero">'
        + f'<div class="forward-kicker">{escape(kicker)}</div>'
        + f"<h1>{escape(title)}</h1>"
        + "</div>"
        + body
        + "</div>"
    )


def _render_metric_card(label: str, value: str, description: str = "") -> str:
    return (
        '<div class="forward-card">'
        f"<div class=\"subtle\">{escape(label)}</div>"
        f"<div class=\"metric\">{escape(value)}</div>"
        + (f"<div class=\"subtle\">{escape(description)}</div>" if description else "")
        + "</div>"
    )


def _render_model_table() -> str:
    rows = [
        "<tr><th>Slice</th><th>Contract</th><th>Write mode</th><th>Missing-row policy</th></tr>"
    ]
    for mapping in CORE_MODEL_MAPPINGS:
        rows.append(
            "<tr>"
            f"<td>{escape(mapping.slug)}</td>"
            f"<td>{escape(mapping.forward_query_file)}</td>"
            f"<td>{escape(mapping.write_mode)}</td>"
            f"<td>{escape(mapping.missing_row_policy)}</td>"
            "</tr>"
        )
    return '<table class="forward-table">' + "".join(rows) + "</table>"


def _fixture_coverage_by_slug() -> dict[str, dict[str, object]]:
    return {str(entry["slug"]): dict(entry) for entry in fixture_coverage()}


def _render_coverage_table(coverage_by_slug: dict[str, dict[str, object]] | None = None) -> str:
    coverage_by_slug = coverage_by_slug or _fixture_coverage_by_slug()
    rows = [
        "<tr><th>Slice</th><th>Rows</th><th>Sample key</th><th>Contract</th><th>Detail</th></tr>"
    ]
    for entry in coverage_by_slug.values():
        rows.append(
            "<tr>"
            f"<td>{escape(str(entry['slug']))}</td>"
            f"<td>{int(entry['count'])}</td>"
            f"<td>{escape(str(entry['sample_key'] or 'none'))}</td>"
            f"<td>{escape(str(entry['contract_version']))}</td>"
            f"<td><a href=\"/plugins/forward_nautobot/slices/{escape(str(entry['slug']))}/\">Open</a></td>"
            "</tr>"
        )
    return '<table class="forward-table">' + "".join(rows) + "</table>"


def _render_coverage_details(coverage_by_slug: dict[str, dict[str, object]] | None = None) -> str:
    coverage_by_slug = coverage_by_slug or _fixture_coverage_by_slug()
    blocks: list[str] = []
    empty_rows_message = '<p class="subtle">No packaged rows available for this slice.</p>'
    for entry in coverage_by_slug.values():
        sample_rows = entry.get("sample_rows", ())
        serialized_rows = "".join(
            f"<pre>{escape(json.dumps(row, indent=2, sort_keys=True))}</pre>"
            for row in sample_rows
        )
        blocks.append(
            "<details class=\"forward-panel\" style=\"margin-top: 12px;\">"
            f"<summary><strong>{escape(str(entry['slug']))}</strong> "
            f"({int(entry['count'])} rows)</summary>"
            f"<p class=\"subtle\">{escape(str(entry['description']))}</p>"
            f"{serialized_rows or empty_rows_message}"
            "</details>"
        )
    return "".join(blocks)


def _render_dashboard_body(summary: dict[str, object], profiles: tuple[ForwardConnectionProfileRecord, ...]) -> str:
    default_profile = next((profile for profile in profiles if profile.is_default), profiles[0] if profiles else None)
    if default_profile is None:
        default_profile_name = "no saved profile"
        default_policy = "ignore"
        default_snapshot = "none"
    else:
        default_profile_name = default_profile.name
        default_policy = default_profile.effective_delete_policy
        default_snapshot = default_profile.last_snapshot_id or default_profile.snapshot_id or "none"
    cards = (
        _render_metric_card("Saved profiles", str(len(profiles)), "Profiles persist in Nautobot."),
        _render_metric_card("Ready profiles", str(int(summary.get("ready_profiles") or 0)), "All write defaults set."),
        _render_metric_card("Last snapshot", str(summary.get("last_snapshot_id") or default_snapshot), "Baseline used for diffs."),
        _render_metric_card("Policy", str(summary.get("current_policy") or default_policy), "Delete handling for missing rows."),
    )
    sections = [
        "<div class=\"forward-grid\">" + "".join(cards) + "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Demo flow</h3>"
        '<ol class="forward-note-list">'
        "<li>Create or select a persisted profile.</li>"
        "<li>Run the SSoT job against bundled contracts.</li>"
        "<li>Show the support bundle and last snapshot baseline.</li>"
        "<li>Explain how query-ID-backed runs switch to diffs when a baseline exists.</li>"
        "</ol>"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Supported slices</h3>"
        f"{_render_model_table()}"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Ingestion coverage</h3>"
        "<p class=\"subtle\">Packaged fixture coverage for the supported slices.</p>"
        f"{_render_coverage_table()}"
        f"{_render_coverage_details()}"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Operational notes</h3>"
        '<div class="forward-taglist">'
        '<span class="forward-tag">Inline NQE fallback</span>'
        '<span class="forward-tag">Query-ID diffs</span>'
        '<span class="forward-tag">Redacted support bundles</span>'
        '<span class="forward-tag">No source-field normalization</span>'
        "</div>"
        f"<p class=\"subtle\">Default profile: {escape(default_profile_name)}</p>"
        f"<p class=\"subtle\">Current policy: {escape(str(summary.get('current_policy') or default_policy))}</p>"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Actions</h3>"
        '<div class="forward-actions">'
        '<a class="forward-action" href="/plugins/forward_nautobot/diagnostics/">Open diagnostics</a>'
        '<a class="forward-action" href="/plugins/forward_nautobot/configuration/">Open configuration</a>'
        '<a class="forward-action secondary" href="/plugins/forward_nautobot/">Refresh overview</a>'
        "</div>"
        "</div>",
    ]
    return "<p class=\"subtle\">An operational view of the Forward SSoT integration in Nautobot 3.1.</p>" + "".join(sections)


def _render_dashboard(summary: dict[str, object], profiles: tuple[ForwardConnectionProfileRecord, ...]) -> str:
    return _render_page(
        "Forward Nautobot Dashboard",
        _render_dashboard_body(summary, profiles),
    )


def _render_diagnostics_body(summary: dict[str, object], profiles: tuple[ForwardConnectionProfileRecord, ...]) -> str:
    coverage_by_slug = _fixture_coverage_by_slug()
    default_profile = next((profile for profile in profiles if profile.is_default), profiles[0] if profiles else None)
    default_profile_name = default_profile.name if default_profile is not None else "no saved profile"
    sections = [
        "<p class=\"subtle\">Operational coverage, readiness, and raw packaged row inspection for support and validation.</p>",
        '<div class="forward-actions">'
        '<a class="forward-action" href="/plugins/forward_nautobot/">Overview</a>'
        '<a class="forward-action secondary" href="/plugins/forward_nautobot/status/">Status</a>'
        '<a class="forward-action secondary" href="/plugins/forward_nautobot/configuration/">Configuration</a>'
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Coverage and readiness</h3>"
        '<div class="forward-stack">'
        f"{_render_metric_card('Saved profiles', str(len(profiles)), 'Profiles persist in Nautobot.')}"
        f"{_render_metric_card('Ready profiles', str(int(summary.get('ready_profiles') or 0)), 'All write defaults set.')}"
        f"{_render_metric_card('Last snapshot', str(summary.get('last_snapshot_id') or 'none'), 'Baseline used for diffs.')}"
        f"{_render_metric_card('Default profile', escape(default_profile_name), 'Persisted profile used for syncs.')}"
        "</div>"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Ingestion coverage</h3>"
        "<p class=\"subtle\">Packaged fixture coverage for the supported slices.</p>"
        "<p class=\"subtle\">Raw packaged rows are available from each slice detail page.</p>"
        f"{_render_coverage_table(coverage_by_slug)}"
        f"{_render_coverage_details(coverage_by_slug)}"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Operational status</h3>"
        f"{_render_status_lines(summary)}"
        "</div>",
        '<div class="forward-section forward-panel">'
        "<h3>Configuration</h3>"
        '<p class="subtle">Open Configuration to edit the persisted profile and defaults used by the sync path.</p>'
        '<div class="forward-actions">'
        '<a class="forward-action" href="/plugins/forward_nautobot/configuration/">Open configuration</a>'
        "</div>"
        "</div>",
    ]
    return "".join(sections)


def _render_slice_detail_body(model_slug: str) -> str:
    coverage_by_slug = _fixture_coverage_by_slug()
    entry = coverage_by_slug.get(model_slug)
    if entry is None:
        return (
            "<div class=\"forward-section forward-panel\">"
            f"<p class=\"error\">Unknown slice: {escape(model_slug)}</p>"
            '<div class="forward-actions">'
            '<a class="forward-action" href="/plugins/forward_nautobot/diagnostics/">Back to diagnostics</a>'
            "</div>"
            "</div>"
        )
    sample_rows = tuple(entry.get("sample_rows", ()))
    raw_rows = "".join(
        f"<pre class=\"forward-json\">{escape(json.dumps(row, indent=2, sort_keys=True))}</pre>"
        for row in sample_rows
    )
    if not raw_rows:
        raw_rows = "<p class=\"subtle\">No packaged rows available for this slice.</p>"
    return (
        '<div class="forward-section forward-panel">'
        f"<h3>{escape(str(entry['slug']))}</h3>"
        f"<p class=\"subtle\">{escape(str(entry['description']))}</p>"
        f"<p><strong>Contract version:</strong> {escape(str(entry['contract_version']))}</p>"
        f"<p><strong>Row count:</strong> {int(entry['count'])}</p>"
        f"<p><strong>Sample key:</strong> {escape(str(entry['sample_key'] or 'none'))}</p>"
        '<div class="forward-actions">'
        '<a class="forward-action" href="/plugins/forward_nautobot/diagnostics/">Back to diagnostics</a>'
        '<a class="forward-action secondary" href="/plugins/forward_nautobot/">Back to overview</a>'
        "</div>"
        "</div>"
        '<div class="forward-section forward-panel">'
        "<h3>Raw packaged rows</h3>"
        f"{raw_rows}"
        "</div>"
    )


class ForwardHomeView(View):
    def get(self, request=None, *args, **kwargs):
        profiles = _iter_persisted_profile_records()
        configuration = ForwardPluginConfiguration(
            default_profile_name="",
            profiles=profiles,
        )
        summary = configuration.status_summary()
        body = _render_dashboard(summary, profiles)
        return HttpResponse(body)


class ForwardDiagnosticsView(View):
    def get(self, request=None, *args, **kwargs):
        profiles = _iter_persisted_profile_records()
        configuration = ForwardPluginConfiguration(
            default_profile_name="",
            profiles=profiles,
        )
        summary = configuration.status_summary()
        body = _render_page(
            "Forward Diagnostics",
            _render_diagnostics_body(summary, profiles),
        )
        return HttpResponse(body)


class ForwardSliceDetailView(View):
    def get(self, request=None, model_slug=None, *args, **kwargs):
        body = _render_page(
            "Forward Slice Detail",
            _render_slice_detail_body(str(model_slug or "").strip()),
        )
        return HttpResponse(body)


class ForwardStatusView(View):
    def get(self, request=None, *args, **kwargs):
        profiles = _iter_persisted_profile_records()
        configuration = ForwardPluginConfiguration(
            default_profile_name="",
            profiles=profiles,
        )
        summary = configuration.status_summary()
        body = _render_page(
            "Forward Status",
            "<p class=\"subtle\">A compact operational summary for reviews and troubleshooting.</p>"
            + _render_dashboard_body(summary, profiles)
            + '<div class="forward-section forward-panel">'
            "<h3>Operational status</h3>"
            "<p class=\"subtle\">Current profile readiness and support state.</p>"
            "</div>"
            '<div class="forward-section forward-panel">'
            "<h3>Profile Status</h3>"
            f"{_render_status_lines(summary)}"
            "</div>",
        )
        return HttpResponse(body)


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
            _render_page(
                "Forward Configuration",
                "<p class=\"subtle\">Persistent connection profiles are modeled in forward_nautobot.models.</p>"
                '<div class="forward-section forward-panel">'
                "<h3>Profile Editor</h3>"
                f"<p class=\"subtle\">Profile fields: name, base_url, username, password, network_id, snapshot_id, enabled_models, query_contract_version, delete_policy, last_snapshot_id.</p>"
                f"<p class=\"subtle\">Write prerequisites: {', '.join(WRITE_DEFAULT_FIELD_NAMES)}.</p>"
                f"<p class=\"subtle\">Editable form fields: {', '.join(FORWARD_PROFILE_FORM_FIELDS)}</p>"
                f"{_render_profile_editor(default_profile)}"
                "</div>"
                '<div class="forward-section forward-panel">'
                "<h3>Profile Status</h3>"
                f"{_render_status_lines(summary)}"
                "</div>",
            )
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
            _render_page(
                "Forward Configuration",
                f"{_render_profile_editor(saved if saved is not None else None, values=payload, message=message, error=error)}"
                '<div class="forward-section forward-panel">'
                "<h3>Profile Status</h3>"
                f"{_render_status_lines(summary)}"
                "</div>",
            )
        )
