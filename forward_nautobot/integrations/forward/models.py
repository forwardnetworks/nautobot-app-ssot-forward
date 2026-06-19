"""Forward integration data contracts."""

from dataclasses import dataclass, field, replace
from typing import Any, Literal

LATEST_PROCESSED_SNAPSHOT = "latestProcessed"


@dataclass(slots=True)
class ForwardConnectionSettings:
    """Connection and request tuning for the Forward API."""

    base_url: str = "https://fwd.app"
    username: str = ""
    password: str = ""
    network_id: str = ""
    snapshot_id: str = LATEST_PROCESSED_SNAPSHOT
    verify_tls: bool = True
    timeout_seconds: float = 30.0
    retries: int = 2
    request_min_interval_seconds: float = 0.0
    nqe_page_size: int = 1000
    nqe_fetch_all_max_pages: int = 100

    @property
    def has_basic_auth(self) -> bool:
        return bool(self.username and self.password)


@dataclass(slots=True)
class ForwardQuerySpec:
    """A normalized query reference for Forward NQE execution."""

    query_text: str | None = None
    query_id: str | None = None
    query_path: str | None = None
    query_repository: str = "org"
    commit_id: str | None = None
    resolved_query_id: str | None = None
    resolved_commit_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    sort_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reference_count = sum(
            bool(value) for value in (self.query_text, self.query_id, self.query_path)
        )
        if reference_count != 1:
            raise ValueError(
                "Exactly one of `query_text`, `query_id`, or `query_path` must be set."
            )
        if self.query_path and not self.query_repository:
            self.query_repository = "org"

    @property
    def execution_mode(self) -> str:
        if self.query_path:
            return "query_path"
        if self.query_id:
            return "query_id"
        return "query"

    @property
    def reference(self) -> str:
        if self.query_path:
            return f"{self.query_repository}:{self.query_path}"
        if self.query_id:
            return self.query_id
        return "<inline query>"

    def with_query_id(self, query_id: str, commit_id: str | None = None):
        return replace(
            self,
            resolved_query_id=query_id,
            resolved_commit_id=commit_id if commit_id is not None else self.commit_id,
        )


@dataclass(slots=True)
class ForwardSyncSpec:
    """All runtime inputs for a Forward sync request."""

    mode: Literal["preview", "sync"] = "preview"
    connection: ForwardConnectionSettings = field(default_factory=ForwardConnectionSettings)
    query: ForwardQuerySpec | None = None
    fetch_all: bool = True
    limit: int | None = None
    offset: int = 0
    model_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.query is None:
            raise ValueError("`query` is required.")


@dataclass(slots=True)
class ForwardSnapshotInfo:
    """Snapshot data shown in the UI/reporting layer."""

    id: str
    state: str = ""
    created_at: str = ""
    processed_at: str = ""
    label: str = ""


@dataclass(slots=True)
class ForwardSyncReport:
    """Execution summary returned by a preview/sync run."""

    mode: str
    source_url: str
    network_id: str
    snapshot_id: str
    query_mode: str
    query_reference: str
    row_count: int
    baseline_snapshot_id: str = ""
    query_contract_version: str = ""
    rows: tuple[dict[str, Any], ...] = ()
    snapshot_metrics: dict[str, Any] = field(default_factory=dict)
    available_snapshots: tuple[ForwardSnapshotInfo, ...] = ()
    planned_models: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "source_url": self.source_url,
            "network_id": self.network_id,
            "snapshot_id": self.snapshot_id,
            "query_mode": self.query_mode,
            "query_reference": self.query_reference,
            "query_contract_version": self.query_contract_version,
            "row_count": self.row_count,
            "baseline_snapshot_id": self.baseline_snapshot_id,
            "rows": [dict(row) for row in self.rows],
            "snapshot_metrics": dict(self.snapshot_metrics),
            "available_snapshots": [
                {
                    "id": snapshot.id,
                    "state": snapshot.state,
                    "created_at": snapshot.created_at,
                    "processed_at": snapshot.processed_at,
                    "label": snapshot.label,
                }
                for snapshot in self.available_snapshots
            ],
            "planned_models": list(self.planned_models),
            "notes": list(self.notes),
        }

    @property
    def summary(self) -> str:
        return (
            f"{self.mode} {self.row_count} row(s) from {self.query_reference} on {self.snapshot_id}"
        )
