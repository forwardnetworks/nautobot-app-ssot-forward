"""Ingestion planning for the Forward integration."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from importlib import resources
from typing import Any

from ...models import ForwardConnectionProfileRecord
from .adapters import ForwardSourceAdapter, NautobotTargetAdapter
from .client import ForwardClient
from .exceptions import ForwardClientError, ForwardConfigurationError
from .models import ForwardConnectionSettings, ForwardQuerySpec, ForwardSyncReport
from .registry import ForwardModelMapping, get_model_mapping, get_model_mappings
from .write_contract import ForwardWriteContractAdvisor
from .write_path import ForwardWriteOperation, ForwardWritePlan, ForwardWritePlanner


@dataclass(slots=True)
class ForwardIngestionRequest:
    """Inputs for a raw ingestion pass."""

    connection: ForwardConnectionSettings
    model_names: tuple[str, ...] = ()
    fetch_all: bool = True
    limit: int | None = None
    offset: int = 0
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
        """Return inline-safe NQE text from a bundled .nqe file.

        Some Forward builds bind inline parameters via ForwardQuerySpec.parameters;
        others (the local master build) don't, and also reject @primaryKey, empty
        list literals, and a trailing ';'. To run on both, emit self-contained
        text: drop @primaryKey/@query and the `f(forward_location_names…) =`
        wrapper, drop the whole `where … forward_location_names …` location-filter
        clause (it's a no-op for an empty list — identical to a full, unscoped
        sync, but avoids the unsupported `[]`), and drop the trailing ';'.
        """
        package = resources.files("forward_nautobot.integrations.forward.queries")
        raw = (package / mapping.forward_query_file).read_text(encoding="utf-8")
        lines = raw.splitlines()
        # Drop leading /* ... */ doc comment block.
        if lines and lines[0].startswith("/*"):
            end = next((i for i, ln in enumerate(lines) if ln.rstrip().endswith("*/")), None)
            if end is not None:
                lines = lines[end + 1 :]
        params = ("forward_location_names", "forward_device_names")
        out: list[str] = []
        skip_or_continuation = False
        for ln in lines:
            s = ln.strip()
            if s.startswith("@primaryKey") or s.startswith("@query"):
                continue
            # Drop the `f(<param>: ...) =` function wrapper (any param name).
            if re.match(r"^f\s*\(\s*forward_\w+\b.*\)\s*=\s*$", s):
                continue
            # Drop the parameter-filter clause: the `where … <param>` line and its
            # immediately-following `|| …` continuation lines (a no-op for an empty
            # filter; avoids the unsupported `[]` literal entirely).
            if s.startswith("where") and any(p in s for p in params):
                skip_or_continuation = True
                continue
            if skip_or_continuation and s.startswith("||"):
                continue
            skip_or_continuation = False
            out.append(ln)
        text = "\n".join(out).strip()
        # The ad-hoc executor rejects a trailing ';' on a plain foreach…select, but
        # REQUIRES it when the query has a top-level `let` binding. Keep it only then.
        has_let = any(l.strip().startswith("let ") for l in out)
        if text.endswith(";") and not has_let:
            text = text[:-1].rstrip()
        return text

    @staticmethod
    def _row_key(mapping: ForwardModelMapping, row: dict[str, Any]) -> str:
        key_parts: list[str] = []
        for field_name in mapping.identity_fields:
            value = row.get(field_name)
            if value is None:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` is missing identity field `{field_name}`."
                )
            value_text = str(value).strip()
            if not value_text:
                raise ValueError(
                    f"Forward row for `{mapping.slug}` has an empty identity field `{field_name}`."
                )
            key_parts.append(value_text)
        return "|".join(key_parts)

    @staticmethod
    def _configuration_status(
        *,
        profile: ForwardConnectionProfileRecord | None,
        model_mappings: tuple[ForwardModelMapping, ...],
    ) -> dict[str, Any]:
        return {
            "profile_provided": profile is not None,
            "write_ready": bool(profile.write_ready) if profile is not None else False,
            "missing_defaults": list(profile.missing_write_defaults())
            if profile is not None
            else [],
            "delete_policy": getattr(profile, "delete_policy", "ignore")
            if profile is not None
            else "ignore",
            "slice_policies": {
                mapping.slug: {
                    "write_mode": mapping.write_mode,
                    "missing_row_policy": mapping.missing_row_policy,
                }
                for mapping in model_mappings
            },
        }

    @staticmethod
    def _slice_policy_for(mapping: ForwardModelMapping) -> dict[str, str]:
        return {
            "write_mode": mapping.write_mode,
            "missing_row_policy": mapping.missing_row_policy,
        }

    @staticmethod
    def _scope_values_for_source(
        source: ForwardSourceAdapter,
        source_slug: str,
    ) -> tuple[str, ...]:
        try:
            mapping = get_model_mapping(source_slug)
        except Exception:
            return ()
        records = source.records.get(mapping.slug, {})
        if not records:
            return ()
        field_name = mapping.identity_fields[0] if mapping.identity_fields else "name"
        values: list[str] = []
        for record in records.values():
            value = record.fields.get(field_name)
            if value is None:
                continue
            value_text = str(value).strip()
            if value_text:
                values.append(value_text)
        return tuple(dict.fromkeys(values))

    def _query_parameters_for(
        self,
        mapping: ForwardModelMapping,
        source: ForwardSourceAdapter,
    ) -> dict[str, list[str]]:
        if not mapping.query_parameters:
            return {}
        parameters: dict[str, list[str]] = {}
        for parameter_name, source_slugs in mapping.query_parameters.items():
            scoped_values: list[str] = []
            for source_slug in source_slugs:
                scoped_values.extend(self._scope_values_for_source(source, source_slug))
            parameters[parameter_name] = list(dict.fromkeys(scoped_values))
        return parameters

    @staticmethod
    def _merge_counts(
        base: dict[str, int],
        update: dict[str, int],
    ) -> dict[str, int]:
        merged = dict(base)
        for key, value in update.items():
            merged[key] = int(merged.get(key, 0) or 0) + int(value or 0)
        return merged

    def _build_full_plan(
        self,
        *,
        source: ForwardSourceAdapter,
        target: NautobotTargetAdapter,
        profile: ForwardConnectionProfileRecord | None,
    ) -> tuple[ForwardWritePlan, dict[str, int], dict[str, Any]]:
        writer = ForwardWritePlanner()
        write_plan = writer.plan(source, target, profile=profile)
        return write_plan, dict(write_plan.diff_summary), dict(write_plan.diff_detail)

    def _build_delta_plan(
        self,
        *,
        mapping: ForwardModelMapping,
        rows: list[dict[str, Any]],
        profile: ForwardConnectionProfileRecord | None,
    ) -> tuple[
        ForwardWritePlan,
        dict[str, int],
        dict[str, Any],
        tuple[dict[str, Any], ...],
        tuple[dict[str, Any], ...],
    ]:
        advisor = ForwardWriteContractAdvisor()
        operations: list[ForwardWriteOperation] = []
        summary = {"create": 0, "update": 0, "deleted": 0, "blocked": 0, "no-change": 0}
        source_rows: list[dict[str, Any]] = []
        diff_entries: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            before = dict(row.get("before") or {}) if isinstance(row.get("before"), dict) else {}
            after = dict(row.get("after") or {}) if isinstance(row.get("after"), dict) else {}
            if after and before:
                action = "update"
                data = after
            elif after:
                action = "create"
                data = after
            elif before:
                action = "delete"
                data = before
            else:
                continue
            record_key = self._row_key(mapping, data)
            blocked_by: tuple[str, ...] = ()
            if action != "delete":
                readiness = advisor.readiness_for(mapping, profile=profile, row=data)
                blocked_by = readiness.blocked_by
                if blocked_by:
                    summary["blocked"] += 1
            operations.append(
                ForwardWriteOperation(
                    model_slug=mapping.slug,
                    record_key=record_key,
                    nautobot_scope=mapping.nautobot_scope,
                    action=action,
                    fields=dict(data),
                    contract_version=mapping.contract_version,
                    blocked_by=blocked_by,
                )
            )
            if action == "delete":
                summary["deleted"] += 1
            else:
                summary[action] += 1
                source_rows.append(dict(data))
            diff_entries.append(
                {
                    "type": row.get("type"),
                    "before": before,
                    "after": after,
                    "action": action,
                    "record_key": record_key,
                }
            )
        if source_rows:
            source_rows_tuple = tuple(source_rows)
        else:
            source_rows_tuple = ()
        write_plan = ForwardWritePlan(
            operations=tuple(operations),
            summary=summary,
            configuration_status=self._configuration_status(
                profile=profile,
                model_mappings=(mapping,),
            ),
            slice_policies={mapping.slug: self._slice_policy_for(mapping)},
            delta_mode=True,
            delta_models=(mapping.slug,),
        )
        return (
            write_plan,
            summary,
            {
                "mode": "delta",
                "rows": diff_entries,
                "operation_count": len(operations),
            },
            source_rows_tuple,
            tuple(diff_entries),
        )

    @staticmethod
    def _compute_tiers(
        mappings: tuple[ForwardModelMapping, ...],
    ) -> list[list[ForwardModelMapping]]:
        """Group topologically-ordered mappings into parallel execution tiers.

        A tier boundary is created for both explicit `depends_on` structural
        dependencies and implicit `query_parameters` source-slug dependencies,
        since both require the source adapter to be populated before the query
        parameters can be computed.
        """
        selected_slugs = {m.slug for m in mappings}
        deps_by_slug: dict[str, list[str]] = {}
        for m in mappings:
            param_source_deps = {
                src_slug for src_slugs in m.query_parameters.values() for src_slug in src_slugs
            }
            all_deps = set(m.depends_on) | param_source_deps
            deps_by_slug[m.slug] = [d for d in all_deps if d in selected_slugs]

        # Longest-path levelling with explicit cycle detection. The registry only
        # cycle-checks depends_on, so a cycle introduced via query_parameters must
        # be caught here rather than KeyError-ing or mis-levelling at runtime.
        levels: dict[str, int] = {}
        resolving: set[str] = set()

        def _level_of(slug: str) -> int:
            cached = levels.get(slug)
            if cached is not None:
                return cached
            if slug in resolving:
                raise ForwardConfigurationError(
                    f"Forward model dependency cycle detected involving `{slug}` "
                    "(check depends_on and query_parameters)."
                )
            resolving.add(slug)
            level = 1 + max((_level_of(d) for d in deps_by_slug[slug]), default=0)
            resolving.discard(slug)
            levels[slug] = level
            return level

        for m in mappings:
            _level_of(m.slug)
        max_level = max(levels.values(), default=1)
        tiers: list[list[ForwardModelMapping]] = [[] for _ in range(max_level)]
        for m in mappings:
            tiers[levels[m.slug] - 1].append(m)
        return tiers

    def _fetch_slice(
        self,
        *,
        mapping: ForwardModelMapping,
        parameters: dict[str, list[str]],
        network_id: str,
        current_snapshot_id: str,
        baseline_snapshot_id: str,
        limit: int,
        offset: int,
        fetch_all: bool,
    ) -> tuple[
        list[dict[str, Any]],  # rows
        str,  # query_mode
        str,  # query_reference
        str,  # resolved_query_reference
        tuple[str, ...],  # notes
        bool,  # is_diff
        dict[str, Any] | None,  # diff_fallback_detail
    ]:
        """Run the network I/O for a single slice. Thread-safe — no shared state writes."""
        query_spec = ForwardQuerySpec(
            query_path=mapping.forward_query_path,
            parameters=parameters,
            sort_keys=mapping.identity_fields,
        )
        query_mode = "bundled_nqe"
        query_reference = mapping.forward_query_file
        notes: tuple[str, ...] = (f"Loaded {mapping.slug} rows from bundled NQE.",)
        resolved_query_reference = ""
        diff_fallback_detail: dict[str, Any] | None = None
        is_diff = False

        try:
            resolved_query_spec = self.client.resolve_query_spec(query_spec)
        except ForwardClientError as exc:
            query_text = self._query_text_for(mapping)
            rows = self.client.run_nqe_query(
                query_spec=ForwardQuerySpec(
                    query_text=query_text,
                    parameters=parameters,
                    sort_keys=mapping.identity_fields,
                ),
                network_id=network_id,
                snapshot_id=current_snapshot_id,
                limit=limit,
                offset=offset,
                fetch_all=fetch_all,
            )
            query_mode = "bundled_nqe_inline"
            query_reference = mapping.forward_query_file
            notes = notes + (
                f"Bundled query path resolution failed ({type(exc).__name__}: {exc}); "
                "inline NQE was used.",
            )
            return (
                rows,
                query_mode,
                query_reference,
                resolved_query_reference,
                notes,
                is_diff,
                diff_fallback_detail,
            )

        query_mode = "bundled_nqe_query_id"
        resolved_query_reference = resolved_query_spec.reference
        if (
            baseline_snapshot_id
            and baseline_snapshot_id != current_snapshot_id
            and (resolved_query_spec.resolved_query_id or resolved_query_spec.query_id)
        ):
            try:
                rows = self.client.run_nqe_diff(
                    query_id=resolved_query_spec.resolved_query_id
                    or resolved_query_spec.query_id
                    or "",
                    commit_id=resolved_query_spec.resolved_commit_id
                    or resolved_query_spec.commit_id,
                    parameters=resolved_query_spec.parameters,
                    before_snapshot_id=baseline_snapshot_id,
                    after_snapshot_id=current_snapshot_id,
                    limit=limit,
                    offset=offset,
                    fetch_all=fetch_all,
                )
                query_mode = "bundled_nqe_query_id_diff"
                is_diff = True
            except ForwardClientError as diff_error:
                notes = notes + (
                    f"Diff execution failed ({type(diff_error).__name__}: {diff_error}); "
                    "using query ID-backed full query instead.",
                )
                rows = self.client.run_nqe_query(
                    query_spec=resolved_query_spec,
                    network_id=network_id,
                    snapshot_id=current_snapshot_id,
                    limit=limit,
                    offset=offset,
                    fetch_all=fetch_all,
                )
                query_mode = "bundled_nqe_query_id"
                diff_fallback_detail = {
                    "mode": "snapshot",
                    "query_mode": query_mode,
                    "query_reference": query_reference,
                    "fallback": "diff-unavailable",
                    "error": str(diff_error),
                    "error_type": type(diff_error).__name__,
                    "rows": rows,
                }
        else:
            rows = self.client.run_nqe_query(
                query_spec=resolved_query_spec,
                network_id=network_id,
                snapshot_id=current_snapshot_id,
                limit=limit,
                offset=offset,
                fetch_all=fetch_all,
            )

        return (
            rows,
            query_mode,
            query_reference,
            resolved_query_reference,
            notes,
            is_diff,
            diff_fallback_detail,
        )

    def run(self, request: ForwardIngestionRequest) -> ForwardIngestionPlan:
        connection = request.connection
        network_id = str(connection.network_id or "").strip()
        if not network_id:
            raise ValueError("Forward network ID is required.")
        model_mappings = get_model_mappings(request.model_names)
        target = NautobotTargetAdapter(model_names=request.model_names)
        target.load()
        source = ForwardSourceAdapter(model_names=request.model_names)
        reports: list[ForwardSyncReport] = []
        current_snapshot_id = self.client.resolve_snapshot_id(
            network_id, request.snapshot_id or connection.snapshot_id
        )
        baseline_snapshot_id = str(
            getattr(request.connection_profile, "last_snapshot_id", "") or ""
        ).strip()
        if baseline_snapshot_id and baseline_snapshot_id == current_snapshot_id:
            empty_summary: dict[str, int] = {
                "create": 0,
                "update": 0,
                "no-change": 0,
                "blocked": 0,
                "deleted": 0,
            }
            return ForwardIngestionPlan(
                source=source,
                target=target,
                reports=(),
                write_plan=ForwardWritePlan(
                    configuration_status=self._configuration_status(
                        profile=request.connection_profile,
                        model_mappings=model_mappings,
                    ),
                    slice_policies={m.slug: self._slice_policy_for(m) for m in model_mappings},
                ),
                diff_summary=empty_summary,
                diff_detail={
                    "mode": "snapshot",
                    "baseline_snapshot_id": baseline_snapshot_id,
                    "current_snapshot_id": current_snapshot_id,
                    "delta_models": [],
                    "skipped": True,
                    "reason": "snapshot unchanged since last sync",
                    "slices": {},
                },
            )
        aggregate_operations: list[ForwardWriteOperation] = []
        aggregate_summary = {
            "create": 0,
            "update": 0,
            "no-change": 0,
            "blocked": 0,
            "deleted": 0,
        }
        diff_detail_slices: dict[str, Any] = {}
        delta_models: list[str] = []
        limit = request.limit or connection.nqe_page_size

        tiers = self._compute_tiers(model_mappings)

        # Warm the NQE query index cache before parallel tier dispatch.
        # All bundled mappings share org:head — one fetch fills the cache so
        # N parallel workers don't race on the same endpoint.
        try:
            self.client.get_nqe_repository_query_index(repository="org", commit_id="head")
        except ForwardClientError:
            pass  # per-slice inline fallback handles resolution failures

        for tier in tiers:
            # Compute query parameters for each slice in this tier (reads source, sequential).
            tier_params = {m.slug: self._query_parameters_for(m, source) for m in tier}

            # Fetch rows for each slice in parallel (pure network I/O, no shared writes).
            if len(tier) > 1:
                with ThreadPoolExecutor(max_workers=len(tier)) as pool:
                    futures = {
                        pool.submit(
                            self._fetch_slice,
                            mapping=m,
                            parameters=tier_params[m.slug],
                            network_id=network_id,
                            current_snapshot_id=current_snapshot_id,
                            baseline_snapshot_id=baseline_snapshot_id,
                            limit=limit,
                            offset=request.offset,
                            fetch_all=request.fetch_all,
                        ): m
                        for m in tier
                    }
                    tier_fetch: dict[str, tuple] = {}
                    for future in as_completed(futures):
                        slug = futures[future].slug
                        tier_fetch[slug] = future.result()
            else:
                m = tier[0]
                tier_fetch = {
                    m.slug: self._fetch_slice(
                        mapping=m,
                        parameters=tier_params[m.slug],
                        network_id=network_id,
                        current_snapshot_id=current_snapshot_id,
                        baseline_snapshot_id=baseline_snapshot_id,
                        limit=limit,
                        offset=request.offset,
                        fetch_all=request.fetch_all,
                    )
                }

            # Process results in topo order (mutates source — must be sequential).
            for mapping in tier:
                (
                    rows,
                    query_mode,
                    query_reference,
                    resolved_query_reference,
                    notes,
                    is_diff,
                    diff_fallback_detail,
                ) = tier_fetch[mapping.slug]
                query_contract_version = mapping.contract_version
                report_rows: list[dict[str, Any]] = []
                slice_write_plan: ForwardWritePlan
                slice_diff_summary: dict[str, int]
                slice_diff_detail: dict[str, Any]

                if is_diff:
                    (
                        slice_write_plan,
                        slice_diff_summary,
                        slice_diff_detail,
                        source_rows,
                        report_rows,
                    ) = self._build_delta_plan(
                        mapping=mapping,
                        rows=rows,
                        profile=request.connection_profile,
                    )
                    if source_rows:
                        source.load_rows(mapping.slug, source_rows)
                    delta_models.append(mapping.slug)
                    diff_detail_slices[mapping.slug] = {
                        **slice_diff_detail,
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "summary": dict(slice_write_plan.summary),
                    }
                else:
                    source.load_rows(mapping.slug, rows)
                    slice_source = source.slice_for_model(mapping.slug)
                    slice_target = target.slice_for_model(mapping.slug)
                    slice_write_plan, slice_diff_summary, slice_diff_detail = self._build_full_plan(
                        source=slice_source,
                        target=slice_target,
                        profile=request.connection_profile,
                    )
                    report_rows = rows
                    diff_detail_slices[mapping.slug] = {
                        "mode": "snapshot",
                        "query_mode": query_mode,
                        "query_reference": query_reference,
                        "resolved_query_reference": resolved_query_reference,
                        "rows": rows,
                        "diff_summary": dict(slice_diff_summary),
                        "diff_detail": slice_diff_detail,
                        "summary": dict(slice_write_plan.summary),
                    }
                    if diff_fallback_detail is not None:
                        diff_detail_slices[mapping.slug].update(diff_fallback_detail)

                aggregate_operations.extend(slice_write_plan.operations)
                aggregate_summary = self._merge_counts(aggregate_summary, slice_write_plan.summary)
                reports.append(
                    ForwardSyncReport(
                        mode="preview",
                        source_url=connection.base_url.rstrip("/"),
                        network_id=network_id,
                        snapshot_id=current_snapshot_id,
                        baseline_snapshot_id=baseline_snapshot_id,
                        query_mode=query_mode,
                        query_reference=query_reference,
                        query_contract_version=query_contract_version,
                        row_count=len(report_rows or rows),
                        rows=tuple(report_rows or rows),
                        planned_models=(mapping.slug,),
                        notes=(
                            *notes,
                            *(
                                (f"Diff baseline snapshot: {baseline_snapshot_id}.",)
                                if query_mode.endswith("_diff") and baseline_snapshot_id
                                else ()
                            ),
                        ),
                    )
                )

        write_plan = ForwardWritePlan(
            operations=tuple(aggregate_operations),
            summary=aggregate_summary,
            configuration_status=self._configuration_status(
                profile=request.connection_profile,
                model_mappings=model_mappings,
            ),
            slice_policies={
                mapping.slug: self._slice_policy_for(mapping) for mapping in model_mappings
            },
            delta_mode=bool(delta_models),
            delta_models=tuple(delta_models),
        )
        diff_detail = {
            "mode": (
                "mixed"
                if delta_models and len(delta_models) != len(model_mappings)
                else "delta"
                if delta_models
                else "snapshot"
            ),
            "baseline_snapshot_id": baseline_snapshot_id,
            "current_snapshot_id": current_snapshot_id,
            "delta_models": list(delta_models),
            "slices": diff_detail_slices,
        }
        return ForwardIngestionPlan(
            source=source,
            target=target,
            reports=tuple(reports),
            write_plan=write_plan,
            diff_summary=dict(aggregate_summary),
            diff_detail=diff_detail,
        )
