"""DiffSync model classes for the first Forward ingestion slices."""

from __future__ import annotations

try:
    from diffsync import DiffSyncModel
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    class DiffSyncModel:  # type: ignore[too-many-ancestors]
        """Fallback model base when DiffSync is not installed."""

        _modelname = ""
        _identifiers: tuple[str, ...] = ()
        _attributes: tuple[str, ...] = ()

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def dict(self) -> dict[str, object]:
            return {
                key: value
                for key, value in self.__dict__.items()
                if not str(key).startswith("_")
            }


class ForwardLocation(DiffSyncModel):
    _modelname = "locations"
    _identifiers = ("name",)
    _attributes = ("city", "country")

    name: str
    city: str = ""
    country: str = ""


class ForwardPlatform(DiffSyncModel):
    _modelname = "platforms"
    _identifiers = ("name",)
    _attributes = ("manufacturer", "device_type")

    name: str
    manufacturer: str = ""
    device_type: str = ""


class ForwardDeviceType(DiffSyncModel):
    _modelname = "device_types"
    _identifiers = ("name",)
    _attributes = ("color",)

    name: str
    color: str = "9e9e9e"


class ForwardDevice(DiffSyncModel):
    _modelname = "devices"
    _identifiers = ("name",)
    _attributes = ("location", "vendor", "model", "device_type")

    name: str
    location: str = ""
    vendor: str = ""
    model: str = ""
    device_type: str = ""


class ForwardInterface(DiffSyncModel):
    _modelname = "interfaces"
    _identifiers = ("device", "name")
    _attributes = (
        "type",
        "lag",
        "mode",
        "untagged_vlan",
        "enabled",
        "mtu",
        "description",
        "speed",
    )

    device: str
    name: str
    type: str = "other"
    lag: str = ""
    mode: str = ""
    untagged_vlan: int | None = None
    enabled: bool = True
    mtu: int | None = None
    description: str = ""
    speed: int | None = None


class ForwardVLAN(DiffSyncModel):
    _modelname = "vlans"
    _identifiers = ("site", "vid")
    _attributes = ("name", "status")

    site: str
    vid: int
    name: str = ""
    status: str = "active"


class ForwardVRF(DiffSyncModel):
    _modelname = "vrfs"
    _identifiers = ("name",)
    _attributes = ("rd", "description", "enforce_unique")

    name: str
    rd: str = ""
    description: str = ""
    enforce_unique: bool = False


class ForwardIPv4Prefix(DiffSyncModel):
    _modelname = "ipv4_prefixes"
    _identifiers = ("prefix", "vrf")
    _attributes = ("status",)

    prefix: str
    vrf: str = ""
    status: str = "active"


class ForwardIPv6Prefix(DiffSyncModel):
    _modelname = "ipv6_prefixes"
    _identifiers = ("prefix", "vrf")
    _attributes = ("status",)

    prefix: str
    vrf: str = ""
    status: str = "active"


class ForwardIPAddress(DiffSyncModel):
    _modelname = "ip_addresses"
    _identifiers = ("device", "interface", "address", "vrf")
    _attributes = ("host_ip", "prefix_length", "status")

    device: str
    interface: str
    vrf: str = ""
    address: str
    host_ip: str = ""
    prefix_length: int | None = None
    status: str = "active"


class ForwardInventoryItem(DiffSyncModel):
    _modelname = "inventory_items"
    _identifiers = ("device", "name")
    _attributes = (
        "manufacturer",
        "label",
        "part_id",
        "serial",
        "asset_tag",
        "role",
        "status",
        "discovered",
        "description",
    )

    device: str
    name: str
    manufacturer: str = ""
    label: str = ""
    part_id: str = ""
    serial: str = ""
    asset_tag: str = ""
    role: str = ""
    status: str = "active"
    discovered: bool = True
    description: str = ""


class ForwardModule(DiffSyncModel):
    _modelname = "modules"
    _identifiers = ("device", "module_bay")
    _attributes = (
        "manufacturer",
        "model",
        "part_number",
        "status",
        "serial",
        "asset_tag",
        "description",
    )

    device: str
    module_bay: str
    manufacturer: str = ""
    model: str = ""
    part_number: str = ""
    status: str = "active"
    serial: str = ""
    asset_tag: str = ""
    description: str = ""
