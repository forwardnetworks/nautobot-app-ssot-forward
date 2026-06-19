from forward_nautobot.integrations.forward.adapters import (
    ForwardSourceAdapter,
    NautobotTargetAdapter,
)
from forward_nautobot.integrations.forward.write_path import ForwardWritePlanner


def test_write_planner_surfaces_create_intent_for_raw_rows():
    source = ForwardSourceAdapter(model_names=("devices",))
    target = NautobotTargetAdapter(model_names=("devices",))
    rows = [
        {
            "name": "device-1",
            "location": "Site A",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        },
        {
            "name": "device-2",
            "location": "Site B",
            "vendor": "Vendor.CISCO",
            "model": "N9K",
            "device_type": "DeviceType.SWITCH",
        },
    ]

    source.load_rows("devices", rows)
    write_plan = ForwardWritePlanner().plan(source, target)

    assert write_plan.summary["create"] == 2
    assert write_plan.diff_summary["create"] == 2
    assert write_plan.diff_detail["models"]["devices"]["create"] == 2
    assert [operation.action for operation in write_plan.operations] == ["create", "create"]
    assert write_plan.operations[0].fields == rows[0]
    assert write_plan.slice_policies["devices"]["missing_row_policy"] == "mark_inactive"
