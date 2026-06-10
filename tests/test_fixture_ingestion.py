from __future__ import annotations

import json
from pathlib import Path

from forward_nautobot.integrations.forward.adapters import ForwardSourceAdapter
from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "forward_ingestion_sample.json"


def test_fixture_ingestion_syncs_raw_rows_without_normalization():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    model_names = ("locations", "platforms", "device_types", "devices")

    source = ForwardSourceAdapter(model_names=model_names)
    target = NautobotTargetAdapter(model_names=model_names)

    loaded_counts: dict[str, int] = {}
    for model_name in model_names:
        rows = payload[model_name]
        loaded = source.load_rows(model_name, rows)
        loaded_counts[model_name] = len(loaded)

    diff = source.sync_to(target)

    assert loaded_counts == {
        "locations": 2,
        "platforms": 1,
        "device_types": 1,
        "devices": 2,
    }
    assert diff.summary()["create"] == 6
    assert source.count("devices") == 2
    assert target.count("devices") == 2
    assert target.get_all("devices")[0].dict()["location"] == "SITE-ALPHA"
    assert source.as_support_summary()["model_counts"]["devices"] == 2
    assert target.as_support_summary()["planned_counts"]["devices"] == 2
