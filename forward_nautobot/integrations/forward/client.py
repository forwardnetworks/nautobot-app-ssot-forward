"""Forward API client for Nautobot sync jobs."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .exceptions import ForwardClientError
from .exceptions import ForwardConfigurationError
from .models import ForwardConnectionSettings
from .models import ForwardQuerySpec
from .models import LATEST_PROCESSED_SNAPSHOT


TRANSIENT_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
@dataclass(slots=True)
class ForwardClient:
    """Small, testable wrapper around the Forward REST API."""

    settings: ForwardConnectionSettings
    transport: httpx.BaseTransport | None = None

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
            "User-Agent": "forward-nautobot/0.1.0",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.settings.retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    verify=self.verify,
                    transport=self.transport,
                ) as client:
                    response = client.request(
                        method,
                        self._api_url(path),
                        params=params,
                        json=json_body,
                        headers=self._headers(),
                        auth=self.auth,
                    )
                if response.status_code in TRANSIENT_HTTP_STATUS_CODES:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code not in TRANSIENT_HTTP_STATUS_CODES or attempt >= self.settings.retries:
                    raise ForwardClientError(
                        f"Forward API request failed with HTTP {status_code}: "
                        f"{exc.response.text}"
                    ) from exc
                last_error = exc
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt >= self.settings.retries:
                    raise ForwardClientError(
                        f"Forward API request failed: {exc}"
                    ) from exc
                last_error = exc

        raise ForwardClientError("Forward API request failed.") from last_error

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
        return snapshots

    def get_latest_processed_snapshot(self, network_id: str) -> dict[str, Any]:
        network_id = str(network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        response = self._request(
            "GET",
            f"/networks/{quote(network_id, safe='')}/snapshots/latestProcessed",
        )
        snapshot = response.json() or {}
        return snapshot if isinstance(snapshot, dict) else {}

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
        if not snapshot_id or snapshot_id == LATEST_PROCESSED_SNAPSHOT:
            return self.get_latest_processed_snapshot_id(network_id)
        return snapshot_id

    def get_snapshot_metrics(self, snapshot_id: str) -> dict[str, Any]:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return {}
        response = self._request(
            "GET",
            f"/snapshots/{quote(snapshot_id, safe='')}/metrics",
        )
        metrics = response.json() or {}
        return metrics if isinstance(metrics, dict) else {}

    def get_committed_nqe_query(
        self,
        *,
        repository: str = "org",
        query_path: str,
        commit_id: str = "head",
    ) -> dict[str, Any]:
        repository = str(repository or "org").strip() or "org"
        query_path = str(query_path or "").strip()
        commit_id = str(commit_id or "head").strip() or "head"
        if not query_path:
            raise ForwardConfigurationError("Forward NQE query path is required.")
        response = self._request(
            "GET",
            f"/nqe/repos/{quote(repository, safe='')}/commits/{quote(commit_id, safe='')}/queries",
            params={"path": query_path},
        )
        data = response.json() or {}
        if isinstance(data, dict) and isinstance(data.get("queries"), list):
            for row in data["queries"]:
                if isinstance(row, dict) and str(row.get("path") or "").strip() == query_path:
                    return row
            raise ForwardClientError(
                f"Forward NQE repository lookup did not include `{query_path}`."
            )
        if isinstance(data, dict):
            return data
        raise ForwardClientError(
            f"Forward NQE repository lookup for `{query_path}` returned an invalid response."
        )

    def resolve_query_spec(self, query_spec: ForwardQuerySpec) -> ForwardQuerySpec:
        if query_spec.query_path:
            query = self.get_committed_nqe_query(
                repository=query_spec.query_repository or "org",
                query_path=query_spec.query_path,
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
            return query_spec.with_query_id(query_id, commit_id or None)
        return query_spec

    def _parse_nqe_records(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
        items = data.get("items") or []
        rows: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("fields"), dict):
                rows.append(dict(item["fields"]))
            elif isinstance(item, dict):
                rows.append(dict(item))
        total = data.get("totalNumItems")
        try:
            total_int = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_int = None
        return rows, total_int

    def _parse_nqe_diff_rows(
        self, data: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int | None]:
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

    @staticmethod
    def _page_signature(rows: list[dict[str, Any]]) -> tuple[int, str, str] | None:
        if not rows:
            return None
        first = rows[0]
        last = rows[-1]
        return (
            len(rows),
            repr(sorted(first.items())),
            repr(sorted(last.items())),
        )

    def run_nqe_query(
        self,
        *,
        query_spec: ForwardQuerySpec,
        network_id: str | None = None,
        snapshot_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        fetch_all: bool = False,
        item_format: str = "JSON",
    ) -> list[dict[str, Any]]:
        network_id = str(network_id or self.settings.network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        snapshot_id = self.resolve_snapshot_id(
            network_id, snapshot_id or self.settings.snapshot_id
        )
        query_spec = self.resolve_query_spec(query_spec)
        limit = int(limit or self.settings.nqe_page_size)
        if limit < 1:
            raise ForwardConfigurationError("Forward NQE page size must be at least 1.")

        def fetch_page(page_offset: int) -> tuple[list[dict[str, Any]], int | None]:
            payload: dict[str, Any] = {
                "parameters": dict(query_spec.parameters),
                "queryOptions": {
                    "limit": limit,
                    "offset": page_offset,
                    "itemFormat": item_format,
                },
            }
            query_id = query_spec.resolved_query_id or query_spec.query_id
            commit_id = query_spec.resolved_commit_id or query_spec.commit_id
            if query_id:
                payload["queryId"] = query_id
                if commit_id:
                    payload["commitId"] = commit_id
            else:
                payload["query"] = query_spec.query_text
            response = self._request(
                "POST",
                "/nqe",
                params={"networkId": network_id, "snapshotId": snapshot_id},
                json_body=payload,
            )
            return self._parse_nqe_records(response.json() or {})

        rows, total = fetch_page(offset)
        if not fetch_all:
            return rows

        all_rows = list(rows)
        fetched_pages = 1
        previous_signature = (
            self._page_signature(rows) if len(rows) == limit and rows else None
        )
        identical_full_page_streak = 0
        while True:
            if total is not None and len(all_rows) >= total:
                return all_rows
            if total is None and len(rows) < limit:
                return all_rows
            if fetched_pages >= self.settings.nqe_fetch_all_max_pages:
                raise ForwardClientError(
                    "Forward NQE pagination exceeded "
                    f"{self.settings.nqe_fetch_all_max_pages} page(s)."
                )
            next_offset = offset + len(all_rows)
            rows, page_total = fetch_page(next_offset)
            fetched_pages += 1
            if total is None and page_total is not None:
                total = page_total
            if not rows:
                return all_rows
            if total is None and len(rows) == limit:
                signature = self._page_signature(rows)
                if signature == previous_signature:
                    identical_full_page_streak += 1
                else:
                    identical_full_page_streak = 0
                previous_signature = signature
                if (
                    identical_full_page_streak
                    >= self.settings.nqe_identical_full_page_streak_limit
                ):
                    raise ForwardClientError(
                        "Forward NQE pagination did not advance; repeated identical pages were returned."
                    )
            else:
                previous_signature = None
                identical_full_page_streak = 0
            all_rows.extend(rows)

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
        item_format: str = "JSON",
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        query_id = str(query_id or "").strip()
        before_snapshot_id = str(before_snapshot_id or "").strip()
        after_snapshot_id = str(after_snapshot_id or "").strip()
        if not query_id:
            raise ForwardConfigurationError("Forward query ID is required.")
        if not before_snapshot_id or not after_snapshot_id:
            raise ForwardConfigurationError(
                "Both before and after snapshot IDs are required."
            )
        limit = int(limit or self.settings.nqe_page_size)
        if limit < 1:
            raise ForwardConfigurationError("Forward NQE page size must be at least 1.")

        def fetch_page(page_offset: int) -> tuple[list[dict[str, Any]], int | None]:
            payload: dict[str, Any] = {
                "queryId": query_id,
                "options": {
                    "limit": limit,
                    "offset": page_offset,
                    "itemFormat": item_format,
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

        rows, total = fetch_page(offset)
        if not fetch_all:
            return rows

        all_rows = list(rows)
        fetched_pages = 1
        previous_signature = (
            self._page_signature(rows) if len(rows) == limit and rows else None
        )
        identical_full_page_streak = 0
        while True:
            if total is not None and len(all_rows) >= total:
                return all_rows
            if total is None and len(rows) < limit:
                return all_rows
            if fetched_pages >= self.settings.nqe_fetch_all_max_pages:
                raise ForwardClientError(
                    "Forward NQE diff pagination exceeded "
                    f"{self.settings.nqe_fetch_all_max_pages} page(s)."
                )
            next_offset = offset + len(all_rows)
            rows, page_total = fetch_page(next_offset)
            fetched_pages += 1
            if total is None and page_total is not None:
                total = page_total
            if not rows:
                return all_rows
            if total is None and len(rows) == limit:
                signature = self._page_signature(rows)
                if signature == previous_signature:
                    identical_full_page_streak += 1
                else:
                    identical_full_page_streak = 0
                previous_signature = signature
                if (
                    identical_full_page_streak
                    >= self.settings.nqe_identical_full_page_streak_limit
                ):
                    raise ForwardClientError(
                        "Forward NQE diff pagination did not advance; repeated identical pages were returned."
                    )
            else:
                previous_signature = None
                identical_full_page_streak = 0
            all_rows.extend(rows)
