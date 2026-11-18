"""Architecture audit: is the slice registry consistent with what actually ships?

One JSON report that answers "if I add or change a slice, what else must change?".
It cross-checks the registry against the bundled queries and their contracts, so
a slice that points at a query that is not packaged, a contract version that
disagrees with the query header, or a dependency that does not exist is found
here rather than on a customer's first sync.

Pure: reads the registry and the packaged query files only. No Forward access,
no database.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .queries import QUERY_CONTRACT_VERSIONS, QUERY_FILENAMES, get_query_contract_fields
from .registry import (
    CORE_MODEL_MAPPINGS,
    ForwardModelMapping,
)

_RANK = {"pass": 0, "warn": 1, "fail": 2}


def _finding(severity: str, code: str, slug: str, message: str) -> dict[str, str]:
    return {"severity": severity, "code": code, "slice": slug, "message": message}


def _find_cycle(mappings: Sequence[ForwardModelMapping]) -> str | None:
    """Return a slug on a dependency cycle, or ``None``."""
    by_slug = {m.slug: m for m in mappings}
    done: set[str] = set()

    def visit(slug: str, path: tuple[str, ...]) -> str | None:
        if slug in path:
            return slug
        if slug in done or slug not in by_slug:
            return None
        for dependency in by_slug[slug].depends_on:
            hit = visit(dependency, (*path, slug))
            if hit:
                return hit
        done.add(slug)
        return None

    for mapping in mappings:
        hit = visit(mapping.slug, ())
        if hit:
            return hit
    return None


def build_architecture_audit(
    mappings: Sequence[ForwardModelMapping] | None = None,
) -> dict[str, Any]:
    """Audit ``mappings`` (default: the registry) and return the report."""
    mappings = tuple(CORE_MODEL_MAPPINGS if mappings is None else mappings)
    known = {m.slug for m in mappings}
    findings: list[dict[str, str]] = []
    slices: list[dict[str, Any]] = []

    for m in mappings:
        if m.forward_query_file not in QUERY_FILENAMES:
            findings.append(
                _finding(
                    "fail",
                    "query_not_bundled",
                    m.slug,
                    f"{m.forward_query_file} is not a packaged query, so this slice cannot run.",
                )
            )
        else:
            contract_fields = set(get_query_contract_fields(m.forward_query_file))
            missing_identity = [f for f in m.identity_fields if f not in contract_fields]
            if missing_identity:
                findings.append(
                    _finding(
                        "fail",
                        "identity_field_not_in_contract",
                        m.slug,
                        f"identity field(s) {missing_identity} are not columns of "
                        f"{m.forward_query_file}, so rows could never be matched.",
                    )
                )
            shipped = QUERY_CONTRACT_VERSIONS.get(m.forward_query_file, "")
            if shipped != m.contract_version:
                findings.append(
                    _finding(
                        "fail",
                        "contract_version_mismatch",
                        m.slug,
                        f"registry says {m.contract_version!r} but {m.forward_query_file} "
                        f"declares {shipped!r}.",
                    )
                )
        for dependency in m.depends_on:
            if dependency not in known:
                findings.append(
                    _finding(
                        "fail",
                        "unknown_dependency",
                        m.slug,
                        f"depends on {dependency!r}, which is not a registered slice.",
                    )
                )
        slices.append(
            {
                "slug": m.slug,
                "query_file": m.forward_query_file,
                "contract_version": m.contract_version,
                "nautobot_scope": m.nautobot_scope,
                "write_mode": m.write_mode,
                "missing_row_policy": m.missing_row_policy,
                "depends_on": list(m.depends_on),
                "supports_device_filters": m.supports_device_filters,
                "enabled_by_default": m.enabled_by_default,
            }
        )

    # Deliberately not checked: supports_device_filters against a scope_devices
    # column. Several filterable slices scope by their own device column instead,
    # and the prefix slices fail closed under a filtered run, so that pairing is
    # not an invariant of the registry.
    cycle = _find_cycle(mappings)
    if cycle:
        findings.append(
            _finding("fail", "dependency_cycle", cycle, "slice dependencies form a cycle.")
        )

    used = {m.forward_query_file for m in mappings}
    worst = max((_RANK[f["severity"]] for f in findings), default=0)
    return {
        "status": {v: k for k, v in _RANK.items()}[worst],
        "slice_count": len(slices),
        "slices": slices,
        # Packaged queries that no slice reads: cables and cloud are driven by their
        # own sync routines, so these are information, not findings.
        "non_slice_queries": sorted(set(QUERY_FILENAMES) - used),
        "findings": findings,
    }
