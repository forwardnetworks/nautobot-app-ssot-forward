"""Bundled Forward query file metadata."""

from __future__ import annotations

import re
from importlib import resources

from .contracts import QUERY_CONTRACT_FIELDS
from .contracts import get_bundled_query_contracts as get_bundled_query_contracts
from .contracts import get_query_contract_field_sets as get_query_contract_field_sets
from .contracts import get_query_contract_fields as get_query_contract_fields

QUERY_FILENAMES: tuple[str, ...] = tuple(sorted(QUERY_CONTRACT_FIELDS))

_CONTRACT_VERSION_PATTERN = re.compile(r"@contract-version\s+([^\s*]+)")
_PRIMARY_KEY_ANNOTATION_PATTERN = re.compile(
    r"^[ \t]*@primaryKey\([^\n]*\)[ \t]*\r?\n",
    flags=re.MULTILINE,
)


def read_bundled_query_source(filename: str) -> str:
    if filename not in QUERY_FILENAMES:
        raise ValueError(f"Unknown bundled NQE filename: {filename}")
    package_root = resources.files(__name__)
    return (package_root / filename).read_text(encoding="utf-8")


def read_bundled_query_execution_source(filename: str) -> str:
    """Return bundled source accepted by the raw async NQE endpoint.

    ``@primaryKey`` is repository metadata used by saved queries and NQE diffs.
    Inline execution removes only that metadata and runs the same bare query
    expression asynchronously; inline queries cannot use the diff endpoint.
    """
    return _PRIMARY_KEY_ANNOTATION_PATTERN.sub("", read_bundled_query_source(filename))


def get_query_contract_version(filename: str) -> str:
    contents = read_bundled_query_source(filename)
    match = _CONTRACT_VERSION_PATTERN.search(contents)
    return match.group(1) if match else ""


QUERY_CONTRACT_VERSIONS: dict[str, str] = {
    filename: get_query_contract_version(filename) for filename in QUERY_FILENAMES
}
