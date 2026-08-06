from forward_nautobot.integrations.forward.queries import (
    QUERY_CONTRACT_FIELDS,
    QUERY_CONTRACT_VERSIONS,
    QUERY_FILENAMES,
    get_query_contract_field_sets,
    read_bundled_query_execution_source,
    read_bundled_query_source,
)
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS


def test_bundled_query_filenames_match_registry():
    expected = tuple(sorted(QUERY_CONTRACT_FIELDS))
    assert QUERY_FILENAMES == expected


def test_bundled_query_files_exist_on_disk():
    from importlib import resources

    package_root = resources.files("forward_nautobot.integrations.forward.queries")
    for filename in QUERY_FILENAMES:
        assert (package_root / filename).is_file(), filename


def test_inline_execution_source_only_removes_repository_primary_key_metadata():
    saved_source = read_bundled_query_source("forward_devices.nqe")
    execution_source = read_bundled_query_execution_source("forward_devices.nqe")

    assert "@primaryKey(name)" in saved_source
    assert "@primaryKey" not in execution_source
    assert "@query" not in execution_source
    assert "forward_vendors" not in execution_source
    assert execution_source == saved_source.replace("\n@primaryKey(name)", "")


def test_all_saved_queries_are_unparameterized_primary_keyed_diff_contracts():
    for filename in QUERY_FILENAMES:
        saved_source = read_bundled_query_source(filename)
        execution_source = read_bundled_query_execution_source(filename)

        assert saved_source.count("@primaryKey(") == 1, filename
        assert "@query" not in saved_source, filename
        assert "@primaryKey" not in execution_source, filename
        assert not execution_source.rstrip().endswith(";"), filename


def test_core_query_files_declare_contract_version():
    for mapping in CORE_MODEL_MAPPINGS:
        assert QUERY_CONTRACT_VERSIONS[mapping.forward_query_file] == mapping.contract_version


def test_core_query_files_match_expected_contract_fields():
    for mapping in CORE_MODEL_MAPPINGS:
        expected = QUERY_CONTRACT_FIELDS[mapping.forward_query_file]
        field_sets = get_query_contract_field_sets(mapping.forward_query_file)
        assert field_sets, mapping.forward_query_file
        assert expected in field_sets, mapping.forward_query_file
