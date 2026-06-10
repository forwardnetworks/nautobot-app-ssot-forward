from importlib import resources

from forward_nautobot.integrations.forward.queries import QUERY_FILENAMES
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS


def test_bundled_query_filenames_match_registry():
    expected = tuple(mapping.forward_query_file for mapping in CORE_MODEL_MAPPINGS)
    assert QUERY_FILENAMES == expected


def test_bundled_query_files_exist_on_disk():
    package_root = resources.files("forward_nautobot.integrations.forward.queries")
    for filename in QUERY_FILENAMES:
        assert (package_root / filename).is_file(), filename

