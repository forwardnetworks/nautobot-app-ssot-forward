from __future__ import annotations

import os
from importlib import resources

import pytest

from forward_nautobot.integrations.forward.client import ForwardClient
from forward_nautobot.integrations.forward.adapters import ForwardSourceAdapter
from forward_nautobot.integrations.forward.adapters import NautobotTargetAdapter
from forward_nautobot.integrations.forward.models import ForwardConnectionSettings
from forward_nautobot.integrations.forward.models import ForwardQuerySpec
from forward_nautobot.integrations.forward.models import ForwardSyncSpec
from forward_nautobot.integrations.forward.planner import ForwardIngestionPlanner
from forward_nautobot.integrations.forward.planner import ForwardIngestionRequest
from forward_nautobot.integrations.forward.support import build_support_bundle
from forward_nautobot.integrations.forward.runner import ForwardSyncRunner


def _live_settings() -> ForwardConnectionSettings | None:
    base_url = os.environ.get("FORWARD_LIVE_BASE_URL", "https://fwd.app").strip()
    username = os.environ.get("FORWARD_LIVE_USERNAME", "").strip()
    password = os.environ.get("FORWARD_LIVE_PASSWORD", "").strip()
    network_id = os.environ.get("FORWARD_LIVE_NETWORK_ID", "").strip()
    if not username or not password or not network_id:
        return None
    return ForwardConnectionSettings(
        base_url=base_url,
        username=username,
        password=password,
        network_id=network_id,
    )


def _load_query_text(filename: str) -> str:
    package = resources.files("forward_nautobot.integrations.forward.queries")
    return (package / filename).read_text(encoding="utf-8")


def _run_live_query(settings: ForwardConnectionSettings, filename: str):
    client = ForwardClient(settings)
    query_text = _load_query_text(filename)
    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_text=query_text),
        network_id=settings.network_id,
        snapshot_id=os.environ.get("FORWARD_LIVE_SNAPSHOT_ID", "latestProcessed"),
        fetch_all=False,
        limit=3,
    )
    return client, query_text, rows


@pytest.mark.integration
def test_live_device_ingestion_contract():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    client, query_text, rows = _run_live_query(settings, "forward_devices.nqe")

    assert rows, "live device query returned no rows"
    first_row = rows[0]
    assert set(first_row) == {"name", "location", "vendor", "model", "device_type"}
    assert first_row["name"]
    assert first_row["vendor"]
    assert first_row["device_type"]

    adapter = ForwardSourceAdapter(model_names=("devices",))
    loaded = adapter.load_rows("devices", rows)
    assert adapter.count("devices") == len(rows)
    assert loaded[0].fields == first_row

    target = NautobotTargetAdapter(model_names=("devices",))
    planned = target.plan_rows("devices", rows)
    assert target.count("devices") == len(rows)
    assert planned[0].fields == first_row

    runner = ForwardSyncRunner(client)
    report = runner.preview(
        ForwardSyncSpec(
            mode="preview",
            connection=settings,
            query=ForwardQuerySpec(query_text=query_text),
            fetch_all=False,
            limit=3,
            model_names=("devices",),
        )
    )
    bundle = build_support_bundle(
        report,
        sample_size=1,
        source_summary=adapter.as_support_summary(),
        target_summary=target.as_support_summary(),
    )
    assert bundle.row_count >= 1
    assert bundle.sample_rows[0]["name"] == first_row["name"]
    assert bundle.source_summary["model_counts"]["devices"] == len(rows)
    assert bundle.target_summary["planned_counts"]["devices"] == len(rows)


@pytest.mark.integration
def test_live_location_ingestion_contract():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    _, _, rows = _run_live_query(settings, "forward_locations.nqe")
    assert rows, "live location query returned no rows"
    first_row = rows[0]
    assert set(first_row) == {"name", "city", "country"}
    assert first_row["name"]

    adapter = ForwardSourceAdapter(model_names=("locations",))
    loaded = adapter.load_rows("locations", rows)
    assert adapter.count("locations") == len(rows)
    assert loaded[0].fields == first_row

    target = NautobotTargetAdapter(model_names=("locations",))
    planned = target.plan_rows("locations", rows)
    assert target.count("locations") == len(rows)
    assert planned[0].fields == first_row


@pytest.mark.integration
def test_live_platform_ingestion_contract():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    _, _, rows = _run_live_query(settings, "forward_platforms.nqe")
    assert rows, "live platform query returned no rows"
    first_row = rows[0]
    assert set(first_row) == {"name", "manufacturer", "device_type"}
    assert first_row["name"]

    adapter = ForwardSourceAdapter(model_names=("platforms",))
    loaded = adapter.load_rows("platforms", rows)
    assert adapter.count("platforms") == len(rows)
    assert loaded[0].fields == first_row

    target = NautobotTargetAdapter(model_names=("platforms",))
    planned = target.plan_rows("platforms", rows)
    assert target.count("platforms") == len(rows)
    assert planned[0].fields == first_row


@pytest.mark.integration
def test_live_device_type_ingestion_contract():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    _, _, rows = _run_live_query(settings, "forward_device_types.nqe")
    assert rows, "live device type query returned no rows"
    first_row = rows[0]
    assert set(first_row) == {"name", "color"}
    assert first_row["name"]

    adapter = ForwardSourceAdapter(model_names=("device_types",))
    loaded = adapter.load_rows("device_types", rows)
    assert adapter.count("device_types") == len(rows)
    assert loaded[0].fields == first_row

    target = NautobotTargetAdapter(model_names=("device_types",))
    planned = target.plan_rows("device_types", rows)
    assert target.count("device_types") == len(rows)
    assert planned[0].fields == first_row


@pytest.mark.integration
def test_live_combined_ingestion_plan_contract():
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    client = ForwardClient(settings)
    planner = ForwardIngestionPlanner(client)
    plan = planner.run(
        ForwardIngestionRequest(
            connection=settings,
            model_names=("locations", "platforms", "device_types", "devices"),
            fetch_all=False,
            limit=3,
        )
    )

    assert len(plan.reports) == 4
    assert plan.reports[0].row_count >= 1
    assert plan.reports[0].query_contract_version == "v1"
    assert plan.source_summary["model_counts"]["devices"] >= 1
    assert plan.target_summary["planned_counts"]["devices"] >= 1
    assert plan.write_summary["create"] >= 1
    assert plan.configuration_status["profile_provided"] is False
    assert plan.configuration_status["delete_policy"] == "ignore"
    assert plan.configuration_status["missing_defaults"] == []
    assert plan.diff_summary["create"] >= 1

    bundle = build_support_bundle(
        plan.reports[0],
        sample_size=1,
        source_summary=plan.source_summary,
        target_summary=plan.target_summary,
        write_summary=plan.write_summary,
        configuration_status=plan.configuration_status,
    )
    assert bundle.source_summary["model_counts"]["devices"] >= 1
    assert bundle.target_summary["planned_counts"]["devices"] >= 1
    assert bundle.write_summary["create"] >= 1
    assert bundle.configuration_status["delete_policy"] == "ignore"
    assert bundle.configuration_status["missing_defaults"] == []
