from forward_nautobot.integrations.forward.queries import QUERY_CONTRACT_VERSIONS
from forward_nautobot.integrations.forward.queries import QUERY_FILENAMES
from forward_nautobot.integrations.forward.queries import QUERY_CONTRACT_FIELDS
from forward_nautobot.integrations.forward.queries import get_query_contract_field_sets
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS


def test_bundled_query_filenames_match_registry():
    expected = tuple(mapping.forward_query_file for mapping in CORE_MODEL_MAPPINGS)
    assert QUERY_FILENAMES == expected


def test_bundled_query_files_exist_on_disk():
    from importlib import resources

    package_root = resources.files("forward_nautobot.integrations.forward.queries")
    for filename in QUERY_FILENAMES:
        assert (package_root / filename).is_file(), filename


def test_core_query_files_declare_contract_version():
    for mapping in CORE_MODEL_MAPPINGS:
        assert QUERY_CONTRACT_VERSIONS[mapping.forward_query_file] == "v1"


def test_core_query_files_match_expected_contract_fields():
    for mapping in CORE_MODEL_MAPPINGS:
        expected = QUERY_CONTRACT_FIELDS[mapping.forward_query_file]
        field_sets = get_query_contract_field_sets(mapping.forward_query_file)
        assert field_sets, mapping.forward_query_file
        assert all(field_set == expected for field_set in field_sets), mapping.forward_query_file
