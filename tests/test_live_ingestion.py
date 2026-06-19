from __future__ import annotations

import os
from importlib import resources

import pytest

from forward_nautobot.integrations.forward.adapters import (
    ForwardSourceAdapter,
    NautobotTargetAdapter,
)
from forward_nautobot.integrations.forward.exceptions import ForwardClientError
from forward_nautobot.integrations.forward.models import (
    ForwardConnectionSettings,
    ForwardQuerySpec,
    ForwardSyncReport,
    ForwardSyncSpec,
)
from forward_nautobot.integrations.forward.registry import get_model_mapping, get_model_mappings
from forward_nautobot.integrations.forward.support import build_support_bundle

try:
    from forward_nautobot.integrations.forward.client import ForwardClient
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    ForwardClient = None

try:
    from forward_nautobot.integrations.forward.planner import (
        ForwardIngestionPlanner,
        ForwardIngestionRequest,
    )
    from forward_nautobot.integrations.forward.runner import ForwardSyncRunner
except ModuleNotFoundError:  # pragma: no cover - local shell without test deps
    ForwardIngestionPlanner = None
    ForwardIngestionRequest = None
    ForwardSyncRunner = None


def _live_settings() -> ForwardConnectionSettings | None:
    base_url = os.environ.get("FORWARD_LIVE_BASE_URL", "https://fwd.app").strip()
    username = os.environ.get("FORWARD_LIVE_USERNAME", "").strip()
    password = os.environ.get("FORWARD_LIVE_PASSWORD", "").strip()
    network_id = os.environ.get("FORWARD_LIVE_NETWORK_ID", "").strip()
    verify_tls = os.environ.get("FORWARD_LIVE_VERIFY_TLS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not username or not password or not network_id:
        return None
    return ForwardConnectionSettings(
        base_url=base_url,
        username=username,
        password=password,
        network_id=network_id,
        verify_tls=verify_tls,
    )


def _load_query_text(filename: str) -> str:
    package = resources.files("forward_nautobot.integrations.forward.queries")
    return (package / filename).read_text(encoding="utf-8")


_LIVE_LOCATION_NAMES_CACHE: dict[tuple[str, str, str], tuple[str, ...]] = {}
_LIVE_DEVICE_NAMES_CACHE: dict[tuple[str, str, str], tuple[str, ...]] = {}


def _live_cache_key(settings: ForwardConnectionSettings) -> tuple[str, str, str]:
    return (settings.base_url, settings.username, settings.network_id)


def _run_live_query(
    settings: ForwardConnectionSettings,
    filename: str,
    *,
    parameters: dict[str, object] | None = None,
    limit: int = 3,
    fetch_all: bool = False,
):
    if ForwardClient is None:  # pragma: no cover - local shell without test deps
        pytest.skip("live Forward ingestion tests require the full dependency set")
    client = ForwardClient(settings)
    query_text = _load_query_text(filename)
    rows = client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_text=query_text, parameters=parameters or {}),
        network_id=settings.network_id,
        snapshot_id=os.environ.get("FORWARD_LIVE_SNAPSHOT_ID", "latestProcessed"),
        fetch_all=fetch_all,
        limit=limit,
    )
    return client, query_text, rows


def _live_location_names(settings: ForwardConnectionSettings) -> tuple[str, ...]:
    cache_key = _live_cache_key(settings)
    if cache_key not in _LIVE_LOCATION_NAMES_CACHE:
        _, _, rows = _run_live_query(settings, "forward_locations.nqe", limit=25)
        _LIVE_LOCATION_NAMES_CACHE[cache_key] = tuple(
            row["name"] for row in rows if row.get("name")
        )
    return _LIVE_LOCATION_NAMES_CACHE[cache_key]


