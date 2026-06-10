"""Bundled Forward query file metadata."""

from ..registry import CORE_MODEL_MAPPINGS

QUERY_FILENAMES: tuple[str, ...] = tuple(
    mapping.forward_query_file for mapping in CORE_MODEL_MAPPINGS
)

