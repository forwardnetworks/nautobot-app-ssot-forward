from forward_nautobot.integrations.forward.write_contract import ForwardWriteContractAdvisor
from forward_nautobot.models import ForwardConnectionProfileRecord
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS


def test_locations_are_blocked_until_location_defaults_are_set():
    advisor = ForwardWriteContractAdvisor()
    mapping = next(item for item in CORE_MODEL_MAPPINGS if item.slug == "locations")

    readiness = advisor.readiness_for(
        mapping,
        profile=ForwardConnectionProfileRecord(name="profile"),
        row={"name": "SITE-ALPHA", "city": "Metropolis", "country": "United States"},
    )

    assert readiness.write_ready is False
    assert "default_location_type_name" in readiness.blocked_by
    assert "default_location_status_name" in readiness.blocked_by


def test_devices_are_blocked_until_device_defaults_are_set():
    advisor = ForwardWriteContractAdvisor()
    mapping = next(item for item in CORE_MODEL_MAPPINGS if item.slug == "devices")

    readiness = advisor.readiness_for(
        mapping,
        profile=ForwardConnectionProfileRecord(name="profile"),
        row={
            "name": "device-1",
            "location": "SITE-ALPHA",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        },
    )

    assert readiness.write_ready is False
    assert "default_device_role_name" in readiness.blocked_by
    assert "default_device_status_name" in readiness.blocked_by


def test_device_types_are_blocked_when_contract_lacks_manufacturer():
    advisor = ForwardWriteContractAdvisor()
    mapping = next(item for item in CORE_MODEL_MAPPINGS if item.slug == "device_types")

    readiness = advisor.readiness_for(mapping, row={"name": "DeviceType.SWITCH"})

    assert readiness.write_ready is False
    assert readiness.missing_contract_fields == ("manufacturer",)
