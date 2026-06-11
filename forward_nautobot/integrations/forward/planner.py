"""Ingestion planning for the Forward integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from importlib import resources

from .adapters import ForwardSourceAdapter
from .adapters import NautobotTargetAdapter
from .client import ForwardClient
from ...models import ForwardConnectionProfileRecord
from .models import ForwardConnectionSettings
from .models import ForwardQuerySpec
from .models import ForwardSyncReport
from .registry import ForwardModelMapping
from .registry import get_model_mappings
from .write_path import ForwardWritePlan
from .write_path import ForwardWritePlanner


@dataclass(slots=True)
class ForwardIngestionRequest:
    """Inputs for a raw ingestion pass."""

    connection: ForwardConnectionSettings
    model_names: tuple[str, ...] = ()
    fetch_all: bool = True
    limit: int | None = None
    offset: int = 0
    item_format: str = "JSON"
    snapshot_id: str | None = None
    connection_profile: ForwardConnectionProfileRecord | None = None


@dataclass(slots=True)
class ForwardIngestionPlan:
    """Raw ingestion plan for the selected Forward model slices."""

    source: ForwardSourceAdapter
    target: NautobotTargetAdapter
    reports: tuple[ForwardSyncReport, ...]
    write_plan: ForwardWritePlan
    diff_summary: dict[str, int]
    diff_detail: dict[str, Any]

    @property
    def source_summary(self) -> dict[str, Any]:
        return self.source.as_support_summary()

    @property
    def target_summary(self) -> dict[str, Any]:
        return self.target.as_support_summary()

    @property
    def write_summary(self) -> dict[str, int]:
        return dict(self.write_plan.summary)

    @property
    def configuration_status(self) -> dict[str, Any]:
        return dict(self.write_plan.configuration_status)


class ForwardIngestionPlanner:
    """Load Forward rows and prepare them for Nautobot writes without mutation."""

    def __init__(self, client: ForwardClient):
        self.client = client

    @staticmethod
    def _query_text_for(mapping: ForwardModelMapping) -> str:
        package = resources.files("forward_nautobot.integrations.forward.queries")
        return (package / mapping.forward_query_file).read_text(encoding="utf-8")

    def run(self, request: ForwardIngestionRequest) -> ForwardIngestionPlan:
        connection = request.connection
        network_id = str(connection.network_id or "").strip()
        if not network_id:
            raise ValueError("Forward network ID is required.")
        source = ForwardSourceAdapter(model_names=request.model_names)
        target = NautobotTargetAdapter(model_names=request.model_names)
        writer = ForwardWritePlanner()
        reports: list[ForwardSyncReport] = []
        for mapping in get_model_mappings(request.model_names):
            query_text = self._query_text_for(mapping)
            rows = self.client.run_nqe_query(
                query_spec=ForwardQuerySpec(query_text=query_text),
                network_id=network_id,
                snapshot_id=request.snapshot_id or connection.snapshot_id,
                limit=request.limit or connection.nqe_page_size,
                offset=request.offset,
                fetch_all=request.fetch_all,
                item_format=request.item_format,
            )
            source.load_rows(mapping.slug, rows)
            reports.append(
                ForwardSyncReport(
                    mode="preview",
                    source_url=connection.base_url.rstrip("/"),
                    network_id=network_id,
                    snapshot_id=request.snapshot_id or connection.snapshot_id,
                    query_mode="bundled_nqe",
                    query_reference=mapping.forward_query_file,
                    query_contract_version=mapping.contract_version,
                    row_count=len(rows),
                    rows=tuple(rows),
                    planned_models=(mapping.slug,),
                    notes=(f"Loaded {mapping.slug} rows from bundled NQE.",),
                )
            )
        write_plan = writer.plan(source, target, profile=request.connection_profile)
        diff = source.sync_to(target)
        return ForwardIngestionPlan(
            source=source,
            target=target,
            reports=tuple(reports),
            write_plan=write_plan,
            diff_summary=diff.summary(),
            diff_detail=diff.dict(),
        )
