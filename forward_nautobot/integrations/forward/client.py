"""Forward API client for Nautobot sync jobs."""

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from .exceptions import ForwardClientError, ForwardConfigurationError
from .models import LATEST_PROCESSED_SNAPSHOT, ForwardConnectionSettings, ForwardQuerySpec

TRANSIENT_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
# Exponential backoff bounds for retrying transient failures (separate from the
# per-request min-interval throttle). Honors Retry-After when the server sends it.
_RETRY_BACKOFF_BASE_SECONDS = 0.5
_RETRY_BACKOFF_CAP_SECONDS = 8.0
NQE_ASYNC_RESULT_ACCEPT = "application/x-ndjson, application/jsonl;q=0.9, application/json;q=0.1"


@dataclass(slots=True)
class ForwardClient:
    """Small, testable wrapper around the Forward REST API."""

    settings: ForwardConnectionSettings
    transport: httpx.BaseTransport | None = None
    _resolved_query_cache: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _resolved_query_index_cache: dict[tuple[str, str], dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _resolved_snapshot_cache: dict[tuple[str, str], str] = field(
        default_factory=dict, init=False, repr=False
    )
    _latest_processed_snapshot_cache: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _snapshot_metrics_cache: dict[str, dict[str, Any]] = field(
        default_factory=dict, init=False, repr=False
    )
    _snapshots_cache: dict[tuple[str, bool, int], list[dict[str, Any]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _last_request_completed_at: float | None = field(default=None, init=False, repr=False)
    _http_client: httpx.Client | None = field(default=None, init=False, repr=False)

    def _get_http_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(
                timeout=self.timeout,
                verify=self.verify,
                transport=self.transport,
                trust_env=True,
            )
        return self._http_client

    def close(self) -> None:
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @property
    def base_url(self) -> str:
        return self.settings.base_url.rstrip("/")

    @property
    def timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.settings.timeout_seconds)

    @property
    def verify(self) -> bool:
        return bool(self.settings.verify_tls)

    @property
    def auth(self):
        if self.settings.has_basic_auth:
            return (self.settings.username, self.settings.password)
        return None

    def _api_url(self, path: str) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        if self.base_url.endswith("/api"):
            return f"{self.base_url}{normalized_path}"
        return f"{self.base_url}/api{normalized_path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "nautobot-app-ssot-forward/0.1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                self._respect_min_interval()
                response = self._get_http_client().request(
                    method,
                    self._api_url(path),
                    params=params,
                    json=json_body,
                    headers={**self._headers(), **(headers or {})},
                    auth=self.auth,
                )
                if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                self._last_request_completed_at = time.monotonic()
                return response
            except httpx.HTTPStatusError as exc:
                self._last_request_completed_at = time.monotonic()
                status_code = exc.response.status_code
                if (
                    status_code not in TRANSIENT_HTTP_STATUS_CODES
                    or attempt >= self.settings.retries
                ):
                    raise ForwardClientError(
                        f"Forward API request failed with HTTP {status_code}: {exc.response.text}"
                    ) from exc
                last_error = exc
                self._sleep_before_retry(attempt, exc.response.headers.get("Retry-After"))
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                self._last_request_completed_at = time.monotonic()
                if attempt >= self.settings.retries:
                    raise ForwardClientError(f"Forward API request failed: {exc}") from exc
                last_error = exc
                self._sleep_before_retry(attempt, None)

        raise ForwardClientError("Forward API request failed.") from last_error

    @staticmethod
    def _retry_after_seconds(retry_after: str | None) -> float | None:
        """Parse a Retry-After header value (delta-seconds or HTTP-date)."""
        if not retry_after:
            return None
        value = str(retry_after).strip()
        try:
            return max(0.0, float(int(value)))
        except (TypeError, ValueError):
            pass
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        delta = when.timestamp() - time.time()
        return max(0.0, delta)

    def _sleep_before_retry(self, attempt: int, retry_after: str | None) -> None:
        """Back off between retries: honor Retry-After, else exponential + jitter.

        Decorrelated jitter matters because the planner fans requests across a
        thread pool sharing this client; without it N workers would retry in
        lockstep and re-stampede a throttled Forward API.
        """
        wait = self._retry_after_seconds(retry_after)
        if wait is None:
            backoff = min(_RETRY_BACKOFF_BASE_SECONDS * (2**attempt), _RETRY_BACKOFF_CAP_SECONDS)
            wait = backoff + random.uniform(0.0, _RETRY_BACKOFF_BASE_SECONDS)
        if wait > 0:
            time.sleep(wait)

    def _respect_min_interval(self) -> None:
        minimum_interval = float(self.settings.request_min_interval_seconds or 0.0)
        if minimum_interval <= 0:
            return
        last_completed_at = self._last_request_completed_at
        if last_completed_at is None:
            return
        elapsed = time.monotonic() - last_completed_at
        remaining = minimum_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def get_networks(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/networks").json()
        rows = data.get("networks") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        networks: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            network_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not network_id or not name:
                continue
            networks.append(
                {
                    "id": network_id,
                    "name": name,
                    "label": f"{name} ({network_id})",
                }
            )
        return networks

    def get_snapshots(
        self,
        network_id: str,
        *,
        include_archived: bool = False,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        network_id = str(network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        cache_key = (network_id, bool(include_archived), int(limit))
        cached_snapshots = self._snapshots_cache.get(cache_key)
        if cached_snapshots is not None:
            return [dict(snapshot) for snapshot in cached_snapshots]
        response = self._request(
            "GET",
            f"/networks/{quote(network_id, safe='')}/snapshots",
            params={
                "includeArchived": str(bool(include_archived)).lower(),
                "limit": limit,
            },
        )
        data = response.json() or {}
        rows = data.get("snapshots") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        snapshots: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            snapshot_id = str(row.get("id") or "").strip()
            if not snapshot_id:
                continue
            state = str(row.get("state") or "").strip()
            created_at = str(row.get("createdAt") or "").strip()
            processed_at = str(row.get("processedAt") or "").strip()
            label_parts = [snapshot_id]
            if state:
                label_parts.append(state)
            if processed_at:
                label_parts.append(processed_at)
            elif created_at:
                label_parts.append(created_at)
            snapshots.append(
                {
                    "id": snapshot_id,
                    "state": state,
                    "created_at": created_at,
                    "processed_at": processed_at,
                    "label": " | ".join(label_parts),
                }
            )
        self._snapshots_cache[cache_key] = [dict(snapshot) for snapshot in snapshots]
        return snapshots

    def get_latest_processed_snapshot(self, network_id: str) -> dict[str, Any]:
        network_id = str(network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        cached_snapshot = self._latest_processed_snapshot_cache.get(network_id)
        if cached_snapshot is not None:
            return dict(cached_snapshot)
        response = self._request(
            "GET",
            f"/networks/{quote(network_id, safe='')}/snapshots/latestProcessed",
        )
        snapshot = response.json() or {}
        if isinstance(snapshot, dict):
            self._latest_processed_snapshot_cache[network_id] = dict(snapshot)
            return snapshot
        return {}

    def get_latest_processed_snapshot_id(self, network_id: str) -> str:
        snapshot = self.get_latest_processed_snapshot(network_id)
        snapshot_id = str(snapshot.get("id") or "").strip()
        if not snapshot_id:
            raise ForwardClientError(
                "Forward latestProcessed snapshot response did not include an ID."
            )
        return snapshot_id

    def resolve_snapshot_id(self, network_id: str, snapshot_id: str) -> str:
        snapshot_id = str(snapshot_id or "").strip()
        cache_key = (network_id, snapshot_id or LATEST_PROCESSED_SNAPSHOT)
        cached_snapshot_id = self._resolved_snapshot_cache.get(cache_key)
        if cached_snapshot_id is not None:
            return cached_snapshot_id
        if not snapshot_id or snapshot_id == LATEST_PROCESSED_SNAPSHOT:
            resolved_snapshot_id = self.get_latest_processed_snapshot_id(network_id)
            self._resolved_snapshot_cache[cache_key] = resolved_snapshot_id
            return resolved_snapshot_id
        self._resolved_snapshot_cache[cache_key] = snapshot_id
        return snapshot_id

    def get_snapshot_metrics(self, snapshot_id: str) -> dict[str, Any]:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return {}
        cached_metrics = self._snapshot_metrics_cache.get(snapshot_id)
        if cached_metrics is not None:
            return dict(cached_metrics)
        response = self._request(
            "GET",
            f"/snapshots/{quote(snapshot_id, safe='')}/metrics",
        )
        metrics = response.json() or {}
        if isinstance(metrics, dict):
            self._snapshot_metrics_cache[snapshot_id] = dict(metrics)
            return metrics
        return {}

    def get_committed_nqe_query(
        self,
        *,
        repository: str = "org",
        query_path: str,
        commit_id: str = "head",
    ) -> dict[str, Any]:
        repository = str(repository or "org").strip() or "org"
        query_path = self._normalize_query_path(query_path)
        commit_id = str(commit_id or "head").strip() or "head"
        if not query_path:
            raise ForwardConfigurationError("Forward NQE query path is required.")
        cache_key = (repository, query_path, commit_id)
        cached_query = self._resolved_query_cache.get(cache_key)
        if cached_query is not None:
            return dict(cached_query)
        query_index = self.get_nqe_repository_query_index(
            repository=repository, commit_id=commit_id
        )
        indexed_query = query_index.get("by_path", {}).get(query_path)
        if isinstance(indexed_query, dict) and indexed_query.get("queryId"):
            query = dict(indexed_query)
            if commit_id == "head":
                query.setdefault("lastCommitId", "")
            self._resolved_query_cache[cache_key] = dict(query)
            return query
        response = self._request(
            "GET",
            f"/nqe/repos/{quote(repository, safe='')}/commits/{quote(commit_id, safe='')}/queries",
            params={"path": query_path},
        )
        data = response.json() or {}
        if isinstance(data, dict) and isinstance(data.get("queries"), list):
            for row in data["queries"]:
                if isinstance(row, dict) and str(row.get("path") or "").strip() == query_path:
                    self._resolved_query_cache[cache_key] = dict(row)
                    return row
            raise ForwardClientError(
                f"Forward NQE repository lookup did not include `{query_path}`."
            )
        if isinstance(data, dict):
            self._resolved_query_cache[cache_key] = dict(data)
            return data
        raise ForwardClientError(
            f"Forward NQE repository lookup for `{query_path}` returned an invalid response."
        )

    @staticmethod
    def _normalize_query_path(query_path: str) -> str:
        normalized = str(query_path or "").strip()
        if not normalized:
            return ""
        if not normalized.startswith("/"):
            return f"/{normalized}"
        return normalized

    def get_nqe_repository_query_index(
        self,
        *,
        repository: str = "org",
        commit_id: str = "head",
    ) -> dict[str, Any]:
        repository = str(repository or "org").strip() or "org"
        commit_id = str(commit_id or "head").strip() or "head"
        cache_key = (repository, commit_id)
        cached_index = self._resolved_query_index_cache.get(cache_key)
        if cached_index is not None:
            return dict(cached_index)
        response = self._request(
            "GET",
            f"/nqe/repos/{quote(repository, safe='')}/commits/{quote(commit_id, safe='')}/queries",
        )
        data = response.json() or {}
        if not isinstance(data, dict):
            raise ForwardClientError(
                f"Forward NQE repository query index for `{repository}:{commit_id}` returned an invalid response."
            )
        queries = data.get("queries")
        if not isinstance(queries, list):
            self._resolved_query_index_cache[cache_key] = {"by_path": {}}
            return {"by_path": {}}
        by_path: dict[str, dict[str, Any]] = {}
        for row in queries:
            if not isinstance(row, dict):
                continue
            path = str(row.get("path") or "").strip()
            query_id = str(row.get("queryId") or "").strip()
            if not path or not query_id:
                continue
            normalized = dict(row)
            by_path[path] = normalized
        index = {"by_path": by_path}
        self._resolved_query_index_cache[cache_key] = dict(index)
        return index

    def resolve_query_spec(self, query_spec: ForwardQuerySpec) -> ForwardQuerySpec:
        if query_spec.query_path and query_spec.resolved_query_id:
            return query_spec
        if query_spec.query_path:
            normalized_query_path = self._normalize_query_path(query_spec.query_path)
            query_index = self.get_nqe_repository_query_index(
                repository=query_spec.query_repository or "org",
                commit_id=query_spec.commit_id or "head",
            )
            query = query_index.get("by_path", {}).get(normalized_query_path)
            if not isinstance(query, dict) or not query.get("queryId"):
                query = self.get_committed_nqe_query(
                    repository=query_spec.query_repository or "org",
                    query_path=normalized_query_path,
                    commit_id=query_spec.commit_id or "head",
                )
            query_id = str(query.get("queryId") or "").strip()
            commit_id = str(
                query_spec.commit_id
                or (query.get("lastCommit") or {}).get("id")
                or query.get("lastCommitId")
                or ""
            ).strip()
            if not query_id:
                raise ForwardClientError(
                    f"Forward NQE query `{query_spec.reference}` did not include a query ID."
                )
            resolved_query_spec = query_spec.with_query_id(query_id, commit_id or None)
            if resolved_query_spec.query_path != normalized_query_path:
                return replace(
                    resolved_query_spec,
                    query_path=normalized_query_path,
                )
            return resolved_query_spec
        return query_spec

    @staticmethod
    def _record_from_nqe_item(item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        if isinstance(item.get("fields"), dict):
            return dict(item["fields"])
        return dict(item)

    def _parse_nqe_records(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        if not isinstance(data, dict):
            return [], None
        items = data.get("items") or []
        rows: list[dict[str, Any]] = []
        for item in items:
            row = self._record_from_nqe_item(item)
            if row is not None:
                rows.append(row)
        total = data.get("totalNumItems")
        try:
            total_int = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_int = None
        return rows, total_int

    def _parse_nqe_lines(self, text: str) -> tuple[list[dict[str, Any]], None]:
        rows: list[dict[str, Any]] = []
        for line in str(text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed_line = json.loads(line)
            except json.JSONDecodeError as exc:
                # Surface as the client's own error type so callers' ForwardClientError
                # handling applies, instead of a raw ValueError aborting the run.
                raise ForwardClientError(
                    f"Forward NQE result contained a malformed ndjson line: {exc}"
                ) from exc
            row = self._record_from_nqe_item(parsed_line)
            if row is not None:
                rows.append(row)
        return rows, None

    def _parse_nqe_async_result(
        self,
        response: httpx.Response,
    ) -> tuple[list[dict[str, Any]], int | None]:
        content_type = str(
            (getattr(response, "headers", {}) or {}).get("content-type") or ""
        ).lower()
        if "jsonl" in content_type or "ndjson" in content_type:
            return self._parse_nqe_lines(getattr(response, "text", ""))
        return self._parse_nqe_records(response.json() or {})

    def _parse_nqe_diff_rows(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        rows = data.get("rows") or []
        parsed_rows: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                parsed_rows.append(
                    {
                        "type": row.get("type"),
                        "before": row.get("before"),
                        "after": row.get("after"),
                    }
                )
        total = data.get("totalNumRows")
        try:
            total_int = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_int = None
        return parsed_rows, total_int

    def _paginate_rows(
        self,
        fetch_page: Callable[[int], tuple[list[dict[str, Any]], int | None]],
        *,
        limit: int,
        offset: int,
        fetch_all: bool,
        exhausted_message: str,
    ) -> list[dict[str, Any]]:
        rows, total = fetch_page(offset)
        if not fetch_all:
            return rows

        all_rows = list(rows)
        fetched_pages = 1
        while True:
            if total is not None and len(all_rows) >= total:
                return all_rows
            if total is None and len(rows) < limit:
                return all_rows
            if fetched_pages >= self.settings.nqe_fetch_all_max_pages:
                raise ForwardClientError(exhausted_message)
            next_offset = offset + len(all_rows)
            rows, page_total = fetch_page(next_offset)
            fetched_pages += 1
            if total is None and page_total is not None:
                total = page_total
            if not rows:
                return all_rows
            all_rows.extend(rows)

    def _fetch_ndjson_stream(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """GET url with ndjson Accept preference.

        Streams line-by-line when the server returns ndjson/jsonl (no full-body buffer).
        Falls back to buffered JSON parsing when the server returns application/json.
        """
        self._respect_min_interval()
        rows: list[dict[str, Any]] = []
        merged_headers = {
            **self._headers(),
            "Accept": NQE_ASYNC_RESULT_ACCEPT,
        }
        try:
            with self._get_http_client().stream(
                "GET",
                url,
                params=params,
                headers=merged_headers,
                auth=self.auth,
            ) as response:
                response.raise_for_status()
                self._last_request_completed_at = time.monotonic()
                content_type = str(response.headers.get("content-type", "")).lower()
                if "ndjson" in content_type or "jsonl" in content_type:
                    for line in response.iter_lines():
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            parsed = json.loads(stripped)
                        except json.JSONDecodeError as exc:
                            raise ForwardClientError(
                                f"Forward NQE stream contained a malformed ndjson line: {exc}"
                            ) from exc
                        row = self._record_from_nqe_item(parsed)
                        if row is not None:
                            rows.append(row)
                else:
                    data = json.loads(response.read())
                    rows, _ = self._parse_nqe_records(data or {})
        except httpx.HTTPStatusError as exc:
            self._last_request_completed_at = time.monotonic()
            raise ForwardClientError(
                f"Forward API request failed with HTTP {exc.response.status_code}: "
                f"{exc.response.text}"
            ) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            self._last_request_completed_at = time.monotonic()
            raise ForwardClientError(f"Forward API request failed: {exc}") from exc
        return rows

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
        network_id = str(network_id or self.settings.network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        snapshot_id = self.resolve_snapshot_id(network_id, snapshot_id or self.settings.snapshot_id)
        query_spec = self.resolve_query_spec(query_spec)
        limit = int(limit or self.settings.nqe_page_size)
        if limit < 1:
            raise ForwardConfigurationError("Forward NQE page size must be at least 1.")
        return self.run_nqe_query_async(
            query_spec=query_spec,
            network_id=network_id,
            snapshot_id=snapshot_id,
            limit=limit,
            offset=offset,
            fetch_all=fetch_all,
        )

    def run_nqe_diff(
        self,
        *,
        query_id: str,
        before_snapshot_id: str,
        after_snapshot_id: str,
        commit_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        query_id = str(query_id or "").strip()
        before_snapshot_id = str(before_snapshot_id or "").strip()
        after_snapshot_id = str(after_snapshot_id or "").strip()
        if not query_id:
            raise ForwardConfigurationError("Forward query ID is required.")
        if not before_snapshot_id or not after_snapshot_id:
            raise ForwardConfigurationError("Both before and after snapshot IDs are required.")
        limit = int(limit or self.settings.nqe_page_size)
        if limit < 1:
            raise ForwardConfigurationError("Forward NQE page size must be at least 1.")

        def fetch_page(page_offset: int) -> tuple[list[dict[str, Any]], int | None]:
            payload: dict[str, Any] = {
                "queryId": query_id,
                "options": {
                    "limit": limit,
                    "offset": page_offset,
                },
            }
            if commit_id:
                payload["commitId"] = commit_id
            if parameters:
                payload["parameters"] = parameters
            response = self._request(
                "POST",
                f"/nqe-diffs/{quote(before_snapshot_id, safe='')}/{quote(after_snapshot_id, safe='')}",
                json_body=payload,
            )
            return self._parse_nqe_diff_rows(response.json() or {})

        return self._paginate_rows(
            fetch_page,
            limit=limit,
            offset=offset,
            fetch_all=fetch_all,
            exhausted_message=(
                "Forward NQE diff pagination exceeded "
                f"{self.settings.nqe_fetch_all_max_pages} page(s)."
            ),
        )

    def get_nqe_execution_status(
        self,
        *,
        network_id: str,
        execution_key: str,
    ) -> dict[str, Any]:
        network_id = str(network_id or "").strip()
        execution_key = str(execution_key or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        if not execution_key:
            raise ForwardConfigurationError("Forward execution key is required.")
        response = self._request(
            "GET",
            f"/networks/{quote(network_id, safe='')}/nqe-executions/{quote(execution_key, safe='')}",
        )
        data = response.json() or {}
        if not isinstance(data, dict):
            raise ForwardClientError(
                "Forward NQE execution status response returned an invalid payload."
            )
        return data

    def get_nqe_execution_result(
        self,
        *,
        execution_key: str,
        network_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        network_id = str(network_id or self.settings.network_id or "").strip()
        execution_key = str(execution_key or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        if not execution_key:
            raise ForwardConfigurationError("Forward execution key is required.")
        limit = int(limit or self.settings.nqe_page_size)
        if limit < 1:
            raise ForwardConfigurationError("Forward NQE page size must be at least 1.")

        def fetch_page(page_offset: int) -> tuple[list[dict[str, Any]], int | None]:
            response = self._request(
                "GET",
                f"/networks/{quote(network_id, safe='')}/nqe-executions/{quote(execution_key, safe='')}/result",
                params={
                    "offset": page_offset,
                    "limit": limit,
                },
                headers={"Accept": NQE_ASYNC_RESULT_ACCEPT},
            )
            return self._parse_nqe_async_result(response)

        return self._paginate_rows(
            fetch_page,
            limit=limit,
            offset=offset,
            fetch_all=fetch_all,
            exhausted_message=(
                "Forward NQE execution result pagination exceeded "
                f"{self.settings.nqe_fetch_all_max_pages} page(s)."
            ),
        )

    def request_nqe_execution(
        self,
        *,
        query_spec: ForwardQuerySpec,
        network_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        network_id = str(network_id or self.settings.network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        raw_snapshot = str(snapshot_id or self.settings.snapshot_id or "").strip()
        resolved_snapshot_id = (
            raw_snapshot
            if raw_snapshot and raw_snapshot != LATEST_PROCESSED_SNAPSHOT
            else self.resolve_snapshot_id(network_id, raw_snapshot)
        )
        if not query_spec.resolved_query_id:
            query_spec = self.resolve_query_spec(query_spec)
        payload: dict[str, Any] = {}
        query_id = query_spec.resolved_query_id or query_spec.query_id
        commit_id = query_spec.resolved_commit_id or query_spec.commit_id
        # Self-contained ad-hoc query text takes no parameters; only saved queries
        # (queryId) bind them. Sending params with a bare main query is a 400.
        if query_spec.parameters and query_id:
            payload["parameters"] = dict(query_spec.parameters)
        if query_id:
            payload["queryId"] = query_id
            if commit_id:
                payload["commitId"] = commit_id
        else:
            payload["query"] = query_spec.query_text
        # sortKeys only order results and are only honoured for saved queries
        # (queryId). The ad-hoc /nqe-executions endpoint on some Forward builds
        # rejects them outright, so send them only when running a saved query.
        if query_spec.sort_keys and query_id:
            payload["sortKeys"] = [
                {"columnName": col, "order": "ASC"} for col in query_spec.sort_keys
            ]
        response = self._request(
            "POST",
            f"/networks/{quote(network_id, safe='')}/nqe-executions",
            params={"snapshotId": resolved_snapshot_id},
            json_body=payload,
        )
        data = response.json() or {}
        if not isinstance(data, dict):
            raise ForwardClientError("Forward NQE execution response returned an invalid payload.")
        execution_key = str(data.get("executionKey") or "").strip()
        if not execution_key:
            raise ForwardClientError(
                "Forward NQE execution response did not include an execution key."
            )
        return data

    def run_nqe_query_async(
        self,
        *,
        query_spec: ForwardQuerySpec,
        network_id: str | None = None,
        snapshot_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
        poll_interval_seconds: float = 5.0,
        max_polls: int = 60,
    ) -> list[dict[str, Any]]:
        network_id = str(network_id or self.settings.network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        execution = self.request_nqe_execution(
            query_spec=query_spec,
            network_id=network_id,
            snapshot_id=snapshot_id,
        )
        execution_key = str(execution.get("executionKey") or "").strip()
        status = execution if isinstance(execution, dict) else {}
        if str(status.get("status") or "").strip() != "COMPLETED":
            poll_cap = max(0.0, float(poll_interval_seconds))
            poll_wait = min(0.5, poll_cap)
            for poll_count in range(int(max_polls)):
                if poll_count:
                    time.sleep(poll_wait)
                    poll_wait = min(poll_wait * 2.0, poll_cap)
                status = self.get_nqe_execution_status(
                    network_id=network_id,
                    execution_key=execution_key,
                )
                if str(status.get("status") or "").strip() == "COMPLETED":
                    break
            else:
                raise ForwardClientError(
                    "Forward NQE execution did not complete before the poll limit was reached."
                )
        outcome = str(status.get("outcome") or "").strip()
        if outcome != "OK":
            error = status.get("error")
            error_text = f": {error}" if error is not None else ""
            raise ForwardClientError(
                f"Forward NQE execution completed with outcome {outcome or 'UNKNOWN'}{error_text}"
            )
        limit = int(limit or self.settings.nqe_page_size)
        if fetch_all:
            return self._fetch_ndjson_stream(
                self._api_url(
                    f"/networks/{quote(network_id, safe='')}"
                    f"/nqe-executions/{quote(execution_key, safe='')}/result"
                )
            )
        return self.get_nqe_execution_result(
            execution_key=execution_key,
            network_id=network_id,
            limit=limit,
            offset=offset,
            fetch_all=False,
        )
