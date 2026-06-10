"""Sync runner scaffolding for the Forward integration."""

from dataclasses import dataclass
from dataclasses import replace

from .client import ForwardClient
from .exceptions import ForwardConfigurationError
from .models import ForwardSnapshotInfo
from .models import ForwardSyncReport
from .models import ForwardSyncSpec
from .registry import get_model_mappings


@dataclass(slots=True)
class ForwardSyncRunner:
    """Turn a sync spec into a report and, later, Nautobot writes."""

    client: ForwardClient

    def _run(self, spec: ForwardSyncSpec, *, mode: str) -> ForwardSyncReport:
        connection = spec.connection
        network_id = str(connection.network_id or "").strip()
        if not network_id:
            raise ForwardConfigurationError("Forward network ID is required.")
        query_spec = self.client.resolve_query_spec(spec.query)
        snapshot_id = self.client.resolve_snapshot_id(
            network_id, connection.snapshot_id
        )
        rows = self.client.run_nqe_query(
            query_spec=query_spec,
            network_id=network_id,
            snapshot_id=snapshot_id,
            limit=spec.limit or connection.nqe_page_size,
            offset=spec.offset,
            fetch_all=spec.fetch_all,
            item_format=spec.item_format,
        )
        snapshot_metrics = {}
        try:
            snapshot_metrics = self.client.get_snapshot_metrics(snapshot_id)
        except Exception:
            snapshot_metrics = {}
        planned_models = tuple(
            mapping.slug for mapping in get_model_mappings(spec.model_names)
        )
        notes = ()
        if mode == "sync":
            notes = (
                "Nautobot write path is not implemented yet; this run is preview-only.",
            )
        return ForwardSyncReport(
            mode=mode,
            source_url=connection.base_url.rstrip("/"),
            network_id=network_id,
            snapshot_id=snapshot_id,
            query_mode=query_spec.execution_mode,
            query_reference=query_spec.reference,
            row_count=len(rows),
            rows=tuple(rows),
            snapshot_metrics=snapshot_metrics,
            available_snapshots=tuple(
                ForwardSnapshotInfo(**item)
                for item in self._snapshot_choices(network_id)
            ),
            planned_models=planned_models,
            notes=notes,
        )

    def _snapshot_choices(self, network_id: str):
        try:
            return self.client.get_snapshots(network_id)
        except Exception:
            return []

    def preview(self, spec: ForwardSyncSpec) -> ForwardSyncReport:
        return self._run(spec, mode="preview")

    def sync(self, spec: ForwardSyncSpec) -> ForwardSyncReport:
        sync_spec = replace(spec, mode="sync")
        return self._run(sync_spec, mode="sync")