def _live_device_names(
    settings: ForwardConnectionSettings,
    *,
    location_names: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    cache_key = _live_cache_key(settings)
    if cache_key not in _LIVE_DEVICE_NAMES_CACHE:
        names = location_names if location_names is not None else _live_location_names(settings)
        _, _, rows = _run_live_query(
            settings,
            "forward_devices.nqe",
            parameters={"forward_location_names": list(names)},
            limit=25,
        )
        _LIVE_DEVICE_NAMES_CACHE[cache_key] = tuple(row["name"] for row in rows if row.get("name"))
    return _LIVE_DEVICE_NAMES_CACHE[cache_key]


def _require_live_query_path(settings: ForwardConnectionSettings, query_path: str):
    _require_live_client()
    client = ForwardClient(settings)
    try:
        return client.resolve_query_spec(ForwardQuerySpec(query_path=query_path))
    except ForwardClientError as exc:
        pytest.skip(
            f"live Forward query path `{query_path}` is not published on this host yet: {exc}"
        )


def _assert_contract_row(rows, expected_keys):
    assert rows, "live query returned no rows"
    first_row = rows[0]
    assert set(first_row) == set(expected_keys)
    return first_row


def _require_live_planner():
    if (
        ForwardClient is None
        or ForwardIngestionPlanner is None
        or ForwardIngestionRequest is None
        or ForwardSyncRunner is None
    ):  # pragma: no cover - local shell without test deps
        pytest.skip("live Forward ingestion tests require the full dependency set")


def _require_live_client():
    if ForwardClient is None:  # pragma: no cover - local shell without test deps
        pytest.skip("live Forward ingestion tests require the full dependency set")


def _counting_request_wrapper(original_request, calls):
    def wrapped_request(self, method, path, **kwargs):
        calls[(method, path)] = calls.get((method, path), 0) + 1
        return original_request(self, method, path, **kwargs)

    return wrapped_request


@pytest.mark.integration
def test_live_async_execution_smoke():
    _require_live_client()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")

    query_path = (
        os.environ.get(
            "FORWARD_LIVE_ASYNC_QUERY_PATH",
            get_model_mapping("devices").forward_query_path,
        )
    ).strip()
    if not query_path:
        query_path = get_model_mapping("devices").forward_query_path
    _require_live_query_path(settings, query_path)

    client = ForwardClient(settings)
    resolved = client.resolve_query_spec(
        ForwardQuerySpec(
            query_path=query_path,
            query_repository="org",
        )
    )
    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(
            query_id=resolved.resolved_query_id or resolved.query_id or "",
            commit_id=resolved.resolved_commit_id or resolved.commit_id,
        ),
        network_id=settings.network_id,
        snapshot_id=os.environ.get("FORWARD_LIVE_SNAPSHOT_ID", "latestProcessed"),
        fetch_all=False,
        limit=3,
    )

    assert rows, "live async smoke returned no rows"
    first_row = rows[0]
    assert "Device" in first_row
    assert len(first_row) >= 2


