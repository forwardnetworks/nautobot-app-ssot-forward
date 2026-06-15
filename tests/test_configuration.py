from forward_nautobot.models import ForwardConnectionProfileRecord
from forward_nautobot.models import ForwardPluginConfiguration


def test_connection_profile_record_round_trips_connection_settings():
    profile = ForwardConnectionProfileRecord(
        name="default",
        base_url="https://fwd.example",
        username="alice",
        password="secret",
        network_id="net-fixture-1",
        snapshot_id="latestProcessed",
        enabled_models=("devices", "locations"),
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        is_default=True,
        last_run_at="2026-06-10T12:00:00Z",
        last_failure="",
        last_support_bundle="bundle-1",
        last_query_reference="forward_devices.nqe",
        last_query_mode="bundled_nqe_query_id_diff",
        last_snapshot_id="snap-1",
    )

    settings = profile.to_connection_settings()

    assert settings.base_url == "https://fwd.example"
    assert settings.username == "alice"
    assert settings.network_id == "net-fixture-1"
    assert settings.verify_tls is True
    assert profile.as_dict()["enabled_models"] == ["devices", "locations"]
    assert profile.write_ready
    assert profile.as_dict()["default_device_role_name"] == "Access Switch"
    assert profile.as_dict()["delete_policy"] == "mark_inactive"
    assert profile.effective_delete_policy == "mark_inactive"
    assert profile.as_dict()["last_run_at"] == "2026-06-10T12:00:00Z"
    assert profile.status_record().as_dict()["last_support_bundle"] == "bundle-1"
    assert profile.status_record().as_dict()["last_query_reference"] == "forward_devices.nqe"
    assert profile.status_record().as_dict()["last_query_mode"] == "bundled_nqe_query_id_diff"
    assert profile.status_record().as_dict()["last_snapshot_id"] == "snap-1"


def test_connection_profile_record_invalid_delete_policy_defaults_to_ignore():
    profile = ForwardConnectionProfileRecord(name="invalid", delete_policy="bogus")

    assert profile.effective_delete_policy == "ignore"


def test_plugin_configuration_tracks_default_profile():
    primary = ForwardConnectionProfileRecord(
        name="primary",
        network_id="net-fixture-1",
        is_default=True,
    )
    secondary = ForwardConnectionProfileRecord(
        name="secondary",
        network_id="net-fixture-1",
    )
    configuration = ForwardPluginConfiguration(
        default_profile_name="primary",
        profiles=(primary, secondary),
        notes=("seeded from fixture",),
    )

    assert configuration.get_default_profile() == primary
    assert configuration.get_profile("secondary") == secondary
    assert configuration.as_dict()["profiles"][0]["name"] == "primary"
    assert primary.missing_write_defaults() == (
        "default_location_type_name",
        "default_location_status_name",
        "default_device_role_name",
        "default_device_status_name",
    )


def test_plugin_configuration_surfaces_status_summary():
    primary = ForwardConnectionProfileRecord(
        name="primary",
        default_location_type_name="Building",
        default_location_status_name="Active",
        default_device_role_name="Access Switch",
        default_device_status_name="Active",
        delete_policy="mark_inactive",
        is_default=True,
        last_query_reference="forward_devices.nqe",
        last_query_mode="bundled_nqe_query_id_diff",
    )
    configuration = ForwardPluginConfiguration(
        default_profile_name="primary",
        profiles=(primary,),
        last_snapshot_id="snap-2",
        metadata={"last_run": "2026-06-10T12:00:00Z", "current_policy": "mark_inactive"},
    )

    status = configuration.status_summary()

    assert status["default_profile_name"] == "primary"
    assert status["default_profile"]["write_ready"] is True
    assert status["ready_profiles"] == 1
    assert status["needs_attention_profiles"] == 0
    assert status["last_run"] == "2026-06-10T12:00:00Z"
    assert status["last_failure"] == ""
    assert status["last_support_bundle"] == ""
    assert status["last_query_reference"] == "forward_devices.nqe"
    assert status["last_query_mode"] == "bundled_nqe_query_id_diff"
    assert status["last_snapshot_id"] == "snap-2"
    assert status["current_policy"] == "mark_inactive"
    assert primary.status_record().as_dict()["delete_policy"] == "mark_inactive"
