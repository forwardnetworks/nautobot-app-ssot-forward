from types import SimpleNamespace

import forward_nautobot.views as views
from forward_nautobot.models import ForwardConnectionProfileRecord
from forward_nautobot.views import (
    ForwardConfigurationView,
    ForwardDiagnosticsView,
    ForwardHomeView,
    ForwardSliceDetailView,
    ForwardStatusView,
)


def _content_text(response):
    content = response.content
    return content.decode() if isinstance(content, bytes) else content


def test_home_view_mentions_forward_plugin():
    response = ForwardHomeView().get()
    text = _content_text(response)

    assert response.status_code == 200
    assert "Forward Nautobot Dashboard" in text
    assert "Ingestion coverage" in text
    assert "Query-ID diffs" in text
    assert 'href="/plugins/forward_nautobot/diagnostics/"' in text


def test_status_view_shows_operational_summary():
    response = ForwardStatusView().get()
    text = _content_text(response)

    assert response.status_code == 200
    assert "Forward Status" in text
    assert "Profile Status" in text
    assert "Operational status" in text


def test_diagnostics_view_summarizes_coverage_and_readiness():
    response = ForwardDiagnosticsView().get()
    text = _content_text(response)

    assert response.status_code == 200
    assert "Forward Diagnostics" in text
    assert "Ingestion coverage" in text
    assert "Coverage and readiness" in text
    assert "Raw packaged rows" in text


def test_slice_detail_view_renders_raw_packaged_rows():
    response = ForwardSliceDetailView().get(model_slug="devices")
    text = _content_text(response)

    assert response.status_code == 200
    assert "Forward Slice Detail" in text
    assert "devices" in text
    assert "Raw packaged rows" in text
    assert "cdl1alfabbcn001" in text
    assert "Contract version" in text


def test_configuration_view_mentions_profile_fields():
    response = ForwardConfigurationView().get()
    text = _content_text(response)

    assert response.status_code == 200
    assert "Persistent connection profiles" in text
    assert "query_contract_version" in text
    assert "default_device_role_name" in text
    assert "delete_policy" in text
    assert "Editable form fields" in text
    assert "Profile Editor" in text
    assert "<form" in text
    assert 'name="delete_policy"' in text
    assert "Save profile" in text


def test_configuration_view_renders_profile_status(monkeypatch):
    class _FakeManager:
        def all(self):
            return [
                SimpleNamespace(
                    to_record=lambda: ForwardConnectionProfileRecord(
                        name="primary",
                        default_location_type_name="Building",
                        default_location_status_name="Active",
                        default_device_role_name="Access Switch",
                        default_device_status_name="Active",
                        delete_policy="mark_inactive",
                        is_default=True,
                        last_run_at="2026-06-10T12:00:00Z",
                        last_failure="none",
                        last_support_bundle="bundle-1",
                        last_query_reference="forward_devices.nqe",
                        last_query_mode="bundled_nqe_query_id_diff",
                    )
                )
            ]

    monkeypatch.setattr(views, "ForwardConnectionProfile", SimpleNamespace(objects=_FakeManager()))

    response = ForwardConfigurationView().get()
    text = _content_text(response)

    assert response.status_code == 200
    assert "Profile Status" in text
    assert "primary" in text
    assert "Ready profiles" in text
    assert "mark_inactive" in text
    assert "Last run" in text
    assert "Last failure" in text
    assert "Last support bundle" in text
    assert "Last query reference" in text
    assert "Last query mode" in text


