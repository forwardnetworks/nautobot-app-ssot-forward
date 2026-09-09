"""Forward API access, delegating transport to the official ``forward-sdk``.

This replaces the hand-rolled httpx client. Retry, backoff, rate limiting,
pagination guards, the async NQE poll loop and the query library workflow are
all owned by the SDK now. What stays here is the plugin's own vocabulary: its
``ForwardConnectionSettings`` and ``ForwardQuerySpec`` shapes, the response
reshaping its adapters expect, and the telemetry its SSoT job result persists.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from forward_sdk import ForwardClient as SdkForwardClient
from forward_sdk import QueryRef
from forward_sdk._sync.services.nqe import NqeExecution

from .exceptions import ForwardClientError, ForwardConfigurationError
from .models import LATEST_PROCESSED_SNAPSHOT, ForwardConnectionSettings, ForwardQuerySpec


def _sdk_snapshot(snapshot_id: str | None) -> str | None:
    """Map the plugin's ``latestProcessed`` sentinel onto the SDK's ``None``."""
    value = str(snapshot_id or "").strip()
    if not value or value == LATEST_PROCESSED_SNAPSHOT:
        return None
    return value


def _query_ref(spec: ForwardQuerySpec) -> QueryRef:
    """Translate a plugin query spec into the SDK's reference type."""
    query_id = spec.resolved_query_id or spec.query_id
    commit_id = spec.resolved_commit_id or spec.commit_id
    if query_id:
        ref = QueryRef.by_id(query_id, commit_id=commit_id)
    elif spec.query_path:
        ref = QueryRef.by_path(spec.query_path, commit_id=commit_id)
    elif spec.query_text:
        ref = QueryRef.inline(spec.query_text)
    else:
        raise ForwardConfigurationError("Query spec carries no query text, ID, or path.")
    if spec.parameters:
        ref = replace(ref, parameters=dict(spec.parameters))
    if spec.sort_keys:
        ref = ref.with_sort(*spec.sort_keys)
    return ref


def _reshape_snapshot(snapshot: Any) -> dict[str, Any]:
    """Adapters expect snake_case snapshot rows with a display label."""
    get = (lambda k: getattr(snapshot, k, None)) if not isinstance(snapshot, dict) else snapshot.get
    identifier = str(get("id") or "")
    state = str(get("state") or "")
    created_at = str(get("created_at") or get("createdAt") or "").strip()
    processed_at = str(get("processed_at") or get("processedAt") or "").strip()
    label_parts = [identifier]
    if state:
        label_parts.append(state)
    if processed_at:
        label_parts.append(processed_at)
    elif created_at:
        label_parts.append(created_at)
    return {
        "id": identifier,
        "state": state,
        "created_at": created_at,
        "processed_at": processed_at,
        "label": " | ".join(label_parts),
    }


class _Counters:
    """SDK counters, plus the aliases this plugin's job result already records.

    ``jobs.py`` reads ``nqe_query_calls`` when it annotates a failure, so that
    name has to keep resolving; the SDK's nearest equivalent is the number of
    executions started.
    """

    def __init__(self, snapshot: Any) -> None:
        self._snapshot = snapshot

    def __getattr__(self, name: str) -> Any:
        return getattr(self._snapshot, name)

    def as_dict(self) -> dict[str, Any]:
        counters = dict(self._snapshot.as_dict())
        counters.setdefault("nqe_query_calls", counters.get("nqe_executions", 0))
        return counters


