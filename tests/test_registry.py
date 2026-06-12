from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS
from forward_nautobot.integrations.forward.registry import get_model_mappings
from forward_nautobot.integrations.forward.registry import CORE_MODEL_SLUGS


def test_registry_entries_expose_dispatch_metadata():
    for mapping in CORE_MODEL_MAPPINGS:
        assert mapping.forward_query_file.endswith(".nqe")
        assert mapping.nautobot_scope
        assert mapping.identity_fields
        assert mapping.lookup_strategy
        assert mapping.write_handler
        assert mapping.contract_version == "v1"
        assert isinstance(mapping.depends_on, tuple)
    assert CORE_MODEL_SLUGS == tuple(mapping.slug for mapping in CORE_MODEL_MAPPINGS)
    assert {
        mapping.slug: mapping.query_parameters
        for mapping in CORE_MODEL_MAPPINGS
        if mapping.query_parameters
    } == {
        "platforms": {"forward_location_names": ("locations",)},
        "device_types": {"forward_location_names": ("locations",)},
        "devices": {"forward_location_names": ("locations",)},
        "interfaces": {"forward_device_names": ("devices",)},
        "vlans": {"forward_location_names": ("locations",)},
        "vrfs": {"forward_device_names": ("devices",)},
        "ipv4_prefixes": {"forward_device_names": ("devices",)},
        "ipv6_prefixes": {"forward_device_names": ("devices",)},
        "ip_addresses": {"forward_device_names": ("devices",)},
        "inventory_items": {"forward_device_names": ("devices",)},
        "modules": {"forward_device_names": ("devices",)},
    }


def test_registry_orders_dependencies_before_dependents():
    ordered = get_model_mappings(("locations", "modules", "devices"))
    slugs = [mapping.slug for mapping in ordered]

    assert slugs.index("locations") < slugs.index("devices")
    assert slugs.index("devices") < slugs.index("modules")
