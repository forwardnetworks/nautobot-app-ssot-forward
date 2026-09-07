"""Idempotent publication and source-proof checks for bundled Forward NQEs."""

from __future__ import annotations

from typing import Any

from .client import ForwardClient
from .queries import QUERY_FILENAMES, read_bundled_query_source
from .registry import DEFAULT_QUERY_DIRECTORY


def normalize_query_source(source: str) -> str:
    return "\n".join(line.rstrip() for line in str(source or "").strip().splitlines()).strip()


def query_path_from_filename(
    filename: str,
    *,
    directory: str = DEFAULT_QUERY_DIRECTORY,
) -> str:
    normalized_directory = str(directory or "/").strip() or "/"
    if not normalized_directory.startswith("/"):
        normalized_directory = f"/{normalized_directory}"
    normalized_directory = normalized_directory.rstrip("/")
    query_name = str(filename or "").removesuffix(".nqe")
    return f"{normalized_directory}/{query_name}" if normalized_directory else f"/{query_name}"


def _committed_source(query: dict[str, Any]) -> str:
    return str(query.get("sourceCode") or query.get("source") or query.get("query") or "")


def _commit_id(query: dict[str, Any]) -> str:
    return str(
        query.get("lastCommitId")
        or query.get("commitId")
        or (query.get("lastCommit") or {}).get("id")
        or ""
    ).strip()


def _query_basis(
    client: ForwardClient,
    *,
    query_path: str,
    query_entry: dict[str, Any],
) -> dict[str, Any]:
    commit_id = _commit_id(query_entry)
    query_id = str(query_entry.get("queryId") or "").strip()
    if query_id and not commit_id:
        history = client.get_nqe_query_history(query_id)
        if history:
            commit_id = str(history[-1].get("id") or history[-1].get("commitId") or "").strip()
    committed = client.get_committed_nqe_query(
        repository="org",
        query_path=query_path,
        commit_id=commit_id or "head",
        require_source_code=True,
    )
    normalized = dict(committed)
    normalized.setdefault("queryId", query_id)
    normalized.setdefault("lastCommitId", commit_id or _commit_id(committed))
    return normalized


def _nqe_error_reason(exc: Exception, reason: str) -> bool:
    """Does this failure carry Forward's named reason code?

    The client attaches the parsed ``reason`` from Forward's error body, so
    prefer that. The string match remains as a fallback for an error that
    reached us without one; matching an exception's rendered text is fragile
    and should not be the primary path.
    """
    structured = getattr(exc, "reason", None)
    if structured:
        return str(structured) == reason
    return f'"reason":"{reason}"' in str(exc).replace(" ", "")


def _ensure_org_directory(
    client: ForwardClient,
    directory_path: str,
    *,
    touched_paths: list[str],
) -> None:
    normalized = "/" + str(directory_path or "").strip("/")
    if normalized == "/":
        return
    try:
        client.add_org_nqe_directory(directory_path=normalized)
    except Exception as exc:
        if _nqe_error_reason(exc, "ADD_DIR_TARGET_ALREADY_HAS_DIR"):
            return
        if not _nqe_error_reason(exc, "ENCLOSING_DIR_DOES_NOT_EXIST"):
            raise
        parent = normalized.rpartition("/")[0] or "/"
        _ensure_org_directory(client, parent, touched_paths=touched_paths)
        client.add_org_nqe_directory(directory_path=normalized)
        touched_paths.append(normalized)
    else:
        touched_paths.append(normalized)


def _add_org_query_with_directory_retry(
    client: ForwardClient,
    *,
    query_path: str,
    source_code: str,
    touched_paths: list[str],
) -> None:
    try:
        client.add_org_nqe_query(query_path=query_path, source_code=source_code)
    except Exception as exc:
        if not _nqe_error_reason(exc, "ENCLOSING_DIR_DOES_NOT_EXIST"):
            raise
        directory_path = query_path.rpartition("/")[0] or "/"
        _ensure_org_directory(client, directory_path, touched_paths=touched_paths)
        client.add_org_nqe_query(query_path=query_path, source_code=source_code)
    touched_paths.append(query_path)


