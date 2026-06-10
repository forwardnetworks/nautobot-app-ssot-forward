from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter


def test_target_adapter_plans_raw_rows_without_normalization():
    adapter = NautobotTargetAdapter(model_names=("devices",))
    rows = [
        {
            "name": "device-1",
            "location": "Site A",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        }
    ]

    planned = adapter.plan_rows("devices", rows)

    assert adapter.count("devices") == 1
    assert planned[0].record_key == "device-1"
    assert planned[0].fields == rows[0]
    assert planned[0].nautobot_scope == "dcim.device"
    assert adapter.get_all("devices")[0].dict()["name"] == "device-1"
