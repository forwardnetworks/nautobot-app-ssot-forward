"""Registry of Forward-to-Nautobot model slices."""

from dataclasses import dataclass, field

from .exceptions import ForwardConfigurationError


@dataclass(frozen=True, slots=True)
class ForwardModelMapping:
    """A planned model slice for the first Nautobot implementation pass."""

    slug: str
    forward_query_file: str
    description: str
    identity_fields: tuple[str, ...] = ("name",)
    contract_version: str = "v1"
    enabled_by_default: bool = True
    nautobot_scope: str = ""
    write_mode: str = "upsert"
    missing_row_policy: str = "ignore"
    dependency_group: str = ""
    depends_on: tuple[str, ...] = ()
    lookup_strategy: str = "name"
    write_handler: str = ""
    query_parameters: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def forward_query_path(self) -> str:
        query_name = str(self.forward_query_file or "").removesuffix(".nqe")
        return f"/forward_nautobot_validation/{query_name}"


CORE_MODEL_MAPPINGS: tuple[ForwardModelMapping, ...] = (
    ForwardModelMapping(
        slug="locations",
        forward_query_file="forward_locations.nqe",
        description="Forward locations mapped to Nautobot locations/sites.",
        identity_fields=("name",),
        nautobot_scope="dcim.location",
        missing_row_policy="mark_inactive",
        dependency_group="core",
        lookup_strategy="name",
        write_handler="_upsert_location",
    ),
    ForwardModelMapping(
        slug="platforms",
        forward_query_file="forward_platforms.nqe",
        description="Forward platforms mapped to Nautobot platforms.",
        identity_fields=("name",),
        nautobot_scope="dcim.platform",
        missing_row_policy="ignore",
        dependency_group="core",
        lookup_strategy="name",
        write_handler="_upsert_platform",
        query_parameters={"forward_location_names": ("locations",)},
    ),
    ForwardModelMapping(
        slug="device_types",
        forward_query_file="forward_device_types.nqe",
        description="Forward device types mapped to Nautobot device types.",
        identity_fields=("name",),
        nautobot_scope="dcim.devicetype",
        missing_row_policy="ignore",
        dependency_group="core",
        lookup_strategy="device_type",
        write_handler="_upsert_device_type",
        query_parameters={"forward_location_names": ("locations",)},
    ),
    ForwardModelMapping(
        slug="devices",
        forward_query_file="forward_devices.nqe",
        description="Forward devices mapped to Nautobot devices.",
        identity_fields=("name",),
        nautobot_scope="dcim.device",
        missing_row_policy="mark_inactive",
        dependency_group="core",
        depends_on=("locations", "platforms", "device_types"),
        lookup_strategy="name",
        write_handler="_upsert_device",
        query_parameters={"forward_location_names": ("locations",)},
    ),
    ForwardModelMapping(
        slug="interfaces",
        forward_query_file="forward_interfaces.nqe",
        description="Forward interfaces mapped to Nautobot interfaces.",
        identity_fields=("device", "name"),
        nautobot_scope="dcim.interface",
        enabled_by_default=False,
        missing_row_policy="mark_inactive",
        dependency_group="core",
        depends_on=("devices",),
        lookup_strategy="device_interface",
        write_handler="_upsert_interface",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="vlans",
        forward_query_file="forward_vlans.nqe",
        description="Forward VLANs mapped to Nautobot VLANs.",
        identity_fields=("site", "vid"),
        nautobot_scope="ipam.vlan",
        enabled_by_default=False,
        missing_row_policy="mark_inactive",
        dependency_group="ipam",
        depends_on=("locations",),
        lookup_strategy="location_vid",
        write_handler="_upsert_vlan",
        query_parameters={"forward_location_names": ("locations",)},
    ),
    ForwardModelMapping(
        slug="vrfs",
        forward_query_file="forward_vrfs.nqe",
        description="Forward VRFs mapped to Nautobot VRFs.",
        identity_fields=("name",),
        nautobot_scope="ipam.vrf",
        enabled_by_default=False,
        missing_row_policy="ignore",
        dependency_group="ipam",
        depends_on=("devices",),
        lookup_strategy="name",
        write_handler="_upsert_vrf",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="ipv4_prefixes",
        forward_query_file="forward_prefixes_ipv4.nqe",
        description="Forward IPv4 prefixes mapped to Nautobot prefixes.",
        identity_fields=("prefix", "vrf"),
        nautobot_scope="ipam.prefix",
        enabled_by_default=False,
        missing_row_policy="ignore",
        dependency_group="ipam",
        depends_on=("vrfs",),
        lookup_strategy="prefix_vrf",
        write_handler="_upsert_prefix",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="ipv6_prefixes",
        forward_query_file="forward_prefixes_ipv6.nqe",
        description="Forward IPv6 prefixes mapped to Nautobot prefixes.",
        identity_fields=("prefix", "vrf"),
        nautobot_scope="ipam.prefix",
        enabled_by_default=False,
        missing_row_policy="ignore",
        dependency_group="ipam",
        depends_on=("vrfs",),
        lookup_strategy="prefix_vrf",
        write_handler="_upsert_prefix",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="ip_addresses",
        forward_query_file="forward_ip_addresses.nqe",
        description="Forward IP addresses mapped to Nautobot IP addresses.",
        identity_fields=("device", "interface", "address", "vrf"),
        nautobot_scope="ipam.ipaddress",
        enabled_by_default=False,
        missing_row_policy="ignore",
        dependency_group="ipam",
        depends_on=("devices", "interfaces", "vrfs"),
        lookup_strategy="device_interface_address_vrf",
        write_handler="_upsert_ip_address",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="inventory_items",
        forward_query_file="forward_inventory_items.nqe",
        description="Forward inventory items mapped to Nautobot inventory items.",
        identity_fields=("device", "name"),
        nautobot_scope="dcim.inventoryitem",
        enabled_by_default=False,
        missing_row_policy="mark_inactive",
        dependency_group="assets",
        depends_on=("devices",),
        lookup_strategy="device_name",
        write_handler="_resolve_inventory_item",
        query_parameters={"forward_device_names": ("devices",)},
    ),
    ForwardModelMapping(
        slug="modules",
        forward_query_file="forward_modules.nqe",
        description="Forward modules mapped to Nautobot modules.",
        identity_fields=("device", "module_bay"),
        nautobot_scope="dcim.module",
        enabled_by_default=False,
        missing_row_policy="mark_inactive",
        dependency_group="assets",
        depends_on=("devices",),
        lookup_strategy="device_module_bay",
        write_handler="_resolve_module",
        query_parameters={"forward_device_names": ("devices",)},
    ),
)

