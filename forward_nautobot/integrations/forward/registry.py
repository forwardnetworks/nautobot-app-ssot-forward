"""Registry of Forward-to-Nautobot model slices."""

from dataclasses import dataclass

from .exceptions import ForwardConfigurationError


@dataclass(frozen=True, slots=True)
class ForwardModelMapping:
    """A planned model slice for the first Nautobot implementation pass."""

    slug: str
    forward_query_file: str
    description: str
    identity_fields: tuple[str, ...] = ("name",)
    enabled_by_default: bool = True
    nautobot_scope: str = ""


CORE_MODEL_MAPPINGS: tuple[ForwardModelMapping, ...] = (
    ForwardModelMapping(
        slug="locations",
        forward_query_file="forward_locations.nqe",
        description="Forward locations mapped to Nautobot locations/sites.",
        identity_fields=("name",),
        nautobot_scope="dcim.location",
    ),
    ForwardModelMapping(
        slug="platforms",
        forward_query_file="forward_platforms.nqe",
        description="Forward platforms mapped to Nautobot platforms.",
        identity_fields=("name",),
        nautobot_scope="dcim.platform",
    ),
    ForwardModelMapping(
        slug="device_types",
        forward_query_file="forward_device_types.nqe",
        description="Forward device types mapped to Nautobot device types.",
        identity_fields=("name",),
        nautobot_scope="dcim.devicetype",
    ),
    ForwardModelMapping(
        slug="devices",
        forward_query_file="forward_devices.nqe",
        description="Forward devices mapped to Nautobot devices.",
        identity_fields=("name",),
        nautobot_scope="dcim.device",
    ),
    ForwardModelMapping(
        slug="interfaces",
        forward_query_file="forward_interfaces.nqe",
        description="Forward interfaces mapped to Nautobot interfaces.",
        identity_fields=("device", "name"),
        nautobot_scope="dcim.interface",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="vlans",
        forward_query_file="forward_vlans.nqe",
        description="Forward VLANs mapped to Nautobot VLANs.",
        identity_fields=("site", "vid"),
        nautobot_scope="ipam.vlan",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="vrfs",
        forward_query_file="forward_vrfs.nqe",
        description="Forward VRFs mapped to Nautobot VRFs.",
        identity_fields=("name",),
        nautobot_scope="ipam.vrf",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="ipv4_prefixes",
        forward_query_file="forward_prefixes_ipv4.nqe",
        description="Forward IPv4 prefixes mapped to Nautobot prefixes.",
        identity_fields=("prefix", "vrf"),
        nautobot_scope="ipam.prefix",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="ipv6_prefixes",
        forward_query_file="forward_prefixes_ipv6.nqe",
        description="Forward IPv6 prefixes mapped to Nautobot prefixes.",
        identity_fields=("prefix", "vrf"),
        nautobot_scope="ipam.prefix",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="ip_addresses",
        forward_query_file="forward_ip_addresses.nqe",
        description="Forward IP addresses mapped to Nautobot IP addresses.",
        identity_fields=("device", "interface", "address", "vrf"),
        nautobot_scope="ipam.ipaddress",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="inventory_items",
        forward_query_file="forward_inventory_items.nqe",
        description="Forward inventory items mapped to Nautobot inventory items.",
        identity_fields=("device", "name"),
        nautobot_scope="dcim.inventoryitem",
        enabled_by_default=False,
    ),
    ForwardModelMapping(
        slug="modules",
        forward_query_file="forward_modules.nqe",
        description="Forward modules mapped to Nautobot modules.",
        identity_fields=("device", "module_bay"),
        nautobot_scope="dcim.module",
        enabled_by_default=False,
    ),
)


def get_default_model_mappings() -> tuple[ForwardModelMapping, ...]:
    return tuple(mapping for mapping in CORE_MODEL_MAPPINGS if mapping.enabled_by_default)


def get_model_mappings(selected: tuple[str, ...] | list[str] | None = None):
    if not selected:
        return get_default_model_mappings()
    lookup = {mapping.slug: mapping for mapping in CORE_MODEL_MAPPINGS}
    unknown = sorted({name for name in selected if name not in lookup})
    if unknown:
        raise ForwardConfigurationError(
            f"Unknown Forward model slice(s): {', '.join(unknown)}"
        )
    return tuple(lookup[name] for name in selected)
