from __future__ import annotations

from forward_nautobot.integrations.forward.cloud import (
    CLOUD_QUERY_FILES,
    ForwardCloudIngestionPlanner,
    ForwardCloudScope,
)
from forward_nautobot.integrations.forward.contrib_sync import cloud_object_name
from forward_nautobot.integrations.forward.exceptions import ForwardClientError


def _account(account_id: str, cloud_type: str = "CloudType.TYPE_A"):
    return {"account_id": account_id, "name": f"Account {account_id}", "cloud_type": cloud_type}


def _network(account_id: str, network_id: str, *, parent_id: str = "", kind: str = "vpc"):
    return {
        "account_id": account_id,
        "cloud_type": "CloudType.TYPE_A",
        "network_id": network_id,
        "name": f"Network {network_id}",
        "parent_id": parent_id,
        "kind": kind,
        "cidrs": ["192.0.2.0/24"],
    }


def _service(account_id: str, service_id: str, *, vpc_id: str):
    return {
        "account_id": account_id,
        "cloud_type": "CloudType.TYPE_A",
        "service_id": service_id,
        "name": f"Service {service_id}",
        "vpc_id": vpc_id,
        "service_kind": "edge",
    }


class _CloudClient:
    def __init__(self, *, full_rows, diff_rows=None, missing=()):
        self.full_rows = full_rows
        self.diff_rows = diff_rows or {}
        self.missing = set(missing)
        self.full_calls = []
        self.diff_calls = []
        self.index_calls = 0

    def get_nqe_repository_query_index(self, **_kwargs):
        self.index_calls += 1
        return []

    def resolve_query_spec(self, spec):
        query_name = spec.query_path.rsplit("/", 1)[-1]
        slug = next(
            slug
            for slug, query_file in CLOUD_QUERY_FILES.items()
            if query_file.removesuffix(".nqe") == query_name
        )
        if slug in self.missing:
            raise ForwardClientError("not published")
        return spec.with_query_id(f"id-{slug}", f"commit-{slug}")

    @staticmethod
    def _slug_for_spec(spec):
        if spec.resolved_query_id:
            return spec.resolved_query_id.removeprefix("id-")
        query_text = spec.query_text or ""
        for slug in CLOUD_QUERY_FILES:
            if f"@intent Forward {slug.replace('_', ' ')}" in query_text:
                return slug
        raise AssertionError("unable to identify query")

    def run_nqe_query(self, *, query_spec, **kwargs):
        slug = self._slug_for_spec(query_spec)
        self.full_calls.append((slug, query_spec.execution_mode, kwargs))
        return [dict(row) for row in self.full_rows.get(slug, [])]

    def run_nqe_diff(self, *, query_id, **kwargs):
        slug = query_id.removeprefix("id-")
        self.diff_calls.append((slug, kwargs))
        return [dict(row) for row in self.diff_rows.get(slug, [])]


def _run(client, **kwargs):
    return ForwardCloudIngestionPlanner(client).run(
        source_url="https://forward.invalid",
        network_id="network-fixture",
        current_snapshot_id="snapshot-current",
        **kwargs,
    )


def test_cloud_scope_filters_type_and_exact_account_id():
    rows = [
        _account("account-1", "CloudType.TYPE_A"),
        _account("account-2", "type_b"),
    ]

    by_type = ForwardCloudScope.from_account_rows(rows, cloud_types=("TYPE_A",))
    by_id = ForwardCloudScope.from_account_rows(rows, cloud_account_ids=("account-2",))
    combined = ForwardCloudScope.from_account_rows(
        rows,
        cloud_types=("type_a",),
        cloud_account_ids=("account-2",),
    )

    assert by_type.account_ids == frozenset({"account-1"})
    assert by_id.account_ids == frozenset({"account-2"})
    assert combined.account_ids == frozenset()


def test_cloud_scope_keeps_same_account_id_distinct_across_cloud_types():
    rows = [_account("shared", "TYPE_A"), _account("shared", "TYPE_B")]

    scope = ForwardCloudScope.from_account_rows(rows)

    assert scope.account_ids == frozenset({"shared"})
    assert scope.account_keys == frozenset({("type_a", "shared"), ("type_b", "shared")})


