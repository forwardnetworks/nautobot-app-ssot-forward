"""Cloud inventory planning for native Nautobot cloud models."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from .client import ForwardClient
from .exceptions import ForwardClientError
from .models import ForwardQuerySpec, ForwardSyncReport
from .queries import read_bundled_query_execution_source
from .registry import DEFAULT_QUERY_DIRECTORY

CLOUD_QUERY_FILES: dict[str, str] = {
    "cloud_accounts": "forward_cloud_accounts.nqe",
    "cloud_networks": "forward_cloud_networks.nqe",
    "cloud_services": "forward_cloud_services.nqe",
}
CLOUD_QUERY_CONTRACT_VERSION = "v2"


def cloud_type_token(value: Any) -> str:
    """Normalize a rendered enum without constraining the set of cloud types."""

    return str(value or "").strip().rsplit(".", 1)[-1].casefold()


def cloud_account_key(row: dict[str, Any]) -> tuple[str, str]:
    """Return the provider-qualified source account identity for a cloud row."""

    return (
        cloud_type_token(row.get("cloud_type")),
        str(row.get("account_id") or "").strip(),
    )


@dataclass(frozen=True, slots=True)
class ForwardCloudScope:
    """Selected current-snapshot account closure for all cloud child slices."""

    account_keys: frozenset[tuple[str, str]] = frozenset()

    @property
    def account_ids(self) -> frozenset[str]:
        return frozenset(account_id for _cloud_type, account_id in self.account_keys)

    @classmethod
    def from_account_rows(
        cls,
        rows: list[dict[str, Any]],
        *,
        cloud_types: tuple[str, ...] = (),
        cloud_account_ids: tuple[str, ...] = (),
    ) -> ForwardCloudScope:
        allowed_types = {cloud_type_token(value) for value in cloud_types if str(value).strip()}
        allowed_ids = {str(value).strip() for value in cloud_account_ids if str(value).strip()}
        selected: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            account_id = str(row.get("account_id") or "").strip()
            if not account_id:
                continue
            if allowed_ids and account_id not in allowed_ids:
                continue
            if allowed_types and cloud_type_token(row.get("cloud_type")) not in allowed_types:
                continue
            selected.add(cloud_account_key(row))
        return cls(account_keys=frozenset(selected))

    def includes_row(self, row: dict[str, Any]) -> bool:
        return cloud_account_key(row) in self.account_keys


@dataclass(slots=True)
class ForwardCloudIngestionPlan:
    """Current scoped cloud rows plus query/diff evidence for a contrib sync."""

    account_rows: tuple[dict[str, Any], ...] = ()
    network_rows: tuple[dict[str, Any], ...] = ()
    service_rows: tuple[dict[str, Any], ...] = ()
    reports: tuple[ForwardSyncReport, ...] = ()
    detail: dict[str, Any] | None = None
    should_sync: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_count": len(self.account_rows),
            "network_count": len(self.network_rows),
            "service_count": len(self.service_rows),
            "should_sync": self.should_sync,
            **dict(self.detail or {}),
        }


@dataclass(slots=True)
class _ResolvedCloudQuery:
    slug: str
    query_file: str
    spec: ForwardQuerySpec
    inline: bool

    @property
    def query_id(self) -> str:
        return str(self.spec.resolved_query_id or self.spec.query_id or "")

    @property
    def commit_id(self) -> str:
        return str(self.spec.resolved_commit_id or self.spec.commit_id or "")


class ForwardCloudIngestionPlanner:
    """Plan cloud ingestion using NQE diffs as the saved-query change detector.

    Native cloud DiffSync needs a complete current source set to avoid treating
    unchanged target objects as missing. Saved-query diffs therefore decide whether
    a cloud sync is needed; when a relevant create/update exists, the planner hydrates
    the complete current cloud source through async NQE before contrib CRUD runs.
    Inline fallback is already a full async result and cannot use NQE diffs.
    """

    def __init__(self, client: ForwardClient):
        self.client = client

    def _resolve(self, slug: str, query_file: str) -> _ResolvedCloudQuery:
        query_path = f"{DEFAULT_QUERY_DIRECTORY}/{query_file.removesuffix('.nqe')}"
        try:
            spec = self.client.resolve_query_spec(ForwardQuerySpec(query_path=query_path))
        except ForwardClientError:
            spec = ForwardQuerySpec(query_text=read_bundled_query_execution_source(query_file))
            return _ResolvedCloudQuery(slug=slug, query_file=query_file, spec=spec, inline=True)
        return _ResolvedCloudQuery(slug=slug, query_file=query_file, spec=spec, inline=False)

    def _run_full(
        self,
        query: _ResolvedCloudQuery,
        *,
        network_id: str,
        snapshot_id: str,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        return self.client.run_nqe_query(
            query_spec=query.spec,
            network_id=network_id,
            snapshot_id=snapshot_id,
            limit=limit,
            fetch_all=True,
        )

    def _run_diff(
        self,
        query: _ResolvedCloudQuery,
        *,
        before_snapshot_id: str,
        after_snapshot_id: str,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        return self.client.run_nqe_diff(
            query_id=query.query_id,
            commit_id=query.commit_id or None,
            before_snapshot_id=before_snapshot_id,
            after_snapshot_id=after_snapshot_id,
            limit=limit,
            fetch_all=True,
        )

    @staticmethod
    def _current_rows_for_scope(
        rows: list[dict[str, Any]], scope: ForwardCloudScope
    ) -> list[dict[str, Any]]:
        return [dict(row) for row in rows if isinstance(row, dict) and scope.includes_row(row)]

    @staticmethod
    def _relevant_diff_rows(
        rows: list[dict[str, Any]],
        scope: ForwardCloudScope,
        *,
        include_all_deletes: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        relevant: list[dict[str, Any]] = []
        suppressed_deletes = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            after = row.get("after") if isinstance(row.get("after"), dict) else None
            before = row.get("before") if isinstance(row.get("before"), dict) else None
            if after is not None and scope.includes_row(after):
                relevant.append(dict(row))
            elif before is not None and (include_all_deletes or scope.includes_row(before)):
                suppressed_deletes += 1
        return relevant, suppressed_deletes

    def _parallel_full(
        self,
        queries: list[_ResolvedCloudQuery],
        *,
        network_id: str,
        snapshot_id: str,
        limit: int | None,
    ) -> dict[str, list[dict[str, Any]]]:
        if not queries:
            return {}
        results: dict[str, list[dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=min(2, len(queries))) as pool:
            futures = {
                pool.submit(
                    self._run_full,
                    query,
                    network_id=network_id,
                    snapshot_id=snapshot_id,
                    limit=limit,
                ): query
                for query in queries
            }
            for future in as_completed(futures):
                query = futures[future]
                results[query.slug] = future.result()
        return results

    def run(
        self,
        *,
        source_url: str,
        network_id: str,
        current_snapshot_id: str,
        baseline_snapshot_id: str = "",
        cloud_types: tuple[str, ...] = (),
        cloud_account_ids: tuple[str, ...] = (),
        limit: int | None = None,
        snapshot_metrics: dict[str, Any] | None = None,
    ) -> ForwardCloudIngestionPlan:
        self.client.get_nqe_repository_query_index(repository="org", commit_id="head")
        queries = {
            slug: self._resolve(slug, query_file) for slug, query_file in CLOUD_QUERY_FILES.items()
        }

        account_query = queries["cloud_accounts"]
        account_full = self._run_full(
            account_query,
            network_id=network_id,
            snapshot_id=current_snapshot_id,
            limit=limit,
        )
        scope = ForwardCloudScope.from_account_rows(
            account_full,
            cloud_types=cloud_types,
            cloud_account_ids=cloud_account_ids,
        )
        scoped_accounts = self._current_rows_for_scope(account_full, scope)
        filtered = bool(cloud_types or cloud_account_ids)
        detection_rows: dict[str, list[dict[str, Any]]] = {}
        query_modes: dict[str, str] = {}
        delete_suppressed: dict[str, int] = {}
        cached_full: dict[str, list[dict[str, Any]]] = {"cloud_accounts": account_full}

        if baseline_snapshot_id:
            for slug, query in queries.items():
                if query.inline:
                    rows = (
                        account_full
                        if slug == "cloud_accounts"
                        else self._run_full(
                            query,
                            network_id=network_id,
                            snapshot_id=current_snapshot_id,
                            limit=limit,
                        )
                    )
                    cached_full[slug] = rows
                    detection_rows[slug] = self._current_rows_for_scope(rows, scope)
                    query_modes[slug] = "bundled_nqe_inline_async"
                    delete_suppressed[slug] = 0
                    continue
                diff_rows = self._run_diff(
                    query,
                    before_snapshot_id=baseline_snapshot_id,
                    after_snapshot_id=current_snapshot_id,
                    limit=limit,
                )
                relevant, suppressed = self._relevant_diff_rows(
                    diff_rows,
                    scope,
                    include_all_deletes=not filtered,
                )
                detection_rows[slug] = relevant
                query_modes[slug] = "bundled_nqe_query_id_diff"
                delete_suppressed[slug] = suppressed
        else:
            cached_full.update(
                self._parallel_full(
                    [queries["cloud_networks"], queries["cloud_services"]],
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    limit=limit,
                )
            )
            for slug, query in queries.items():
                rows = cached_full.get(slug, [])
                detection_rows[slug] = self._current_rows_for_scope(rows, scope)
                query_modes[slug] = (
                    "bundled_nqe_inline_async" if query.inline else "bundled_nqe_query_id_async"
                )
                delete_suppressed[slug] = 0

        should_sync = bool(scope.account_keys) and (
            not baseline_snapshot_id
            or any(query.inline for query in queries.values())
            or any(detection_rows.values())
        )
        if should_sync:
            missing_full = [
                queries[slug]
                for slug in ("cloud_networks", "cloud_services")
                if slug not in cached_full
            ]
            cached_full.update(
                self._parallel_full(
                    missing_full,
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    limit=limit,
                )
            )

        scoped_networks = self._current_rows_for_scope(cached_full.get("cloud_networks", []), scope)
        scoped_services = self._current_rows_for_scope(cached_full.get("cloud_services", []), scope)
        reports: list[ForwardSyncReport] = []
        for slug, query in queries.items():
            mode = query_modes[slug]
            notes = [
                "Cloud account scope is applied after unparameterized NQE execution.",
                "Cloud deletions are suppressed until managed-object ownership is explicit.",
            ]
            if query.inline:
                notes.append(
                    "NQE diffs are disabled for this slice until the bundled query is published."
                )
            elif mode.endswith("_diff") and should_sync:
                notes.append(
                    "A relevant NQE delta triggered async hydration of the complete cloud source."
                )
            reports.append(
                ForwardSyncReport(
                    mode="preview",
                    source_url=source_url.rstrip("/"),
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    baseline_snapshot_id=baseline_snapshot_id,
                    query_mode=mode,
                    query_reference=query.query_file,
                    query_contract_version=CLOUD_QUERY_CONTRACT_VERSION,
                    row_count=len(detection_rows[slug]),
                    rows=tuple(detection_rows[slug]),
                    snapshot_metrics=dict(snapshot_metrics or {}),
                    planned_models=(slug,),
                    notes=tuple(notes),
                )
            )

        return ForwardCloudIngestionPlan(
            account_rows=tuple(scoped_accounts if should_sync else ()),
            network_rows=tuple(scoped_networks if should_sync else ()),
            service_rows=tuple(scoped_services if should_sync else ()),
            reports=tuple(reports),
            should_sync=should_sync,
            detail={
                "mode": "delta" if baseline_snapshot_id else "snapshot",
                "filtered_scope": filtered,
                "selected_account_count": len(scope.account_keys),
                "available_account_count": len(account_full),
                "scope_filtered_account_count": len(account_full) - len(scoped_accounts),
                "delete_suppressed": delete_suppressed,
                "query_modes": query_modes,
                "scope_empty": not bool(scope.account_keys),
            },
        )
