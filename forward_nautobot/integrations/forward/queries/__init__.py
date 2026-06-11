"""Bundled Forward query file metadata."""

from __future__ import annotations

import re
from importlib import resources

from ..registry import CORE_MODEL_MAPPINGS
from .contracts import QUERY_CONTRACT_FIELDS
from .contracts import get_bundled_query_contracts
from .contracts import get_query_contract_field_sets
from .contracts import get_query_contract_fields

QUERY_FILENAMES: tuple[str, ...] = tuple(
    mapping.forward_query_file for mapping in CORE_MODEL_MAPPINGS
)

_CONTRACT_VERSION_PATTERN = re.compile(r"@contract-version\s+([^\s*]+)")


def get_query_contract_version(filename: str) -> str:
    package_root = resources.files(__name__)
    contents = (package_root / filename).read_text(encoding="utf-8")
    match = _CONTRACT_VERSION_PATTERN.search(contents)
    return match.group(1) if match else ""


QUERY_CONTRACT_VERSIONS: dict[str, str] = {
    filename: get_query_contract_version(filename) for filename in QUERY_FILENAMES
}