def test_first_cloud_baseline_runs_full_async_queries_and_applies_account_closure():
    client = _CloudClient(
        full_rows={
            "cloud_accounts": [_account("account-1"), _account("account-2", "TYPE_B")],
            "cloud_networks": [
                _network("account-1", "network-1"),
                _network("account-2", "network-2"),
            ],
            "cloud_services": [_service("account-1", "service-1", vpc_id="network-1")],
        }
    )

    plan = _run(client, cloud_types=("TYPE_A",))

    assert plan.should_sync is True
    assert [row["account_id"] for row in plan.account_rows] == ["account-1"]
    assert [row["network_id"] for row in plan.network_rows] == ["network-1"]
    assert [row["service_id"] for row in plan.service_rows] == ["service-1"]
    assert {call[0] for call in client.full_calls} == set(CLOUD_QUERY_FILES)
    assert not client.diff_calls
    assert all(not call[2].get("parameters") for call in client.full_calls)


def test_saved_cloud_queries_use_diffs_and_skip_full_hydration_when_unchanged():
    client = _CloudClient(
        full_rows={"cloud_accounts": [_account("account-1")]},
        diff_rows={slug: [] for slug in CLOUD_QUERY_FILES},
    )

    plan = _run(client, baseline_snapshot_id="snapshot-before")

    assert plan.should_sync is False
    assert [call[0] for call in client.full_calls] == ["cloud_accounts"]
    assert {call[0] for call in client.diff_calls} == set(CLOUD_QUERY_FILES)
    assert {report.query_mode for report in plan.reports} == {"bundled_nqe_query_id_diff"}


def test_relevant_saved_query_diff_triggers_complete_async_hydration():
    changed = _network("account-1", "network-2")
    client = _CloudClient(
        full_rows={
            "cloud_accounts": [_account("account-1"), _account("account-2")],
            "cloud_networks": [_network("account-1", "network-1"), changed],
            "cloud_services": [_service("account-1", "service-1", vpc_id="network-1")],
        },
        diff_rows={"cloud_networks": [{"before": {}, "after": changed}]},
    )

    plan = _run(
        client,
        baseline_snapshot_id="snapshot-before",
        cloud_account_ids=("account-1",),
    )

    assert plan.should_sync is True
    assert {row["network_id"] for row in plan.network_rows} == {"network-1", "network-2"}
    assert {call[0] for call in client.full_calls} == set(CLOUD_QUERY_FILES)
    network_report = next(r for r in plan.reports if r.planned_models == ("cloud_networks",))
    assert network_report.query_mode == "bundled_nqe_query_id_diff"
    assert network_report.row_count == 1


def test_missing_saved_cloud_query_falls_back_inline_and_disables_diff_for_slice():
    client = _CloudClient(
        full_rows={
            "cloud_accounts": [_account("account-1")],
            "cloud_networks": [_network("account-1", "network-1")],
            "cloud_services": [],
        },
        diff_rows={"cloud_accounts": [], "cloud_services": []},
        missing={"cloud_networks"},
    )

    plan = _run(client, baseline_snapshot_id="snapshot-before")

    assert plan.should_sync is True
    inline_call = next(call for call in client.full_calls if call[0] == "cloud_networks")
    assert inline_call[1] == "query"
    assert "cloud_networks" not in {call[0] for call in client.diff_calls}
    network_report = next(r for r in plan.reports if r.planned_models == ("cloud_networks",))
    assert network_report.query_mode == "bundled_nqe_inline_async"
    assert any("diffs are disabled" in note for note in network_report.notes)


def test_delete_only_cloud_delta_is_reported_but_never_hydrated_for_removal():
    removed = _service("account-1", "service-removed", vpc_id="network-1")
    client = _CloudClient(
        full_rows={"cloud_accounts": [_account("account-1")]},
        diff_rows={"cloud_services": [{"before": removed, "after": {}}]},
    )

    plan = _run(client, baseline_snapshot_id="snapshot-before")

    assert plan.should_sync is False
    assert plan.as_dict()["delete_suppressed"]["cloud_services"] == 1
    assert [call[0] for call in client.full_calls] == ["cloud_accounts"]


def test_cloud_object_name_is_readable_stable_unique_and_bounded():
    first = cloud_object_name("network", "resource-1", account_id="account-1")
    same = cloud_object_name("network", "resource-1", account_id="account-1")
    other = cloud_object_name("network", "resource-1", account_id="account-2")
    long_name = cloud_object_name("service", "x" * 500, account_id="account-1")

    assert first == same
    assert first != other
    assert first.startswith("resource-1 [network:")
    assert len(long_name) <= 255
