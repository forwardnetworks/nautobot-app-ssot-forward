from types import SimpleNamespace

from forward_nautobot.models import ForwardConnectionProfileRecord
import forward_nautobot.views as views
from forward_nautobot.views import ForwardConfigurationView
from forward_nautobot.views import ForwardHomeView


def test_home_view_mentions_forward_plugin():
    response = ForwardHomeView().get()

    assert response.status_code == 200
    assert "Forward Nautobot plugin." in response.content


def test_configuration_view_mentions_profile_fields():
    response = ForwardConfigurationView().get()

    assert response.status_code == 200
    assert "Persistent connection profiles" in response.content
    assert "query_contract_version" in response.content
    assert "default_device_role_name" in response.content
    assert "delete_policy" in response.content
    assert "Editable form fields" in response.content
    assert "Profile Editor" in response.content
    assert "<form" in response.content
    assert 'name="delete_policy"' in response.content
    assert "Save profile" in response.content


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
                    )
                )
            ]

    monkeypatch.setattr(views, "ForwardConnectionProfile", SimpleNamespace(objects=_FakeManager()))

    response = ForwardConfigurationView().get()

    assert response.status_code == 200
    assert "Profile Status" in response.content
    assert "primary" in response.content
    assert "Ready profiles" in response.content
    assert "mark_inactive" in response.content
    assert "Last run" in response.content
    assert "Last failure" in response.content
    assert "Last support bundle" in response.content


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

    assert response.status_code == 200
    assert "Saved profile primary." in response.content
    assert "primary" in response.content
    assert "mark_inactive" in response.content
    assert "Ready profiles" in response.content
    assert "secret" not in response.content
    assert manager.rows["primary"].enabled_models == ["devices", "interfaces"]
    assert manager.rows["primary"].is_default is True


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

    assert response.status_code == 200
    assert "Saved profile" not in response.content
    assert manager.rows == {}
