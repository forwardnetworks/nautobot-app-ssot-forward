"""Bundled Forward query file metadata.

The parsing of NQE source — stripping the saved-query ``@primaryKey`` annotation
for inline execution, and reading the ``@contract-version`` header — is owned by
``forward_sdk.nqe.files`` rather than reimplemented here. This module keeps the
packaging concern: which files ship with the plugin, and reading them out of the
installed package rather than off a filesystem path.
"""

from __future__ import annotations

from importlib import resources

from forward_sdk.nqe.files import contract_version, strip_primary_key

from .contracts import QUERY_CONTRACT_FIELDS
from .contracts import get_bundled_query_contracts as get_bundled_query_contracts
from .contracts import get_query_contract_field_sets as get_query_contract_field_sets
from .contracts import get_query_contract_fields as get_query_contract_fields

QUERY_FILENAMES: tuple[str, ...] = tuple(sorted(QUERY_CONTRACT_FIELDS))


def read_bundled_query_source(filename: str) -> str:
    if filename not in QUERY_FILENAMES:
        raise ValueError(f"Unknown bundled NQE filename: {filename}")
    package_root = resources.files(__name__)
    return (package_root / filename).read_text(encoding="utf-8")


def read_bundled_query_execution_source(filename: str) -> str:
    """Return bundled source accepted by the raw async NQE endpoint.

    ``@primaryKey`` is repository metadata used by saved queries and NQE
    diffs. Inline execution removes only that metadata and runs the same bare
    query expression asynchronously; inline queries cannot use the diff endpoint.
    """
    return strip_primary_key(read_bundled_query_source(filename))


def get_query_contract_version(filename: str) -> str:
    return contract_version(read_bundled_query_source(filename)) or ""


QUERY_CONTRACT_VERSIONS: dict[str, str] = {
    filename: get_query_contract_version(filename) for filename in QUERY_FILENAMES
}
