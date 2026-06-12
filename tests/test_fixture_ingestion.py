from __future__ import annotations

import json
from pathlib import Path

from forward_nautobot.fixture_support import fixture_path
from forward_nautobot.integrations.forward.adapters import ForwardSourceAdapter
from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS
from forward_nautobot.integrations.forward import CORE_MODEL_SLUGS


def _identity_key(mapping, row):
    return "|".join(str(row[field]).strip() for field in mapping.identity_fields)


def test_fixture_ingestion_syncs_raw_rows_without_normalization():
    payload = json.loads(Path(fixture_path()).read_text(encoding="utf-8"))
    model_names = CORE_MODEL_SLUGS

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
        "devices": 1,
        "interfaces": 2,
        "vlans": 1,
        "vrfs": 1,
        "ipv4_prefixes": 1,
        "ipv6_prefixes": 1,
        "ip_addresses": 2,
        "inventory_items": 1,
        "modules": 1,
    }
    assert diff.summary()["create"] == 15
    assert source.count("devices") == 1
    assert target.count("devices") == 1
    assert target.get_all("devices")[0].dict()["location"] == "DC01_ModernDC-CDL"
    assert source.as_support_summary()["model_counts"]["devices"] == 1
    assert target.as_support_summary()["planned_counts"]["devices"] == 1


def test_fixture_ingestion_round_trips_every_supported_slice_raw():
    payload = json.loads(Path(fixture_path()).read_text(encoding="utf-8"))

    for mapping in CORE_MODEL_MAPPINGS:
        rows = payload[mapping.slug]
        source = ForwardSourceAdapter(model_names=(mapping.slug,))
        target = NautobotTargetAdapter(model_names=(mapping.slug,))

        loaded = source.load_rows(mapping.slug, rows)
        planned = target.plan_rows(mapping.slug, rows)

        assert source.count(mapping.slug) == len(rows)
        assert target.count(mapping.slug) == len(rows)
        assert source.as_support_summary()["model_counts"][mapping.slug] == len(rows)
        assert target.as_support_summary()["planned_counts"][mapping.slug] == len(rows)
        assert tuple(record.fields for record in loaded) == tuple(dict(row) for row in rows)
        assert tuple(record.fields for record in planned) == tuple(dict(row) for row in rows)
        assert tuple(record.record_key for record in loaded) == tuple(
            _identity_key(mapping, row) for row in rows
        )
        assert tuple(record.record_key for record in planned) == tuple(
            _identity_key(mapping, row) for row in rows
        )
