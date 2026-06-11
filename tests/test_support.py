from forward_nautobot.integrations.forward.models import ForwardSnapshotInfo
from forward_nautobot.integrations.forward.models import ForwardSyncReport
from forward_nautobot.integrations.forward.support import classify_failure
from forward_nautobot.integrations.forward.support import build_support_bundle
from forward_nautobot.integrations.forward.support import build_support_bundle_pair
from forward_nautobot.integrations.forward.support import redact_support_bundle_payload


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
        notes=("ssot-sync",),
    )

    bundle = build_support_bundle(report, sample_size=1)

    assert bundle.row_count == 2
    assert bundle.sharing_profile == "external"
    assert bundle.sample_rows == ({"name": "device-1", "location": "alpha"},)
    assert bundle.available_snapshots[0]["id"] == "snap-1"
    assert bundle.query_contract_version == ""
    assert bundle.write_summary == {}
    assert bundle.diff_summary == {}
    assert bundle.configuration_status == {}
    assert bundle.failure_classification == "clean"


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
        write_summary={"create": 1},
        diff_summary={"create": 1},
        configuration_status={"write_ready": False},
    )

    assert bundle.source_summary["model_counts"]["devices"] == 1
    assert bundle.target_summary["planned_counts"]["devices"] == 1
    assert bundle.write_summary["create"] == 1
    assert bundle.diff_summary["create"] == 1
    assert bundle.configuration_status["write_ready"] is False
    assert bundle.failure_classification == "configuration-blocked"


def test_support_bundle_failure_classification_prefers_row_blockers():
    assert (
        classify_failure(
            write_summary={"blocked": 2},
            configuration_status={"write_ready": True},
        )
        == "row-blocked"
    )


def test_support_bundle_redaction_masks_sensitive_fields():
    report = ForwardSyncReport(
        mode="preview",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="query_text",
        query_reference="<inline query>",
        row_count=1,
        rows=({"name": "device-1", "password": "secret"},),
    )

    bundle = build_support_bundle(
        report,
        diagnostics={"token": "abc123", "nested": {"username": "alice"}},
    )

    redacted = bundle.as_redacted_dict()

    assert redacted["sharing_profile"] == "external"
    assert redacted["sample_rows"][0]["password"] == "[REDACTED]"
    assert redacted["sample_rows"][0]["name"] == "[REDACTED]"
    assert redacted["source_url"] == "[REDACTED]"
    assert redacted["diagnostics"]["token"] == "[REDACTED]"
    assert redacted["diagnostics"]["nested"]["username"] == "[REDACTED]"
    assert bundle.as_dict()["sample_rows"][0]["password"] == "secret"
    assert redact_support_bundle_payload({"password": "secret"})["password"] == "[REDACTED]"
    assert bundle.as_shared_dict("internal")["sample_rows"][0]["password"] == "[REDACTED]"


def test_support_bundle_internal_profile_retains_non_secret_details():
    report = ForwardSyncReport(
        mode="preview",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="query_text",
        query_reference="<inline query>",
        row_count=1,
        rows=({"name": "device-1", "password": "secret"},),
    )

    bundle = build_support_bundle(report, sharing_profile="internal")

    redacted = bundle.as_redacted_dict()

    assert bundle.sharing_profile == "internal"
    assert redacted["source_url"] == "https://fwd.example"
    assert redacted["sample_rows"][0]["name"] == "device-1"
    assert redacted["sample_rows"][0]["password"] == "[REDACTED]"


def test_support_bundle_pair_returns_bundle_and_shared_view_together():
    report = ForwardSyncReport(
        mode="preview",
        source_url="https://fwd.example",
        network_id="net-1",
        snapshot_id="snap-1",
        query_mode="query_text",
        query_reference="<inline query>",
        row_count=1,
        rows=({"name": "device-1"},),
    )

    bundle, shared = build_support_bundle_pair(report, sharing_profile="external")

    assert bundle.sharing_profile == "external"
    assert shared == bundle.as_redacted_dict()