def _draft_change_path(change: dict[str, Any]) -> str:
    path = str(change.get("path") or "").strip()
    if path:
        return path
    for basis_key in ("basis", "editBasis"):
        basis = change.get(basis_key)
        if isinstance(basis, dict):
            path = str(basis.get("path") or "").strip()
            if path:
                return path
    return str(change.get("directory") or "").strip()


def _dry_run_summary(result: dict[str, Any], *, snapshot_id: str) -> dict[str, Any]:
    new_errors = result.get("newErrors") if isinstance(result.get("newErrors"), dict) else {}
    invalid_paths = sorted(path for path, errors in new_errors.items() if errors)
    unauthorized_queries = list(result.get("unauthorizedQueryChanges") or [])
    unauthorized_access = list(result.get("unauthorizedAccessSettingChanges") or [])
    uses = [item for item in (result.get("uses") or []) if isinstance(item, dict)]
    error_uses = [item for item in uses if str(item.get("severity") or "").upper() == "ERROR"]
    passed = not (invalid_paths or unauthorized_queries or unauthorized_access or error_uses)
    return {
        "status": "pass" if passed else "fail",
        "snapshot_id": snapshot_id,
        "snapshot_aware": bool(snapshot_id),
        "invalid_paths": invalid_paths,
        "unauthorized_query_count": len(unauthorized_queries),
        "unauthorized_access_count": len(unauthorized_access),
        "impacted_use_count": len(uses),
        "error_use_count": len(error_uses),
    }


def _discard_touched_drafts(
    client: ForwardClient,
    touched_paths: list[str],
) -> list[str]:
    cleanup_errors: list[str] = []
    for path in reversed(tuple(dict.fromkeys(touched_paths))):
        try:
            client.discard_org_nqe_draft_change(path=path)
        except Exception as exc:  # cleanup evidence must not hide the validation result
            cleanup_errors.append(f"{path}: {type(exc).__name__}")
    return cleanup_errors


def _stage_planned_changes(
    client: ForwardClient,
    planned_changes: list[dict[str, Any]],
    *,
    touched_paths: list[str],
) -> None:
    for change in planned_changes:
        if change["action"] == "add":
            _add_org_query_with_directory_retry(
                client,
                query_path=change["path"],
                source_code=change["source"],
                touched_paths=touched_paths,
            )
        else:
            client.edit_org_nqe_query(
                query_path=change["path"],
                source_code=change["source"],
                query_id=change["query_id"],
                commit_id=change["commit_id"],
            )
            touched_paths.append(change["path"])