@pytest.mark.integration
def test_live_device_ingestion_contract():
    _require_live_planner()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    _require_live_query_path(settings, "/forward_nautobot_validation/forward_devices")

    location_names = _live_location_names(settings)
    client = ForwardClient(settings)
    runner = ForwardSyncRunner(client)
    spec = ForwardSyncSpec(
        mode="preview",
        connection=settings,
        query=ForwardQuerySpec(
            query_path="/forward_nautobot_validation/forward_devices",
            parameters={"forward_location_names": list(location_names)},
        ),
        fetch_all=False,
        limit=3,
        model_names=("devices",),
    )
    report = runner.preview(spec)
    rows = list(report.rows)

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
def test_live_device_ingestion_contract_via_async_execution():
    _require_live_client()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    _require_live_query_path(settings, "/forward_nautobot_validation/forward_devices")

    location_names = _live_location_names(settings)
    client = ForwardClient(settings)
    rows = client.run_nqe_query_async(
        query_spec=ForwardQuerySpec(
            query_path="/forward_nautobot_validation/forward_devices",
            parameters={"forward_location_names": list(location_names)},
        ),
        network_id=settings.network_id,
        snapshot_id=os.environ.get("FORWARD_LIVE_SNAPSHOT_ID", "latestProcessed"),
        fetch_all=False,
        limit=3,
    )

    assert rows, "live async device query returned no rows"
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

    bundle = build_support_bundle(
        ForwardSyncReport(
            mode="preview",
            source_url=settings.base_url.rstrip("/"),
            network_id=settings.network_id,
            snapshot_id=os.environ.get("FORWARD_LIVE_SNAPSHOT_ID", "latestProcessed"),
            query_mode="bundled_nqe_query_id_async",
            query_reference="org:/forward_nautobot_validation/forward_devices",
            row_count=len(rows),
            rows=tuple(rows),
            baseline_snapshot_id="",
            query_contract_version="",
            snapshot_metrics={},
            available_snapshots=(),
            planned_models=("devices",),
            notes=(),
        ),
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
    _require_live_query_path(settings, "/forward_nautobot_validation/forward_locations")

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
    _require_live_query_path(settings, "/forward_nautobot_validation/forward_platforms")

    location_names = _live_location_names(settings)
    _, _, rows = _run_live_query(
        settings,
        "forward_platforms.nqe",
        parameters={"forward_location_names": list(location_names)},
    )
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
    _require_live_query_path(settings, "/forward_nautobot_validation/forward_device_types")

    location_names = _live_location_names(settings)
    _, _, rows = _run_live_query(
        settings,
        "forward_device_types.nqe",
        parameters={"forward_location_names": list(location_names)},
    )
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
@pytest.mark.parametrize(
    ("filename", "model_slug", "expected_keys"),
    (
        ("forward_vlans.nqe", "vlans", ("site", "vid", "name", "status")),
        ("forward_vrfs.nqe", "vrfs", ("name", "rd", "description", "enforce_unique")),
        ("forward_prefixes_ipv4.nqe", "ipv4_prefixes", ("vrf", "prefix", "status")),
        ("forward_prefixes_ipv6.nqe", "ipv6_prefixes", ("vrf", "prefix", "status")),
        (
            "forward_ip_addresses.nqe",
            "ip_addresses",
            ("device", "interface", "vrf", "address", "host_ip", "prefix_length", "status"),
        ),
        (
            "forward_inventory_items.nqe",
            "inventory_items",
            (
                "device",
                "manufacturer",
                "name",
                "label",
                "part_id",
                "serial",
                "asset_tag",
                "role",
                "status",
                "discovered",
                "description",
            ),
        ),
        (
            "forward_modules.nqe",
            "modules",
            (
                "device",
                "module_bay",
                "manufacturer",
                "model",
                "part_number",
                "status",
                "serial",
                "asset_tag",
                "description",
            ),
        ),
    ),
)
def test_live_additional_ingestion_contracts(filename, model_slug, expected_keys):
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    _require_live_query_path(settings, get_model_mapping(model_slug).forward_query_path)

    if filename == "forward_vlans.nqe":
        parameters = {"forward_location_names": list(_live_location_names(settings))}
    else:
        parameters = {"forward_device_names": list(_live_device_names(settings))}
    _, _, rows = _run_live_query(settings, filename, parameters=parameters)
    if filename == "forward_modules.nqe" and not rows:
        _, _, rows = _run_live_query(
            settings,
            filename,
            parameters={"forward_device_names": []},
            limit=25,
        )
    if filename == "forward_modules.nqe" and not rows:
        pytest.skip("live Forward snapshot has no module rows for this tranche")
    first_row = _assert_contract_row(rows, expected_keys)

    source = ForwardSourceAdapter(model_names=(model_slug,))
    loaded = source.load_rows(model_slug, rows)
    assert source.count(model_slug) == len(rows)
    assert loaded[0].fields == first_row

    target = NautobotTargetAdapter(model_names=(model_slug,))
    planned = target.plan_rows(model_slug, rows)
    assert target.count(model_slug) == len(rows)
    assert planned[0].fields == first_row


@pytest.mark.integration
def test_live_combined_ingestion_plan_contract():
    _require_live_planner()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    for mapping in get_model_mappings(("locations", "platforms", "device_types", "devices")):
        _require_live_query_path(settings, mapping.forward_query_path)

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
    assert plan.target_summary["model_slugs"] == [
        "locations",
        "platforms",
        "device_types",
        "devices",
    ]
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
    assert bundle.target_summary["model_slugs"] == [
        "locations",
        "platforms",
        "device_types",
        "devices",
    ]
    assert bundle.write_summary["create"] >= 1
    assert bundle.configuration_status["delete_policy"] == "ignore"
    assert bundle.configuration_status["missing_defaults"] == []


@pytest.mark.integration
def test_live_subset_ingestion_plan_contract():
    _require_live_planner()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    for mapping in get_model_mappings(("locations", "devices", "interfaces")):
        _require_live_query_path(settings, mapping.forward_query_path)

    client = ForwardClient(settings)
    planner = ForwardIngestionPlanner(client)
    plan = planner.run(
        ForwardIngestionRequest(
            connection=settings,
            model_names=("locations", "devices", "interfaces"),
            fetch_all=False,
            limit=3,
        )
    )

    assert [report.query_reference for report in plan.reports] == [
        "forward_locations.nqe",
        "forward_devices.nqe",
        "forward_interfaces.nqe",
    ]
    assert [report.planned_models for report in plan.reports] == [
        ("locations",),
        ("devices",),
        ("interfaces",),
    ]
    assert plan.reports[0].query_contract_version == "v1"
    assert plan.reports[1].query_contract_version == "v1"
    assert plan.reports[2].query_contract_version == "v1"
    assert plan.reports[0].row_count >= 1
    assert plan.reports[1].row_count >= 1
    assert plan.write_summary["create"] == sum(report.row_count for report in plan.reports)
    assert plan.diff_summary["create"] == plan.write_summary["create"]
    assert plan.configuration_status["profile_provided"] is False
    assert plan.configuration_status["delete_policy"] == "ignore"


@pytest.mark.integration
def test_live_preview_sync_smoke_is_bounded(monkeypatch):
    _require_live_planner()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    for mapping in get_model_mappings(("locations",)):
        _require_live_query_path(settings, mapping.forward_query_path)

    client = ForwardClient(settings)
    calls: dict[tuple[str, str], int] = {}
    monkeypatch.setattr(
        ForwardClient,
        "_request",
        _counting_request_wrapper(ForwardClient._request, calls),
    )

    runner = ForwardSyncRunner(client)
    query_text = _load_query_text("forward_locations.nqe")
    spec = ForwardSyncSpec(
        mode="preview",
        connection=settings,
        query=ForwardQuerySpec(query_text=query_text),
        fetch_all=False,
        limit=1,
        model_names=("locations",),
    )

    preview_report = runner.preview(spec)
    sync_report = runner.sync(spec)

    assert preview_report.row_count >= 1
    assert preview_report.row_count == sync_report.row_count
    assert preview_report.query_reference == sync_report.query_reference
    assert preview_report.planned_models == ("locations",)
    assert sync_report.planned_models == ("locations",)
    assert calls.get(("GET", "/nqe/repos/org/commits/head/queries"), 0) == 0
    assert calls[("GET", f"/networks/{settings.network_id}/snapshots/latestProcessed")] == 1
    assert calls[("GET", f"/snapshots/{preview_report.snapshot_id}/metrics")] == 1
    assert calls[("GET", f"/networks/{settings.network_id}/snapshots")] == 1
    assert calls[("POST", f"/networks/{settings.network_id}/nqe-executions")] == 2
    assert any(
        method == "GET" and path.startswith(f"/networks/{settings.network_id}/nqe-executions/")
        for method, path in calls
    )


@pytest.mark.integration
def test_live_preview_sync_smoke_for_devices_is_bounded(monkeypatch):
    _require_live_planner()
    settings = _live_settings()
    if settings is None:
        pytest.skip("live Forward credentials not configured")
    for mapping in get_model_mappings(("locations", "devices")):
        _require_live_query_path(settings, mapping.forward_query_path)

    _, _, location_rows = _run_live_query(settings, "forward_locations.nqe")
    assert location_rows, "live location query returned no rows"
    location_name = location_rows[0]["name"]

    client = ForwardClient(settings)
    calls: dict[tuple[str, str], int] = {}
    monkeypatch.setattr(
        ForwardClient,
        "_request",
        _counting_request_wrapper(ForwardClient._request, calls),
    )

    runner = ForwardSyncRunner(client)
    query_text = _load_query_text("forward_devices.nqe")
    spec = ForwardSyncSpec(
        mode="preview",
        connection=settings,
        query=ForwardQuerySpec(
            query_text=query_text,
            parameters={"forward_location_names": [location_name]},
        ),
        fetch_all=False,
        limit=1,
        model_names=("devices",),
    )

    preview_report = runner.preview(spec)
    sync_report = runner.sync(spec)

    assert preview_report.row_count >= 1
    assert preview_report.row_count == sync_report.row_count
    assert preview_report.query_reference == sync_report.query_reference
    assert preview_report.planned_models == ("devices",)
    assert sync_report.planned_models == ("devices",)
    assert calls.get(("GET", "/nqe/repos/org/commits/head/queries"), 0) == 0
    assert calls[("GET", f"/networks/{settings.network_id}/snapshots/latestProcessed")] == 1
    assert calls[("GET", f"/snapshots/{preview_report.snapshot_id}/metrics")] == 1
    assert calls[("GET", f"/networks/{settings.network_id}/snapshots")] == 1
    assert calls[("POST", f"/networks/{settings.network_id}/nqe-executions")] == 2
    assert any(
        method == "GET" and path.startswith(f"/networks/{settings.network_id}/nqe-executions/")
        for method, path in calls
    )
