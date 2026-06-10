from forward_nautobot.integrations.forward.models import ForwardSnapshotInfo
from forward_nautobot.integrations.forward.models import ForwardSyncReport
from forward_nautobot.integrations.forward.support import build_support_bundle


def test_support_bundle_preserves_raw_sample_rows():
    report = ForwardSyncReport(
        mode="preview",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="query_text",
        query_reference="<inline query>",
        row_count=2,
        rows=(
            {"name": "device-1", "location": "alpha"},
            {"name": "device-2", "location": "beta"},
        ),
        available_snapshots=(
            ForwardSnapshotInfo(id="snap-1", label="snap-1"),
        ),
        planned_models=("devices",),
        notes=("preview-only",),
    )

    bundle = build_support_bundle(report, sample_size=1)

    assert bundle.row_count == 2
    assert bundle.sample_rows == ({"name": "device-1", "location": "alpha"},)
    assert bundle.available_snapshots[0]["id"] == "snap-1"


def test_support_bundle_includes_adapter_summaries():
    report = ForwardSyncReport(
        mode="preview",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="query_text",
        query_reference="<inline query>",
        row_count=1,
    )

    bundle = build_support_bundle(
        report,
        source_summary={"model_counts": {"devices": 1}},
        target_summary={"planned_counts": {"devices": 1}},
    )

    assert bundle.source_summary["model_counts"]["devices"] == 1
    assert bundle.target_summary["planned_counts"]["devices"] == 1
