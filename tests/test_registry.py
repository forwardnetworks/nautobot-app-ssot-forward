from forward_nautobot.integrations.forward.registry import (
    CORE_MODEL_MAPPINGS,
    CORE_MODEL_SLUGS,
    get_model_mappings,
)


def test_registry_entries_expose_dispatch_metadata():
    for mapping in CORE_MODEL_MAPPINGS:
        assert mapping.forward_query_file.endswith(".nqe")
        assert mapping.nautobot_scope
        assert mapping.identity_fields
        assert mapping.lookup_strategy
        assert mapping.write_handler
        assert mapping.contract_version in {"v1", "v2"}
        assert isinstance(mapping.depends_on, tuple)
    assert CORE_MODEL_SLUGS == tuple(mapping.slug for mapping in CORE_MODEL_MAPPINGS)
    assert {
        mapping.slug for mapping in CORE_MODEL_MAPPINGS if mapping.supports_device_filters
    } == set(CORE_MODEL_SLUGS)
    assert not any(mapping.query_parameters for mapping in CORE_MODEL_MAPPINGS)


def test_registry_orders_dependencies_before_dependents():
    ordered = get_model_mappings(("locations", "modules", "devices"))
    slugs = [mapping.slug for mapping in ordered]

    assert slugs.index("locations") < slugs.index("devices")
    assert slugs.index("devices") < slugs.index("modules")
