from __future__ import annotations

import pytest

try:
    from forward_nautobot.integrations.forward.adapters import (
        ForwardSourceAdapter,
        NautobotTargetAdapter,
    )
    from forward_nautobot.integrations.forward.write_path import ForwardWritePlanner

    _HAVE_DEPS = True
except ModuleNotFoundError:  # pragma: no cover - local shell without diffsync
    _HAVE_DEPS = False


pytestmark = pytest.mark.skipif(not _HAVE_DEPS, reason="write-path deps (diffsync) required")


def _plan_for(source_row, target_row):
    source = ForwardSourceAdapter()
    source.load_rows("devices", [source_row])
    target = NautobotTargetAdapter()
    target.load_rows("devices", [target_row])
    return ForwardWritePlanner().plan(source, target)


def test_changed_field_rollup_counts_only_changed_fields():
    plan = _plan_for(
        {"name": "d1", "location": "L", "vendor": "cisco", "model": "A", "device_type": "A"},
        {"name": "d1", "location": "L", "vendor": "cisco", "model": "B", "device_type": "B"},
    )
    assert plan.summary["update"] == 1
    rollup = plan.diff_detail["changed_fields"]["devices"]
    assert rollup == {"model": 1, "device_type": 1}  # location/vendor unchanged -> absent
    assert plan.diff_detail["changed_fields_top"]["model"] == 1


def test_changed_field_rollup_empty_when_no_updates():
    row = {"name": "d1", "location": "L", "vendor": "cisco", "model": "A", "device_type": "A"}
    plan = _plan_for(dict(row), dict(row))  # identical -> no-change
    assert plan.summary["no-change"] == 1
    assert plan.diff_detail["changed_fields"] == {}
    assert plan.diff_detail["changed_fields_top"] == {}
