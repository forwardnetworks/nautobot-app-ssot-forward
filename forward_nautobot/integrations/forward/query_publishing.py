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
    return f'"reason":"{reason}"' in str(exc).replace(" ", "")


def _ensure_org_directory(client: ForwardClient, directory_path: str) -> None:
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
        _ensure_org_directory(client, parent)
        client.add_org_nqe_directory(directory_path=normalized)


def _add_org_query_with_directory_retry(
    client: ForwardClient,
    *,
    query_path: str,
    source_code: str,
) -> None:
    try:
        client.add_org_nqe_query(query_path=query_path, source_code=source_code)
    except Exception as exc:
        if not _nqe_error_reason(exc, "ENCLOSING_DIR_DOES_NOT_EXIST"):
            raise
        directory_path = query_path.rpartition("/")[0] or "/"
        _ensure_org_directory(client, directory_path)
        client.add_org_nqe_query(query_path=query_path, source_code=source_code)


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
) -> dict[str, Any]:
    query_index = client.get_nqe_repository_query_index(repository="org", commit_id="head")
    existing_by_path = query_index.get("by_path", {})
    changed_paths: list[str] = []
    publication: list[dict[str, str]] = []

    for filename in QUERY_FILENAMES:
        query_path = query_path_from_filename(filename, directory=directory)
        source = read_bundled_query_source(filename)
        existing = existing_by_path.get(query_path)
        if not isinstance(existing, dict):
            _add_org_query_with_directory_retry(
                client,
                query_path=query_path,
                source_code=source,
            )
            changed_paths.append(query_path)
            publication.append({"filename": filename, "path": query_path, "status": "added"})
            continue

        committed = _query_basis(client, query_path=query_path, query_entry=existing)
        if normalize_query_source(_committed_source(committed)) == normalize_query_source(source):
            publication.append({"filename": filename, "path": query_path, "status": "unchanged"})
            continue
        if not overwrite:
            publication.append({"filename": filename, "path": query_path, "status": "stale"})
            continue
        client.edit_org_nqe_query(
            query_path=query_path,
            source_code=source,
            query_id=str(committed.get("queryId") or existing.get("queryId") or ""),
            commit_id=_commit_id(committed),
        )
        changed_paths.append(query_path)
        publication.append({"filename": filename, "path": query_path, "status": "updated"})

    commit_id = ""
    if changed_paths:
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
        "audit": audit,
    }
