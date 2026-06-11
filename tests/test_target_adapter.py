import forward_nautobot.integrations.forward.adapters as adapters

from forward_nautobot.integrations.forward.adapters import ForwardSourceAdapter
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


def test_target_adapter_loads_current_orm_state_when_available(monkeypatch):
    location = adapters.ForwardLocation(name="SITE-ALPHA", city="Austin", country="US")

    class _FakeManager:
        def all(self):
            return [location]

    class _FakeApps:
        def __init__(self, models):
            self.models = models

        def get_model(self, app_label, model_name):
            return self.models[(app_label, model_name)]

    models = {
        ("dcim", "location"): type("LocationModel", (), {"objects": _FakeManager()}),
    }
    monkeypatch.setattr(adapters, "django_apps", _FakeApps(models))

    target = NautobotTargetAdapter(model_names=("locations",))

    target.load()

    assert target.count("locations") == 1
    assert target.get_all("locations")[0].dict()["name"] == "SITE-ALPHA"
    assert target.get_all("locations")[0].dict()["city"] == "Austin"
    assert target.get_all("locations")[0].dict()["country"] == "US"