@dataclass(slots=True)
class ForwardClient:
    """Plugin-facing Forward client. Transport is the SDK's."""

    settings: ForwardConnectionSettings
    transport: httpx.BaseTransport | None = None
    _sdk: Any = field(default=None, init=False, repr=False)
    # A sync pins one snapshot and snapshots are immutable, so these are cached
    # for the client's lifetime. The SDK caches the query index but not these,
    # and the planner resolves a snapshot once per slice across a thread pool.
    _snapshot_cache: dict[Any, Any] = field(default_factory=dict, init=False, repr=False)
    _cache_lock: Any = field(default_factory=threading.Lock, init=False, repr=False)

    # -- lifecycle ---------------------------------------------------------
    @property
    def sdk(self) -> SdkForwardClient:
        if self._sdk is None:
            self._sdk = SdkForwardClient(
                self.settings.base_url,
                username=self.settings.username or None,
                password=self.settings.password or None,
                verify=bool(self.settings.verify_tls),
                timeout=float(self.settings.timeout_seconds),
                retries=int(self.settings.retries),
                rate_limit_rpm=self._rate_limit(),
                network_id=self.settings.network_id or None,
                snapshot_id=_sdk_snapshot(self.settings.snapshot_id),
                transport=self.transport,
            )
        return self._sdk

    def _rate_limit(self) -> Any:
        interval = float(self.settings.request_min_interval_seconds or 0.0)
        return int(60.0 / interval) if interval > 0 else "auto"

    def _cached(self, key: Any, produce: Any) -> Any:
        with self._cache_lock:
            if key in self._snapshot_cache:
                return self._snapshot_cache[key]
        value = produce()
        with self._cache_lock:
            return self._snapshot_cache.setdefault(key, value)

    def close(self) -> None:
        if self._sdk is not None:
            self._sdk.close()
            self._sdk = None

    def __enter__(self) -> ForwardClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- telemetry ---------------------------------------------------------
    @property
    def counters(self) -> Any:
        return _Counters(self.sdk.counters)

    def nqe_execution_telemetry(self) -> list[dict[str, Any]]:
        return [report.as_dict() for report in self.sdk.nqe.execution_reports()]

    # -- networks ----------------------------------------------------------
    def get_networks(self) -> list[dict[str, Any]]:
        with _translated():
            rows = self.sdk.networks.list()
        networks: list[dict[str, Any]] = []
        for row in rows:
            identifier = str(getattr(row, "id", "") or "")
            name = str(getattr(row, "name", "") or "")
            if identifier and name:
                networks.append({"id": identifier, "name": name, "label": f"{name} ({identifier})"})
        return networks

    # -- snapshots ---------------------------------------------------------
    def get_snapshots(
        self, network_id: str, *, include_archived: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            with _translated():
                rows = self.sdk.snapshots.list(network_id, include_archived=include_archived)
            return [_reshape_snapshot(row) for row in rows]

        snapshots = self._cached(("snapshots", network_id, bool(include_archived)), fetch)
        return [dict(row) for row in snapshots][: max(1, int(limit))]

    def resolve_snapshot_id(self, network_id: str, snapshot_id: str | None) -> str:
        concrete = _sdk_snapshot(snapshot_id)
        if concrete:
            return concrete

        def fetch() -> str:
            with _translated():
                return str(self.sdk.snapshots.latest_processed_id(network_id) or "")

        resolved = self._cached(("latest_processed", network_id), fetch)
        if not resolved:
            raise ForwardClientError(
                f"Forward network {network_id} has no latest processed snapshot."
            )
        return str(resolved)

    def get_snapshot_metrics(self, snapshot_id: str) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            with _translated():
                return dict(self.sdk.snapshots.metrics(snapshot_id))

        return dict(self._cached(("metrics", snapshot_id), fetch))

    def get_latest_processed_snapshot_id(self, network_id: str) -> str:
        return str(self.get_latest_processed_snapshot(network_id).get("id") or "")

    def get_latest_processed_snapshot(self, network_id: str) -> dict[str, Any]:
        with _translated():
            snapshot = self.sdk.snapshots.latest_processed(network_id)
        if snapshot is None:
            raise ForwardClientError(
                f"Forward network {network_id} has no latest processed snapshot."
            )
        return _reshape_snapshot(snapshot)

    # -- query library -----------------------------------------------------
    def get_nqe_repository_query_index(
        self, *, repository: str = "org", commit_id: str = "head"
    ) -> dict[str, Any]:
        with _translated():
            index = self.sdk.nqe.repo.index(repository=repository)
        return {
            "by_path": {
                path: {
                    "path": entry.path,
                    "queryId": entry.query_id,
                    "lastCommitId": entry.commit_id,
                    "sourceCode": entry.source,
                }
                for path, entry in index.items()
            }
        }

    def get_committed_nqe_query(
        self,
        *,
        repository: str = "org",
        query_path: str,
        commit_id: str = "head",
        require_source_code: bool = False,
    ) -> dict[str, Any]:
        with _translated():
            found = self.sdk.nqe.repo.queries(
                repository=repository,
                commit_id=commit_id or "head",
                path=query_path,
                with_source=require_source_code,
            )
        if not found:
            raise ForwardClientError(f"Forward NQE query `{query_path}` was not found.")
        entry = found[0]
        return {
            "path": entry.path,
            "queryId": entry.query_id,
            # Forward sends the commit nested when asked for a specific one and flat
            # when listing at head; both are real, so emit both for callers.
            "lastCommit": {"id": entry.commit_id} if entry.commit_id else {},
            "lastCommitId": entry.commit_id,
            "sourceCode": entry.source,
        }

    def get_nqe_query_history(self, query_id: str) -> list[dict[str, Any]]:
        with _translated():
            return [dict(commit) for commit in self.sdk.nqe.repo.history(query_id)]

    def get_org_nqe_head_commit_id(self) -> str:
        with _translated():
            return str(self.sdk.nqe.repo.head_commit_id() or "")

    def get_org_nqe_draft_changes(self) -> list[dict[str, Any]]:
        with _translated():
            return [{"type": d.action, "path": d.path} for d in self.sdk.nqe.repo.drafts()]

    def add_org_nqe_query(self, *, query_path: str, source_code: str) -> None:
        with _translated():
            self.sdk.nqe.repo.stage_add(query_path, source_code)

    def add_org_nqe_directory(self, *, directory_path: str) -> None:
        with _translated():
            self.sdk.nqe.repo.stage_directory(directory_path)

    def edit_org_nqe_query(
        self, *, query_path: str, source_code: str, query_id: str, commit_id: str
    ) -> None:
        if not query_id or not commit_id:
            raise ForwardConfigurationError(
                "Editing a saved Forward NQE query requires both a query ID and a commit ID."
            )
        with _translated():
            self.sdk.nqe.repo.stage_edit(
                query_path, source_code, query_id=query_id, commit_id=commit_id
            )

    def commit_org_nqe_queries(self, *, query_paths: list[str], message: str) -> str:
        title, _, body = str(message or "").partition("\n")
        with _translated():
            report = self.sdk.nqe.repo.commit(list(query_paths), title=title, body=body.strip())
        return str(getattr(report, "commit_id", "") or "")

    def dry_run_org_nqe_queries(
        self, *, query_paths: list[str], snapshot_id: str | None = None
    ) -> dict[str, Any]:
        with _translated():
            return dict(
                self.sdk.nqe.repo.dry_run(list(query_paths), snapshot_id=_sdk_snapshot(snapshot_id))
            )

    def discard_org_nqe_draft_change(self, *, path: str) -> None:
        with _translated():
            self.sdk.nqe.repo.discard(path)

    # -- NQE execution -----------------------------------------------------
    def resolve_query_spec(self, query_spec: ForwardQuerySpec) -> ForwardQuerySpec:
        if query_spec.resolved_query_id or not query_spec.query_path:
            return query_spec
        with _translated():
            ref = self.sdk.nqe.resolve(_query_ref(query_spec))
        resolved_id = getattr(ref, "resolved_query_id", None) or ref.query_id
        resolved_commit = getattr(ref, "resolved_commit_id", None) or ref.commit_id
        return query_spec.with_query_id(str(resolved_id or ""), resolved_commit)

    def run_nqe_query(
        self,
        *,
        query_spec: ForwardQuerySpec,
        network_id: str | None = None,
        snapshot_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        ref = _query_ref(query_spec)
        resolved_network = network_id or self.settings.network_id or None
        resolved_snapshot = _sdk_snapshot(snapshot_id or self.settings.snapshot_id)
        page_size = int(limit or self.settings.nqe_page_size)
        with _translated():
            if fetch_all:
                # Every row, streamed. This is what all production callers ask for.
                rows = self.sdk.nqe.query(
                    ref,
                    network_id=resolved_network,
                    snapshot_id=resolved_snapshot,
                    page_size=page_size,
                    stream=True,
                )
            else:
                # One bounded page, preserving the previous client's semantics
                # where `limit` capped the rows returned rather than the page size.
                execution = self.sdk.nqe.execute(
                    ref, network_id=resolved_network, snapshot_id=resolved_snapshot
                )
                execution.wait()
                rows = execution.result_page(offset=int(offset or 0), limit=page_size).items
        return [dict(row) for row in rows]

    # The plugin's async entrypoint; the SDK has no separate synchronous path.
    run_nqe_query_async = run_nqe_query

    def _execution(self, *, execution_key: str, network_id: str | None = None) -> NqeExecution:
        return NqeExecution(
            self.sdk.nqe,
            key=execution_key,
            network_id=str(network_id or self.settings.network_id or ""),
        )

    def request_nqe_execution(
        self,
        *,
        query_spec: ForwardQuerySpec,
        network_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        with _translated():
            execution = self.sdk.nqe.execute(
                _query_ref(query_spec),
                network_id=network_id or self.settings.network_id or None,
                snapshot_id=_sdk_snapshot(snapshot_id or self.settings.snapshot_id),
            )
        # ``last_status`` is the status string, not the response body, so the
        # submit result is rebuilt from the handle's own properties.
        status: dict[str, Any] = {
            "executionKey": execution.key,
            "status": str(execution.last_status or ""),
        }
        for key, value in (
            ("rowsProduced", execution.rows_produced),
            ("millisExecuting", execution.millis_executing),
            ("timeoutMinutes", execution.timeout_minutes),
        ):
            if value is not None:
                status[key] = value
        return status

    def get_nqe_execution_status(self, *, network_id: str, execution_key: str) -> dict[str, Any]:
        with _translated():
            return dict(
                self._execution(execution_key=execution_key, network_id=network_id).status()
            )

    def get_nqe_execution_result(
        self,
        *,
        execution_key: str,
        network_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        execution = self._execution(execution_key=execution_key, network_id=network_id)
        with _translated():
            if fetch_all:
                return [dict(row) for row in execution.rows()]
            page = execution.result_page(
                offset=offset, limit=int(limit or self.settings.nqe_page_size)
            )
        return [dict(row) for row in page.items]

    def run_nqe_diff(
        self,
        *,
        query_id: str,
        before_snapshot_id: str,
        after_snapshot_id: str,
        commit_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        # The SDK's diff always starts at offset 0 and pages internally; no
        # production caller passes a non-zero offset.
        if offset:
            raise ForwardConfigurationError(
                "Forward NQE diffs are paged by the SDK; a non-zero offset is not supported."
            )
        del fetch_all
        with _translated():
            entries = self.sdk.nqe.diff(
                QueryRef.by_id(query_id, commit_id=commit_id),
                before=before_snapshot_id,
                after=after_snapshot_id,
                page_size=int(limit or self.settings.nqe_page_size),
            )
        # Contract rows stay raw dicts; only the diff envelope is unwrapped.
        return [
            {"type": str(entry.type or ""), "before": entry.before, "after": entry.after}
            for entry in entries
        ]


class _translated:
    """Map SDK failures onto the plugin's error type, preserving control flow.

    Deliberately wider than ``ForwardError``. Four callers treat
    ``ForwardClientError`` as a signal to degrade — three fall back to inline
    NQE source when a bundled query is unpublished, and the planner disables
    destructive reconciliation when snapshot metrics are unavailable. Anything
    that escapes untranslated defeats those recoveries at exactly the moment
    something is already wrong.

    That is not hypothetical: before forward-sdk 0.1.5, a response the SDK
    could not parse raised pydantic's ``ValidationError``, which is not a
    ``ForwardError``. 0.1.5 raises ``ForwardResponseError`` instead, but
    catching only the SDK's base class would let the next such gap through on
    a version bump, so the net is cast wider here on purpose.

    ``KeyboardInterrupt``, ``SystemExit`` and ``GeneratorExit`` derive from
    ``BaseException`` rather than ``Exception`` and so are never caught.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, _tb) -> bool:
        if exc is None or not isinstance(exc, Exception):
            return False
        if isinstance(exc, (ForwardClientError, ForwardConfigurationError)):
            return False
        # str(exc) carries Forward's raw response body, which is what the
        # publishing code's reason matching reads. `reason` is the structured
        # form and should replace that matching once callers are updated.
        translated = ForwardClientError(str(exc))
        translated.reason = getattr(exc, "reason", None)
        raise translated from exc
