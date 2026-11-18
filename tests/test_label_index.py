"""Label index: every numeric figure in a bundle can be found by a readable name."""

import re

from forward_nautobot.integrations.forward.support import (
    build_label_index,
    build_support_bundle,
    redact_support_bundle_payload,
)


def _resolve(payload, path):
    """Follow a path like 'a.b[1].c' without using the code under test."""
    node = payload
    for token in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        node = node[int(token[1:-1])] if token.startswith("[") else node[token]
    return node


def test_every_numeric_figure_is_indexed_and_its_path_resolves_to_that_figure():
    payload = {
        "diff_summary": {"create": 4, "update": 2},
        "snapshot_metrics": {"numSuccessfulDevices": 98},
        "slices": [{"name": "devices", "count": 7}],
    }
    index = build_label_index(payload)
    assert {_resolve(payload, entry["figure_path"]) for entry in index} == {4, 2, 98, 7}
    assert len(index) == 4


def test_labels_read_as_words_not_paths():
    index = build_label_index({"diff_summary": {"create": 4}})
    assert [e["figure_label"] for e in index] == ["diff summary / create"]


def test_booleans_text_and_sample_rows_are_not_figures():
    payload = {
        "ready": True,
        "name": "x",
        "sample_rows": [{"serial": 12345}],
        "label_index": {"old": 1},
        "count": 3,
    }
    assert [e["figure_path"] for e in build_label_index(payload)] == ["count"]


def test_two_figures_whose_labels_collide_are_both_kept():
    payload = {"a_b": 1, "a b": 2}  # both read as "a b"
    index = build_label_index(payload)
    assert len(index) == 2
    assert sorted(_resolve(payload, e["figure_path"]) for e in index) == [1, 2]


def test_a_built_bundle_carries_an_index_that_points_at_real_figures():
    from forward_nautobot.integrations.forward.models import ForwardSyncReport

    report = ForwardSyncReport(
        mode="live",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="saved",
        query_reference="q",
        row_count=11,
        rows=(),
        planned_models=(),
        notes=(),
        snapshot_metrics={"numSuccessfulDevices": 98},
        available_snapshots=(),
    )
    bundle = build_support_bundle(
        report, diff_summary={"create": 4}, diagnostics={"api_usage": {"http_429": 0}}
    ).as_dict()

    by_label = {e["figure_label"]: e["figure_path"] for e in bundle["diagnostics"]["label_index"]}
    assert by_label["row count"] == "row_count"
    assert "diff summary / create" in by_label
    assert "diagnostics / api usage / http 429" in by_label


def test_the_index_survives_external_sharing():
    entries = [{"figure_label": "row count", "figure_path": "row_count"}]
    bundle = {"diagnostics": {"label_index": entries}}
    shared = redact_support_bundle_payload(bundle, sharing_profile="external")
    assert shared["diagnostics"]["label_index"] == entries


def test_raw_rows_and_before_after_values_are_not_indexed():
    payload = {"slices": {"devices": {"rows": [{"serial": 9}], "count": 1}}, "before": {"x": 2}}
    assert [e["figure_path"] for e in build_label_index(payload)] == ["slices.devices.count"]


def test_generic_label_and_path_values_elsewhere_in_a_bundle_stay_redacted_externally():
    """Redaction allowlists by key name at every depth; the index must not widen it.

    Component labels, snapshot labels and raw row paths all use these common names.
    """
    bundle = {
        "diagnostics": {
            "label_index": [{"figure_label": "row count", "figure_path": "row_count"}],
            "diff_detail": {"slices": {"inventory_items": {"rows": [{"label": "PSU-1"}]}}},
        },
        "available_snapshots": [{"label": "snap-1 | processed | 2026-01-01", "path": "/x"}],
    }

    shared = redact_support_bundle_payload(bundle, sharing_profile="external")

    assert shared["diagnostics"]["label_index"][0]["figure_label"] == "row count"
    row = shared["diagnostics"]["diff_detail"]["slices"]["inventory_items"]["rows"][0]
    assert row["label"] == "[REDACTED]"
    assert shared["available_snapshots"][0]["label"] == "[REDACTED]"
    assert shared["available_snapshots"][0]["path"] == "[REDACTED]"