def test_configuration_view_can_persist_profile(monkeypatch):
    class _StoredProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def save(self, update_fields=None):  # pragma: no cover - exercised by call path
            return None

        def to_record(self):
            return ForwardConnectionProfileRecord.from_mapping(self.__dict__)

    class _FakeManager:
        def __init__(self):
            self.rows = {}

        def all(self):
            return list(self.rows.values())

        def get(self, name):
            return self.rows[name]

        def update_or_create(self, name, defaults):
            row = self.rows.get(name)
            if row is None:
                row = _StoredProfile(name=name, **defaults)
                self.rows[name] = row
            else:
                row.__dict__.update(defaults)
            return row, True

    manager = _FakeManager()
    monkeypatch.setattr(views, "ForwardConnectionProfile", SimpleNamespace(objects=manager))

    response = ForwardConfigurationView().post(
        SimpleNamespace(
            POST={
                "name": "primary",
                "base_url": "https://fwd.example",
                "username": "alice",
                "password": "secret",
                "network_id": "net-fixture-1",
                "verify_tls": "0",
                "snapshot_id": "latestProcessed",
                "enabled_models": "devices,interfaces",
                "query_contract_version": "v1",
                "default_location_type_name": "Building",
                "default_location_status_name": "Active",
                "default_device_role_name": "Access Switch",
                "default_device_status_name": "Active",
                "delete_policy": "mark_inactive",
                "is_default": "1",
            }
        )
    )
    text = _content_text(response)

    assert response.status_code == 200
    assert "Saved profile primary." in text
    assert "primary" in text
    assert "mark_inactive" in text
    assert "Ready profiles" in text
    assert "secret" not in text
    assert manager.rows["primary"].enabled_models == ["devices", "interfaces"]
    assert manager.rows["primary"].is_default is True
    assert manager.rows["primary"].verify_tls is False


def test_configuration_view_rejects_invalid_profile(monkeypatch):
    class _FakeManager:
        def __init__(self):
            self.rows = {}

        def all(self):
            return list(self.rows.values())

        def update_or_create(self, name, defaults):  # pragma: no cover - should not be called
            raise AssertionError("invalid profile data should not be persisted")

    manager = _FakeManager()
    monkeypatch.setattr(views, "ForwardConnectionProfile", SimpleNamespace(objects=manager))

    response = ForwardConfigurationView().post(
        SimpleNamespace(
            POST={
                "name": "primary",
                "base_url": "not-a-url",
                "username": "alice",
                "password": "secret",
                "network_id": "net-fixture-1",
                "snapshot_id": "latestProcessed",
                "enabled_models": "devices,interfaces",
                "query_contract_version": "v1",
                "default_location_type_name": "Building",
                "default_location_status_name": "Active",
                "default_device_role_name": "Access Switch",
                "default_device_status_name": "Active",
                "delete_policy": "mark_inactive",
                "is_default": "1",
            }
        )
    )
    text = _content_text(response)

    assert response.status_code == 200
    assert "Saved profile" not in text
    assert manager.rows == {}


def test_bundle_record_roundtrip_persists_and_preserves_json():
    """The persisted bundle JSON survives from_mapping/as_dict and is preserved by
    with_run_history when a later (skipped/failed) run does not supply a new one."""
    rec = ForwardConnectionProfileRecord(name="p", last_support_bundle_json='{"a":1}')
    rehydrated = ForwardConnectionProfileRecord.from_mapping(rec.as_dict())
    assert rehydrated.last_support_bundle_json == '{"a":1}'
    # A run that supplies no bundle keeps the previous one.
    after_skip = rehydrated.with_run_history(last_run_at="t")
    assert after_skip.last_support_bundle_json == '{"a":1}'
    # A run that supplies a new bundle overwrites.
    after_run = rehydrated.with_run_history(last_support_bundle_json='{"b":2}')
    assert after_run.last_support_bundle_json == '{"b":2}'


def test_support_bundle_download_serves_persisted_bundle(monkeypatch):
    default = ForwardConnectionProfileRecord(
        name="primary", is_default=True, last_support_bundle_json='{"ok":true}'
    )
    other = ForwardConnectionProfileRecord(name="secondary", last_support_bundle_json='{"x":1}')
    monkeypatch.setattr(views, "_iter_persisted_profile_records", lambda: (default, other))

    response = views.ForwardSupportBundleDownloadView().get(request=SimpleNamespace(GET={}))
    assert response.status_code == 200
    assert _content_text(response) == '{"ok":true}'

    # explicit ?profile= selects that profile
    picked = views.ForwardSupportBundleDownloadView().get(
        request=SimpleNamespace(GET={"profile": "secondary"})
    )
    assert _content_text(picked) == '{"x":1}'


def test_support_bundle_download_404_when_no_bundle(monkeypatch):
    monkeypatch.setattr(views, "_iter_persisted_profile_records", lambda: ())
    response = views.ForwardSupportBundleDownloadView().get(request=SimpleNamespace(GET={}))
    assert response.status_code == 404
