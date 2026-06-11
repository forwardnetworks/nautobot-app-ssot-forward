from __future__ import annotations

import importlib
import importlib.abc
import sys


def test_forward_integration_imports_without_diffsync():
    blocked_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "diffsync" or name.startswith("diffsync.")
        or name.startswith("forward_nautobot.integrations.forward.adapters")
        or name.startswith("forward_nautobot.integrations.forward.diffsync_models")
    }

    class _BlockDiffSync(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):  # pragma: no cover - import hook
            if fullname == "diffsync" or fullname.startswith("diffsync."):
                raise ModuleNotFoundError(fullname)
            return None

    blocker = _BlockDiffSync()
    sys.meta_path.insert(0, blocker)
    try:
        for name in blocked_modules:
            sys.modules.pop(name, None)
        adapters = importlib.import_module("forward_nautobot.integrations.forward.adapters")
        source = adapters.ForwardSourceAdapter(model_names=("devices",))
        loaded = source.load_rows(
            "devices",
            [
                {
                    "name": "device-1",
                    "location": "site-a",
                    "vendor": "Vendor.CISCO",
                    "model": "N9K",
                    "device_type": "DeviceType.SWITCH",
                }
            ],
        )
        target = adapters.NautobotTargetAdapter(model_names=("devices",))
        planned = target.plan_rows("devices", [loaded[0].fields])
        assert source.count("devices") == 1
        assert source.as_support_summary()["model_counts"]["devices"] == 1
        assert loaded[0].fields["name"] == "device-1"
        assert planned[0].fields["name"] == "device-1"
        assert target.count("devices") == 1
    finally:
        sys.meta_path.remove(blocker)
        for name, module in blocked_modules.items():
            sys.modules[name] = module