def audit_bundled_queries(
    client: ForwardClient,
    *,
    directory: str = DEFAULT_QUERY_DIRECTORY,
) -> dict[str, Any]:
    query_index = client.get_nqe_repository_query_index(repository="org", commit_id="head")
    by_path = query_index.get("by_path", {})
    entries: list[dict[str, str]] = []
    for filename in QUERY_FILENAMES:
        query_path = query_path_from_filename(filename, directory=directory)
        query_entry = by_path.get(query_path)
        if not isinstance(query_entry, dict):
            entries.append({"filename": filename, "path": query_path, "status": "missing"})
            continue
        try:
            committed = _query_basis(
                client,
                query_path=query_path,
                query_entry=query_entry,
            )
        except Exception as exc:  # attribution belongs in the audit report
            entries.append(
                {
                    "filename": filename,
                    "path": query_path,
                    "status": "lookup-failed",
                    "message": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
            continue
        source = _committed_source(committed)
        if not source:
            status = "source-unavailable"
        elif normalize_query_source(source) == normalize_query_source(
            read_bundled_query_source(filename)
        ):
            status = "matched"
        else:
            status = "stale"
        entries.append({"filename": filename, "path": query_path, "status": status})

    counts: dict[str, int] = {}
    for entry in entries:
        status = entry["status"]
        counts[status] = counts.get(status, 0) + 1
    return {
        "status": "pass" if counts.get("matched", 0) == len(QUERY_FILENAMES) else "fail",
        "repository": "org",
        "directory": str(directory),
        "query_count": len(QUERY_FILENAMES),
        "counts": counts,
        "queries": entries,
    }


def publish_bundled_queries(
    client: ForwardClient,
    *,
    directory: str = DEFAULT_QUERY_DIRECTORY,
    overwrite: bool = False,
    commit_message: str = "Publish bundled Forward Nautobot NQE queries",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    query_index = client.get_nqe_repository_query_index(repository="org", commit_id="head")
    existing_by_path = query_index.get("by_path", {})
    changed_paths: list[str] = []
    publication: list[dict[str, str]] = []
    planned_changes: list[dict[str, Any]] = []

    for filename in QUERY_FILENAMES:
        query_path = query_path_from_filename(filename, directory=directory)
        source = read_bundled_query_source(filename)
        existing = existing_by_path.get(query_path)
        if not isinstance(existing, dict):
            changed_paths.append(query_path)
            publication.append({"filename": filename, "path": query_path, "status": "added"})
            planned_changes.append(
                {
                    "action": "add",
                    "path": query_path,
                    "source": source,
                }
            )
            continue

        committed = _query_basis(client, query_path=query_path, query_entry=existing)
        if normalize_query_source(_committed_source(committed)) == normalize_query_source(source):
            publication.append({"filename": filename, "path": query_path, "status": "unchanged"})
            continue
        if not overwrite:
            publication.append({"filename": filename, "path": query_path, "status": "stale"})
            continue
        changed_paths.append(query_path)
        publication.append({"filename": filename, "path": query_path, "status": "updated"})
        planned_changes.append(
            {
                "action": "edit",
                "path": query_path,
                "source": source,
                "query_id": str(committed.get("queryId") or existing.get("queryId") or ""),
                "commit_id": _commit_id(committed),
            }
        )

    commit_id = ""
    dry_run = {
        "status": "not-required",
        "snapshot_id": "",
        "snapshot_aware": False,
        "invalid_paths": [],
        "unauthorized_query_count": 0,
        "unauthorized_access_count": 0,
        "impacted_use_count": 0,
        "error_use_count": 0,
    }
    if changed_paths:
        existing_draft_paths = {
            path
            for change in client.get_org_nqe_draft_changes()
            if (path := _draft_change_path(change))
        }
        conflicting_paths = sorted(set(changed_paths) & existing_draft_paths)
        if conflicting_paths:
            return {
                "status": "fail",
                "repository": "org",
                "directory": str(directory),
                "changed_count": 0,
                "commit_id": "",
                "publication": publication,
                "dry_run": {
                    **dry_run,
                    "status": "blocked-existing-drafts",
                    "conflicting_paths": conflicting_paths,
                },
                "audit": audit_bundled_queries(client, directory=directory),
            }

        touched_paths: list[str] = []
        try:
            _stage_planned_changes(
                client,
                planned_changes,
                touched_paths=touched_paths,
            )
            resolved_snapshot_id = str(snapshot_id or "").strip()
            client_settings = getattr(client, "settings", None)
            network_id = str(getattr(client_settings, "network_id", "") or "").strip()
            if not resolved_snapshot_id and network_id:
                resolved_snapshot_id = client.resolve_snapshot_id(
                    network_id,
                    str(getattr(client_settings, "snapshot_id", "") or ""),
                )
            dry_run = _dry_run_summary(
                client.dry_run_org_nqe_queries(
                    query_paths=changed_paths,
                    snapshot_id=resolved_snapshot_id or None,
                ),
                snapshot_id=resolved_snapshot_id,
            )
        except Exception as exc:
            cleanup_errors = _discard_touched_drafts(client, touched_paths)
            if cleanup_errors:
                raise RuntimeError(
                    "Forward NQE commit dry-run failed and draft cleanup was incomplete: "
                    + "; ".join(cleanup_errors)
                ) from exc
            raise
        if dry_run["status"] != "pass":
            dry_run["cleanup_errors"] = _discard_touched_drafts(client, touched_paths)
            return {
                "status": "fail",
                "repository": "org",
                "directory": str(directory),
                "changed_count": len(changed_paths),
                "commit_id": "",
                "publication": publication,
                "dry_run": dry_run,
                "audit": audit_bundled_queries(client, directory=directory),
            }
        commit_id = client.commit_org_nqe_queries(
            query_paths=changed_paths,
            message=commit_message,
        )
    audit = audit_bundled_queries(client, directory=directory)
    return {
        "status": audit["status"],
        "repository": "org",
        "directory": str(directory),
        "changed_count": len(changed_paths),
        "commit_id": commit_id,
        "publication": publication,
        "dry_run": dry_run,
        "audit": audit,
    }
