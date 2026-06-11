"""Bundled query contract diff helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import run
from typing import Any

from .queries import QUERY_CONTRACT_FIELDS
from .queries import QUERY_CONTRACT_VERSIONS
from .queries import QUERY_FILENAMES
from .queries import get_query_contract_field_sets


@dataclass(slots=True)
class ContractSnapshot:
    """A concrete snapshot of bundled query contracts."""

    source: str
    contracts: dict[str, dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "contracts": dict(self.contracts)}


@dataclass(slots=True)
class ContractDiffEntry:
    """A single contract change."""

    filename: str
    change_type: str
    current: dict[str, Any]
    baseline: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "change_type": self.change_type,
            "current": dict(self.current),
            "baseline": dict(self.baseline),
        }


@dataclass(slots=True)
class ContractDiffReport:
    """Diff report between bundled query contracts."""

    current: ContractSnapshot
    baseline: ContractSnapshot
    entries: tuple[ContractDiffEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "current": self.current.as_dict(),
            "baseline": self.baseline.as_dict(),
            "entries": [entry.as_dict() for entry in self.entries],
            "changed_files": [entry.filename for entry in self.entries],
        }


def snapshot_current_contracts() -> ContractSnapshot:
    return ContractSnapshot(
        source="current",
        contracts={
            filename: {
                "contract_version": QUERY_CONTRACT_VERSIONS[filename],
                "fields": tuple(get_query_contract_field_sets(filename)[0]),
            }
            for filename in QUERY_FILENAMES
        },
    )


def snapshot_contracts_from_text(source: str, query_texts: dict[str, str]) -> ContractSnapshot:
    contracts: dict[str, dict[str, Any]] = {}
    for filename in QUERY_FILENAMES:
        contents = query_texts.get(filename, "")
        field_sets = get_query_contract_field_sets_from_text(contents)
        contracts[filename] = {
            "contract_version": _extract_contract_version(contents),
            "fields": tuple(field_sets[0]) if field_sets else (),
        }
    return ContractSnapshot(source=source, contracts=contracts)


def snapshot_contracts_from_git_ref(ref: str, repo_root: Path | None = None) -> ContractSnapshot:
    repo_root = repo_root or Path(__file__).resolve().parents[3]
    query_texts: dict[str, str] = {}
    for filename in QUERY_FILENAMES:
        relative_path = f"forward_nautobot/integrations/forward/queries/{filename}"
        result = run(
            ["git", "-C", str(repo_root), "show", f"{ref}:{relative_path}"],
            check=False,
            capture_output=True,
            text=True,
        )
        query_texts[filename] = result.stdout if result.returncode == 0 else ""
    return snapshot_contracts_from_text(source=ref, query_texts=query_texts)


def diff_contract_snapshots(
    current: ContractSnapshot, baseline: ContractSnapshot
) -> ContractDiffReport:
    entries: list[ContractDiffEntry] = []
    for filename in QUERY_FILENAMES:
        current_contract = current.contracts.get(filename, {})
        baseline_contract = baseline.contracts.get(filename, {})
        if current_contract != baseline_contract:
            change_type = "modified"
            if not baseline_contract:
                change_type = "added"
            elif not current_contract:
                change_type = "removed"
            entries.append(
                ContractDiffEntry(
                    filename=filename,
                    change_type=change_type,
                    current=current_contract,
                    baseline=baseline_contract,
                )
            )
    return ContractDiffReport(current=current, baseline=baseline, entries=tuple(entries))


def _extract_contract_version(query_text: str) -> str:
    for line in query_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("* @contract-version"):
            return stripped.split()[-1]
    return ""


def get_query_contract_field_sets_from_text(query_text: str) -> tuple[tuple[str, ...], ...]:
    field_sets: list[tuple[str, ...]] = []
    inside_select = False
    current_fields: list[str] = []
    for raw_line in query_text.splitlines():
        line = raw_line.strip().rstrip(",")
        if not line:
            continue
        if line.startswith("select"):
            inside_select = True
            current_fields = []
            continue
        if inside_select and line.startswith("};"):
            if current_fields:
                field_sets.append(tuple(current_fields))
            inside_select = False
            current_fields = []
            continue
        if inside_select:
            if ":" in line and not line.startswith("@"):
                field_name = line.split(":", 1)[0].strip()
                if field_name and field_name[0].isalpha():
                    current_fields.append(field_name)
    if current_fields:
        field_sets.append(tuple(current_fields))
    return tuple(field_sets)