CORE_MODEL_LOOKUP: dict[str, ForwardModelMapping] = {
    mapping.slug: mapping for mapping in CORE_MODEL_MAPPINGS
}
CORE_MODEL_SLUGS: tuple[str, ...] = tuple(CORE_MODEL_LOOKUP)


def get_default_model_mappings() -> tuple[ForwardModelMapping, ...]:
    return tuple(mapping for mapping in CORE_MODEL_MAPPINGS if mapping.enabled_by_default)


def get_model_mapping(slug: str) -> ForwardModelMapping:
    model_slug = str(slug or "").strip()
    if model_slug not in CORE_MODEL_LOOKUP:
        raise ForwardConfigurationError(f"Unknown Forward model slice: {model_slug}")
    return CORE_MODEL_LOOKUP[model_slug]


def _topologically_ordered_model_mappings(
    selected: tuple[str, ...] | list[str] | None = None,
) -> tuple[ForwardModelMapping, ...]:
    if not selected:
        return get_default_model_mappings()
    selected_names = tuple(
        dict.fromkeys(str(item).strip() for item in selected if str(item).strip())
    )
    unknown = sorted({name for name in selected_names if name not in CORE_MODEL_LOOKUP})
    if unknown:
        raise ForwardConfigurationError(f"Unknown Forward model slice(s): {', '.join(unknown)}")

    selected_set = set(selected_names)
    ordered: list[ForwardModelMapping] = []
    permanent: set[str] = set()
    visiting: set[str] = set()

    def visit(slug: str):
        if slug in permanent:
            return
        if slug in visiting:
            raise ForwardConfigurationError(f"Forward model dependency cycle detected at `{slug}`.")
        visiting.add(slug)
        mapping = CORE_MODEL_LOOKUP[slug]
        for dependency in mapping.depends_on:
            if dependency in selected_set:
                visit(dependency)
        visiting.remove(slug)
        permanent.add(slug)
        ordered.append(mapping)

    for name in selected_names:
        visit(name)
    return tuple(ordered)


def get_model_mappings(selected: tuple[str, ...] | list[str] | None = None):
    return _topologically_ordered_model_mappings(selected)
