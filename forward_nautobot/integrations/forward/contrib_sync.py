"""DiffSync/NautobotModel CRUD redesign — contrib write path.

De-risking + build-out for the redesign in
docs/03_Plans/active/2026-06-23-diffsync-crud-redesign.md. Writes flow through
the standard nautobot-ssot ``contrib`` path: source rows populate
``NautobotModel`` subclasses, then ``source.sync_to(target)`` applies create/
update/delete via framework CRUD (no hand-rolled write_executor).

Phase 1: locations. Phase 2: manufacturers, platforms, device_types, devices —
the full device FK chain, all resolved by lookup (contrib never get_or_creates
FK targets, so dependent objects are synced first via ``top_level`` order and
Role/Status/LocationType are ensured up front).

Two behaviors moved out of the writer to satisfy contrib:
- Location dedup happens in the SOURCE (one canonical row per physical site),
  and a shared LocationCanonicalizer maps every device's raw location string to
  that same canonical name so the FK lookup resolves.
- Manufacturer/Platform/DeviceType are DERIVED from device rows (which carry
  vendor/model/device_type together); the standalone platforms/device_types NQE
  slices lack a manufacturer and cannot form a valid identity alone.

Imports safely when nautobot-ssot/Django are unavailable (unit/CI): CONTRIB_AVAILABLE
is False and no model/adapter classes are defined. Exercised by the live WF smoke
on a real Nautobot, not the DB-less unit suite.
"""

from __future__ import annotations

from typing import Any

from .normalize import normalize_location_key

try:
    from diffsync import Adapter
    from django.contrib.contenttypes.models import ContentType
    from nautobot.cloud.models import CloudAccount, CloudNetwork, CloudResourceType, CloudService
    from nautobot.dcim.choices import InterfaceTypeChoices
    from nautobot.dcim.models import (
        Device,
        DeviceType,
        Interface,
        InventoryItem,
        Location,
        LocationType,
        Manufacturer,
        Module,
        ModuleBay,
        ModuleType,
        Platform,
    )
    from nautobot.extras.models import Role, Status
    from nautobot.ipam.models import VLAN, VRF, IPAddress, Namespace, Prefix
    from nautobot_ssot.contrib import NautobotAdapter, NautobotModel

    CONTRIB_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only in a real Nautobot env
    CONTRIB_AVAILABLE = False


# Provider Manufacturer names per Forward cloudType (readable, stable).
_CLOUD_PROVIDER_NAMES = {
    "AWS": "Amazon Web Services",
    "AZURE": "Microsoft Azure",
    "GCP": "Google Cloud Platform",
    "IBM": "IBM Cloud",
}


def _cloud_type_key(cloud_type: str) -> str:
    """Normalize a Forward cloudType to its bare key.

    Forward's toString yields e.g. "CloudType.AWS"; strip the enum prefix so the
    provider map keys ("AWS"/"AZURE"/"GCP") match.
    """
    return str(cloud_type or "").strip().split(".")[-1].upper()


def cloud_provider_name(cloud_type: str) -> str:
    key = _cloud_type_key(cloud_type)
    return _CLOUD_PROVIDER_NAMES.get(key, key or "Cloud")


def cloud_resource_type_name(cloud_type: str, kind: str) -> str:
    """Readable CloudResourceType name, e.g. 'CloudType.AWS' vpc -> 'AWS VPC'."""
    ct = _cloud_type_key(cloud_type)
    pretty = {
        "vpc": "VPC",
        "subnet": "Subnet",
        "load-balancer": "Load Balancer",
        "nat-gateway": "NAT Gateway",
    }.get(str(kind or "").strip(), str(kind or "").strip())
    return f"{ct} {pretty}".strip()


class _ForwardContribDeleteMixin:
    """Skip ORM deletes unless the target adapter opts in (``allow_delete=True``).

    contrib ``source.sync_to(target)`` delete-reconciles the whole target table:
    any object the source lacks would be deleted. Since the plugin imports a
    scoped subset, that default would wipe Nautobot objects it does not manage.
    Defaulting deletes off makes every contrib runner create/update-safe; deletes
    are opt-in once delete scoping (a managed-object filter) is in place.
    """

    def delete(self):
        if not getattr(self.adapter, "allow_delete", False):
            return self
        return super().delete()


class LocationCanonicalizer:
    """Map raw Forward location strings to one canonical name per physical site.

    Formatting variants ("...30TH ST..." vs "...30TH STREET...") share a
    normalized key; the first-seen raw name for a key wins and is reused for the
    Location and for every device that references any variant of that site, so
    contrib's FK-by-lookup resolves consistently.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    def add(self, raw: str) -> None:
        name = str(raw or "").strip()
        key = normalize_location_key(name)
        if key and key not in self._by_key:
            self._by_key[key] = name

    def canonical(self, raw: str) -> str:
        name = str(raw or "").strip()
        key = normalize_location_key(name)
        return self._by_key.get(key, name)

    @property
    def names(self) -> list[str]:
        return list(self._by_key.values())


if CONTRIB_AVAILABLE:

    class ForwardContribManufacturer(_ForwardContribDeleteMixin, NautobotModel):
        _model = Manufacturer
        _modelname = "manufacturer"
        _identifiers = ("name",)
        _attributes = ()
        name: str

    class ForwardContribLocation(_ForwardContribDeleteMixin, NautobotModel):
        _model = Location
        _modelname = "location"
        _identifiers = ("name",)
        _attributes = ("location_type__name", "status__name")
        name: str
        location_type__name: str
        status__name: str

    class ForwardContribPlatform(_ForwardContribDeleteMixin, NautobotModel):
        _model = Platform
        _modelname = "platform"
        _identifiers = ("name",)
        _attributes = ("manufacturer__name",)
        name: str
        manufacturer__name: str

    class ForwardContribDeviceType(_ForwardContribDeleteMixin, NautobotModel):
        _model = DeviceType
        _modelname = "device_type"
        _identifiers = ("manufacturer__name", "model")
        _attributes = ()
        manufacturer__name: str
        model: str

    class ForwardContribDevice(_ForwardContribDeleteMixin, NautobotModel):
        _model = Device
        _modelname = "device"
        _identifiers = ("name",)
        _attributes = (
            "location__name",
            "role__name",
            "status__name",
            "device_type__manufacturer__name",
            "device_type__model",
            "platform__name",
        )
        name: str
        location__name: str
        role__name: str
        status__name: str
        device_type__manufacturer__name: str
        device_type__model: str
        platform__name: str

    class ForwardContribInterface(_ForwardContribDeleteMixin, NautobotModel):
        _model = Interface
        _modelname = "interface"
        _identifiers = ("device__name", "name")
        _attributes = ("type", "status__name", "enabled", "mtu", "description", "mac_address")
        device__name: str
        name: str
        type: str
        status__name: str
        enabled: bool = True
        mtu: int | None = None
        description: str = ""
        # Nautobot's MACAddressCharField stores an absent MAC as NULL, so the
        # contrib field must be Optional — a plain str annotation makes the target
        # adapter raise when it loads a MAC-less interface (None for a str field).
        mac_address: str | None = None

    # Dependency order: FK targets must be created before the objects that
    # reference them, since contrib resolves FKs by lookup.
    _CORE_TOP_LEVEL = [
        "manufacturer",
        "location",
        "platform",
        "device_type",
        "device",
        "interface",
    ]

    # Nautobot Interface.type is a choice field; validate against the real choice
    # set (not a hand-maintained subset) and fall back to "other" for anything
    # Forward emits that Nautobot does not model.
    _INTERFACE_TYPE_FALLBACK = "other"
    _KNOWN_INTERFACE_TYPES = set(InterfaceTypeChoices.values())

    class ForwardContribCoreTarget(NautobotAdapter):
        top_level = _CORE_TOP_LEVEL
        manufacturer = ForwardContribManufacturer
        location = ForwardContribLocation
        platform = ForwardContribPlatform
        device_type = ForwardContribDeviceType
        device = ForwardContribDevice
        interface = ForwardContribInterface

    class ForwardContribCoreSource(Adapter):
        top_level = _CORE_TOP_LEVEL
        manufacturer = ForwardContribManufacturer
        location = ForwardContribLocation
        platform = ForwardContribPlatform
        device_type = ForwardContribDeviceType
        device = ForwardContribDevice
        interface = ForwardContribInterface

        def __init__(
            self,
            *,
            location_rows: list[dict[str, Any]],
            device_rows: list[dict[str, Any]],
            canonicalizer: LocationCanonicalizer,
            location_type_name: str,
            location_status_name: str,
            device_role_name: str,
            device_status_name: str,
            interface_rows: list[dict[str, Any]] | None = None,
            interface_status_name: str = "Active",
            **kwargs,
        ):
            super().__init__(**kwargs)
            self._location_rows = location_rows
            self._device_rows = device_rows
            self._canon = canonicalizer
            self._location_type_name = location_type_name
            self._location_status_name = location_status_name
            self._device_role_name = device_role_name
            self._device_status_name = device_status_name
            self._interface_rows = interface_rows or []
            self._interface_status_name = interface_status_name

        def load(self):
            # Manufacturers / platforms / device_types are derived from device
            # rows (they carry vendor/model/device_type together).
            manufacturers: set[str] = set()
            platforms: dict[str, str] = {}
            device_types: set[tuple[str, str]] = set()

            for row in self._device_rows:
                vendor = str(row.get("vendor") or "").strip()
                model = str(row.get("model") or "").strip()
                dtype = str(row.get("device_type") or "").strip()
                if vendor:
                    manufacturers.add(vendor)
                if model and vendor:
                    platforms.setdefault(model, vendor)
                if vendor and dtype:
                    device_types.add((vendor, dtype))

            for name in sorted(manufacturers):
                self.add(ForwardContribManufacturer(name=name))

            # One Location per physical site, named by the canonicalizer.
            for name in self._canon.names:
                self.add(
                    ForwardContribLocation(
                        name=name,
                        location_type__name=self._location_type_name,
                        status__name=self._location_status_name,
                    )
                )

            for model, vendor in sorted(platforms.items()):
                self.add(ForwardContribPlatform(name=model, manufacturer__name=vendor))

            for vendor, dtype in sorted(device_types):
                self.add(ForwardContribDeviceType(manufacturer__name=vendor, model=dtype))

            seen_devices: set[str] = set()
            for row in self._device_rows:
                name = str(row.get("name") or "").strip()
                vendor = str(row.get("vendor") or "").strip()
                model = str(row.get("model") or "").strip()
                dtype = str(row.get("device_type") or "").strip()
                location = self._canon.canonical(row.get("location") or "")
                # Skip rows missing a required identity/FK so contrib lookups do
                # not blow up; incomplete devices are not synced.
                if not (name and vendor and model and dtype and location):
                    continue
                if name in seen_devices:
                    continue
                seen_devices.add(name)
                self.add(
                    ForwardContribDevice(
                        name=name,
                        location__name=location,
                        role__name=self._device_role_name,
                        status__name=self._device_status_name,
                        device_type__manufacturer__name=vendor,
                        device_type__model=dtype,
                        platform__name=model,
                    )
                )

            # Interfaces — only for devices that were synced (FK target exists).
            seen_ifaces: set[tuple[str, str]] = set()
            for row in self._interface_rows:
                dev = str(row.get("device") or "").strip()
                iname = str(row.get("name") or "").strip()
                if not (dev and iname) or dev not in seen_devices:
                    continue
                key = (dev, iname)
                if key in seen_ifaces:
                    continue
                seen_ifaces.add(key)
                itype = str(row.get("type") or "").strip().lower()
                if itype not in _KNOWN_INTERFACE_TYPES:
                    itype = _INTERFACE_TYPE_FALLBACK
                mtu = row.get("mtu")
                # Use None (not "") for an absent MAC so it matches Nautobot's NULL
                # storage and does not churn; only pass a value that looks like a MAC.
                raw_mac = str(row.get("mac_address") or "").strip()
                mac = raw_mac if ":" in raw_mac else None
                self.add(
                    ForwardContribInterface(
                        device__name=dev,
                        name=iname,
                        type=itype,
                        status__name=self._interface_status_name,
                        enabled=bool(row.get("enabled", True)),
                        mtu=int(mtu) if isinstance(mtu, int) else None,
                        description=str(row.get("description") or ""),
                        mac_address=mac,
                    )
                )

    class ForwardContribCloudAccount(_ForwardContribDeleteMixin, NautobotModel):
        _model = CloudAccount
        _modelname = "cloud_account"
        _identifiers = ("name",)
        _attributes = ("account_number", "provider__name")
        name: str
        account_number: str
        provider__name: str

    class ForwardContribCloudVPC(_ForwardContribDeleteMixin, NautobotModel):
        # Top-level cloud networks (VPCs/VNets). Disjoint queryset (parent IS NULL)
        # from subnets so the two share _model=CloudNetwork without colliding.
        _model = CloudNetwork
        _modelname = "cloud_vpc"
        _identifiers = ("name",)
        _attributes = ("cloud_resource_type__name", "cloud_account__name")
        name: str
        cloud_resource_type__name: str
        cloud_account__name: str

        @classmethod
        def get_queryset(cls):
            return CloudNetwork.objects.filter(parent__isnull=True)

    class ForwardContribCloudSubnet(_ForwardContribDeleteMixin, NautobotModel):
        # Child cloud networks (subnets), parented to their VPC. Synced after VPCs
        # so the parent FK resolves by lookup.
        _model = CloudNetwork
        _modelname = "cloud_subnet"
        _identifiers = ("name",)
        _attributes = ("cloud_resource_type__name", "cloud_account__name", "parent__name")
        name: str
        cloud_resource_type__name: str
        cloud_account__name: str
        parent__name: str

        @classmethod
        def get_queryset(cls):
            return CloudNetwork.objects.filter(parent__isnull=False)

    class ForwardContribCloudService(_ForwardContribDeleteMixin, NautobotModel):
        _model = CloudService
        _modelname = "cloud_service"
        _identifiers = ("name",)
        _attributes = ("cloud_resource_type__name", "cloud_account__name")
        name: str
        cloud_resource_type__name: str
        cloud_account__name: str

    _CLOUD_TOP_LEVEL = ["cloud_account", "cloud_vpc", "cloud_subnet", "cloud_service"]

    class ForwardContribCloudTarget(NautobotAdapter):
        top_level = _CLOUD_TOP_LEVEL
        cloud_account = ForwardContribCloudAccount
        cloud_vpc = ForwardContribCloudVPC
        cloud_subnet = ForwardContribCloudSubnet
        cloud_service = ForwardContribCloudService

    class ForwardContribCloudSource(Adapter):
        top_level = _CLOUD_TOP_LEVEL
        cloud_account = ForwardContribCloudAccount
        cloud_vpc = ForwardContribCloudVPC
        cloud_subnet = ForwardContribCloudSubnet
        cloud_service = ForwardContribCloudService

        def __init__(
            self,
            *,
            account_rows: list[dict[str, Any]],
            network_rows: list[dict[str, Any]],
            service_rows: list[dict[str, Any]],
            **kwargs,
        ):
            super().__init__(**kwargs)
            self._account_rows = account_rows
            self._network_rows = network_rows
            self._service_rows = service_rows

        def load(self):
            # Map account id -> account name so network/service rows (which carry
            # only account_id) can reference the account by name for the FK lookup.
            account_name_by_id: dict[str, str] = {}
            seen_accounts: set[str] = set()
            for row in self._account_rows:
                acct_id = str(row.get("account_id") or "").strip()
                name = str(row.get("name") or "").strip() or acct_id
                cloud_type = str(row.get("cloud_type") or "").strip()
                if not acct_id or name in seen_accounts:
                    continue
                seen_accounts.add(name)
                account_name_by_id[acct_id] = name
                self.add(
                    ForwardContribCloudAccount(
                        name=name,
                        account_number=acct_id,
                        provider__name=cloud_provider_name(cloud_type),
                    )
                )

            # Forward network id -> Nautobot CloudNetwork name, so a subnet can
            # reference its parent VPC by name (rows carry the parent's Forward id).
            name_by_network_id: dict[str, str] = {}
            for row in self._network_rows:
                nid = str(row.get("network_id") or "").strip()
                nm = str(row.get("name") or "").strip()
                if nid and nm:
                    name_by_network_id.setdefault(nid, nm)

            seen_networks: set[str] = set()
            for row in self._network_rows:
                name = str(row.get("name") or "").strip()
                acct_id = str(row.get("account_id") or "").strip()
                cloud_type = str(row.get("cloud_type") or "").strip()
                kind = str(row.get("kind") or "vpc").strip()
                account_name = account_name_by_id.get(acct_id)
                if not (name and account_name) or name in seen_networks:
                    continue
                seen_networks.add(name)
                rtype = cloud_resource_type_name(cloud_type, kind)
                if kind == "subnet":
                    parent_name = name_by_network_id.get(str(row.get("parent_id") or "").strip())
                    if not parent_name:
                        continue  # orphan subnet (parent VPC not in the set) — skip
                    self.add(
                        ForwardContribCloudSubnet(
                            name=name,
                            cloud_resource_type__name=rtype,
                            cloud_account__name=account_name,
                            parent__name=parent_name,
                        )
                    )
                else:
                    self.add(
                        ForwardContribCloudVPC(
                            name=name,
                            cloud_resource_type__name=rtype,
                            cloud_account__name=account_name,
                        )
                    )

            seen_services: set[str] = set()
            for row in self._service_rows:
                name = str(row.get("name") or "").strip()
                acct_id = str(row.get("account_id") or "").strip()
                cloud_type = str(row.get("cloud_type") or "").strip()
                kind = str(row.get("service_kind") or "").strip()
                account_name = account_name_by_id.get(acct_id)
                if not (name and account_name) or name in seen_services:
                    continue
                seen_services.add(name)
                self.add(
                    ForwardContribCloudService(
                        name=name,
                        cloud_resource_type__name=cloud_resource_type_name(cloud_type, kind),
                        cloud_account__name=account_name,
                    )
                )

    class ForwardContribVRF(_ForwardContribDeleteMixin, NautobotModel):
        _model = VRF
        _modelname = "vrf"
        _identifiers = ("name", "namespace__name")
        _attributes = ("status__name",)
        name: str
        namespace__name: str
        status__name: str

    class ForwardContribVLAN(_ForwardContribDeleteMixin, NautobotModel):
        _model = VLAN
        _modelname = "vlan"
        _identifiers = ("vid", "name")
        _attributes = ("status__name",)
        vid: int
        name: str
        status__name: str

    class ForwardContribPrefix(_ForwardContribDeleteMixin, NautobotModel):
        # Identity on the real DB fields (network/prefix_length) — `prefix` is a
        # property and contrib's load/create call _meta.get_field, which fails on
        # non-fields. create() rebuilds the cidr via the property.
        _model = Prefix
        _modelname = "prefix"
        _identifiers = ("network", "prefix_length", "namespace__name")
        _attributes = ("status__name",)
        network: str
        prefix_length: int
        namespace__name: str
        status__name: str

        @classmethod
        def create(cls, adapter, ids, attrs):
            ns = Namespace.objects.get(name=ids["namespace__name"])
            status = Status.objects.get(name=attrs["status__name"])
            cidr = f"{ids['network']}/{ids['prefix_length']}"
            obj, _ = Prefix.objects.get_or_create(
                prefix=cidr, namespace=ns, defaults={"status": status}
            )
            model = super(NautobotModel, cls).create(adapter, ids=ids, attrs=attrs)
            model.pk = obj.pk
            return model

    class ForwardContribIPAddress(_ForwardContribDeleteMixin, NautobotModel):
        # Identity on real fields (host/mask_length); `address` is a property and
        # IPAddress needs a namespace at construction, so create() is custom.
        _model = IPAddress
        _modelname = "ip_address"
        _identifiers = ("host", "mask_length")
        _attributes = ("status__name",)
        host: str
        mask_length: int
        status__name: str

        @classmethod
        def create(cls, adapter, ids, attrs):
            ns = Namespace.objects.get(name="Global")
            status = Status.objects.get(name=attrs["status__name"])
            address = f"{ids['host']}/{ids['mask_length']}"
            # Match on host AND mask within the same namespace — filter(host=)
            # alone would treat 10.0.0.1/24 and 10.0.0.1/32 as identical, and an
            # unscoped match could pick an IP from a different namespace.
            obj = IPAddress.objects.filter(
                host=ids["host"], mask_length=ids["mask_length"], parent__namespace=ns
            ).first() or IPAddress.objects.create(address=address, namespace=ns, status=status)
            model = super(NautobotModel, cls).create(adapter, ids=ids, attrs=attrs)
            model.pk = obj.pk
            return model

    class ForwardContribInventoryItem(_ForwardContribDeleteMixin, NautobotModel):
        _model = InventoryItem
        _modelname = "inventory_item"
        _identifiers = ("device__name", "name")
        _attributes = ("manufacturer__name",)
        device__name: str
        name: str
        manufacturer__name: str

    class ForwardContribModuleType(_ForwardContribDeleteMixin, NautobotModel):
        _model = ModuleType
        _modelname = "module_type"
        _identifiers = ("manufacturer__name", "model")
        _attributes = ()
        manufacturer__name: str
        model: str

    class ForwardContribModuleBay(_ForwardContribDeleteMixin, NautobotModel):
        _model = ModuleBay
        _modelname = "module_bay"
        _identifiers = ("parent_device__name", "name")
        _attributes = ()
        parent_device__name: str
        name: str

    class ForwardContribModule(_ForwardContribDeleteMixin, NautobotModel):
        # A Module occupies a ModuleBay; identity is the bay (device + bay name).
        _model = Module
        _modelname = "module"
        _identifiers = ("parent_module_bay__parent_device__name", "parent_module_bay__name")
        _attributes = ("module_type__manufacturer__name", "module_type__model", "status__name")
        parent_module_bay__parent_device__name: str
        parent_module_bay__name: str
        module_type__manufacturer__name: str
        module_type__model: str
        status__name: str

    # IPAM + assets sync after the device chain (devices must already exist).
    # module_type/module_bay precede module (FK targets created first).
    _EXTENDED_TOP_LEVEL = [
        "vrf",
        "vlan",
        "prefix",
        "ip_address",
        "inventory_item",
        "module_type",
        "module_bay",
        "module",
    ]

    class ForwardContribExtendedTarget(NautobotAdapter):
        top_level = _EXTENDED_TOP_LEVEL
        vrf = ForwardContribVRF
        vlan = ForwardContribVLAN
        prefix = ForwardContribPrefix
        ip_address = ForwardContribIPAddress
        inventory_item = ForwardContribInventoryItem
        module_type = ForwardContribModuleType
        module_bay = ForwardContribModuleBay
        module = ForwardContribModule

    class ForwardContribExtendedSource(Adapter):
        top_level = _EXTENDED_TOP_LEVEL
        vrf = ForwardContribVRF
        vlan = ForwardContribVLAN
        prefix = ForwardContribPrefix
        ip_address = ForwardContribIPAddress
        inventory_item = ForwardContribInventoryItem
        module_type = ForwardContribModuleType
        module_bay = ForwardContribModuleBay
        module = ForwardContribModule

        def __init__(
            self,
            *,
            vrf_rows: list[dict[str, Any]],
            vlan_rows: list[dict[str, Any]],
            prefix_rows: list[dict[str, Any]],
            ipaddress_rows: list[dict[str, Any]],
            inventory_rows: list[dict[str, Any]],
            module_rows: list[dict[str, Any]] | None = None,
            namespace_name: str = "Global",
            status_name: str = "Active",
            **kwargs,
        ):
            super().__init__(**kwargs)
            self._vrf_rows = vrf_rows
            self._vlan_rows = vlan_rows
            self._prefix_rows = prefix_rows
            self._ipaddress_rows = ipaddress_rows
            self._inventory_rows = inventory_rows
            self._module_rows = module_rows or []
            self._namespace_name = namespace_name
            self._status_name = status_name

        def load(self):
            seen: set = set()
            for row in self._vrf_rows:
                name = str(row.get("name") or "").strip()
                if not name or ("vrf", name) in seen:
                    continue
                seen.add(("vrf", name))
                self.add(
                    ForwardContribVRF(
                        name=name,
                        namespace__name=self._namespace_name,
                        status__name=self._status_name,
                    )
                )
            for row in self._vlan_rows:
                vid = row.get("vid")
                name = str(row.get("name") or "").strip()
                if vid is None or not name or ("vlan", vid, name) in seen:
                    continue
                seen.add(("vlan", vid, name))
                self.add(
                    ForwardContribVLAN(vid=int(vid), name=name, status__name=self._status_name)
                )
            for row in self._prefix_rows:
                pfx = str(row.get("prefix") or "").strip()
                net, _, plen = pfx.partition("/")
                if not net or not plen.isdigit() or ("prefix", net, plen) in seen:
                    continue
                seen.add(("prefix", net, plen))
                self.add(
                    ForwardContribPrefix(
                        network=net,
                        prefix_length=int(plen),
                        namespace__name=self._namespace_name,
                        status__name=self._status_name,
                    )
                )
            for row in self._ipaddress_rows:
                host = str(row.get("host_ip") or "").strip()
                mask = row.get("prefix_length")
                if not host or mask is None:
                    addr = str(row.get("address") or "").strip()
                    h, _, m = addr.partition("/")
                    host = host or h
                    mask = int(m) if (mask is None and m.isdigit()) else mask
                if not host or mask is None or ("ip", host, mask) in seen:
                    continue
                seen.add(("ip", host, mask))
                self.add(
                    ForwardContribIPAddress(
                        host=host, mask_length=int(mask), status__name=self._status_name
                    )
                )
            # Device-scoped slices reference devices by FK lookup; restrict to
            # devices that actually exist (core sync runs first) so one missing
            # device cannot fail the whole extended sync.
            existing_devices = set(Device.objects.values_list("name", flat=True))

            for row in self._inventory_rows:
                dev = str(row.get("device") or "").strip()
                name = str(row.get("name") or "").strip()
                mfr = str(row.get("manufacturer") or "").strip()
                if not (dev and name and mfr) or dev not in existing_devices:
                    continue
                if ("inv", dev, name) in seen:
                    continue
                seen.add(("inv", dev, name))
                self.add(
                    ForwardContribInventoryItem(device__name=dev, name=name, manufacturer__name=mfr)
                )

            # Modules: derive ModuleType (manufacturer+model) and ModuleBay
            # (device+bay) first, then the Module occupying the bay.
            module_types: set[tuple[str, str]] = set()
            module_bays: set[tuple[str, str]] = set()
            for row in self._module_rows:
                dev = str(row.get("device") or "").strip()
                bay = str(row.get("module_bay") or "").strip()
                mfr = str(row.get("manufacturer") or "").strip()
                model = str(row.get("model") or "").strip()
                if dev not in existing_devices:
                    continue
                if dev and bay and ("mtype", mfr, model) not in module_types and mfr and model:
                    module_types.add(("mtype", mfr, model))
                    self.add(ForwardContribModuleType(manufacturer__name=mfr, model=model))
            for row in self._module_rows:
                dev = str(row.get("device") or "").strip()
                bay = str(row.get("module_bay") or "").strip()
                if dev not in existing_devices:
                    continue
                if dev and bay and ("mbay", dev, bay) not in module_bays:
                    module_bays.add(("mbay", dev, bay))
                    self.add(ForwardContribModuleBay(parent_device__name=dev, name=bay))
            seen_modules: set[tuple[str, str]] = set()
            for row in self._module_rows:
                dev = str(row.get("device") or "").strip()
                bay = str(row.get("module_bay") or "").strip()
                mfr = str(row.get("manufacturer") or "").strip()
                model = str(row.get("model") or "").strip()
                if dev not in existing_devices:
                    continue
                if not (dev and bay and mfr and model) or (dev, bay) in seen_modules:
                    continue
                seen_modules.add((dev, bay))
                self.add(
                    ForwardContribModule(
                        parent_module_bay__parent_device__name=dev,
                        parent_module_bay__name=bay,
                        module_type__manufacturer__name=mfr,
                        module_type__model=model,
                        status__name=self._status_name,
                    )
                )

    class _StubJob:
        """Minimal job satisfying NautobotAdapter (logger + no metadata)."""

        class _Logger:
            def _noop(self, *args, **kwargs):
                return None

            info = warning = error = debug = _noop

        logger = _Logger()


def _ensure_status_with_content_types(status_name: str, models: list):
    status, _ = Status.objects.get_or_create(name=status_name)
    for model in models:
        ct = ContentType.objects.get_for_model(model)
        if not status.content_types.filter(pk=ct.pk).exists():
            status.content_types.add(ct)
    return status


def ensure_core_prerequisites(
    *,
    location_type_name: str,
    location_status_name: str,
    device_role_name: str,
    device_status_name: str,
):
    """Create the LocationType / Status / Role objects the core slices resolve by
    lookup (with the right content-types), since contrib will not create them."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    location_type, _ = LocationType.objects.get_or_create(name=location_type_name)
    # A Device may only sit at a LocationType whose content_types include Device.
    dev_ct = ContentType.objects.get_for_model(Device)
    if not location_type.content_types.filter(pk=dev_ct.pk).exists():
        location_type.content_types.add(dev_ct)
    _ensure_status_with_content_types(location_status_name, [Location])
    # Device status also covers interfaces (they reuse the same default status).
    _ensure_status_with_content_types(device_status_name, [Device, Interface])
    role, _ = Role.objects.get_or_create(name=device_role_name, defaults={"color": "000000"})
    dev_ct = ContentType.objects.get_for_model(Device)
    if not role.content_types.filter(pk=dev_ct.pk).exists():
        role.content_types.add(dev_ct)


def run_contrib_core_sync(
    *,
    location_rows: list[dict[str, Any]],
    device_rows: list[dict[str, Any]],
    location_type_name: str,
    location_status_name: str,
    device_role_name: str,
    device_status_name: str,
    dryrun: bool,
    interface_rows: list[dict[str, Any]] | None = None,
    allow_delete: bool = False,
    job: Any | None = None,
) -> dict[str, int]:
    """Sync locations + the device FK chain (+ interfaces) into Nautobot via
    contrib CRUD. Returns the diffsync summary; dryrun computes without applying.
    """
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    # Prerequisites mutate the DB, so only create them on a real (non-dryrun) run.
    # The diff itself never calls create(), so dryrun needs nothing ensured.
    if not dryrun:
        ensure_core_prerequisites(
            location_type_name=location_type_name,
            location_status_name=location_status_name,
            device_role_name=device_role_name,
            device_status_name=device_status_name,
        )

    # Canonical location set = union of the locations slice and every location a
    # device references, so each device's FK target exists.
    canon = LocationCanonicalizer()
    for row in location_rows:
        canon.add(row.get("name") or "")
    for row in device_rows:
        canon.add(row.get("location") or "")

    job = job or _StubJob()
    target = ForwardContribCoreTarget(job=job)
    target.allow_delete = bool(allow_delete)
    target.load()
    source = ForwardContribCoreSource(
        location_rows=location_rows,
        device_rows=device_rows,
        canonicalizer=canon,
        location_type_name=location_type_name,
        location_status_name=location_status_name,
        device_role_name=device_role_name,
        device_status_name=device_status_name,
        interface_rows=interface_rows or [],
        interface_status_name=device_status_name,
    )
    source.load()
    diff = source.diff_to(target)
    summary = dict(diff.summary())
    if not dryrun:
        source.sync_to(target)
    return summary


def ensure_extended_prerequisites(*, namespace_name: str = "Global", status_name: str = "Active"):
    """Ensure the Namespace + Status (with IPAM/asset content types) the extended
    slices resolve by lookup."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    Namespace.objects.get_or_create(name=namespace_name)
    _ensure_status_with_content_types(status_name, [VLAN, VRF, Prefix, IPAddress, Module])


def run_contrib_extended_sync(
    *,
    vrf_rows: list[dict[str, Any]] | None = None,
    vlan_rows: list[dict[str, Any]] | None = None,
    prefix_rows: list[dict[str, Any]] | None = None,
    ipaddress_rows: list[dict[str, Any]] | None = None,
    inventory_rows: list[dict[str, Any]] | None = None,
    module_rows: list[dict[str, Any]] | None = None,
    namespace_name: str = "Global",
    status_name: str = "Active",
    dryrun: bool,
    allow_delete: bool = False,
    job: Any | None = None,
) -> dict[str, int]:
    """Sync IPAM (VRF/VLAN/Prefix/IPAddress) + inventory items into Nautobot via
    contrib CRUD. Devices must already exist (run the core sync first). Returns the
    diffsync summary; dryrun computes without applying."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    if not dryrun:
        ensure_extended_prerequisites(namespace_name=namespace_name, status_name=status_name)
    job = job or _StubJob()
    target = ForwardContribExtendedTarget(job=job)
    target.allow_delete = bool(allow_delete)
    target.load()
    source = ForwardContribExtendedSource(
        vrf_rows=vrf_rows or [],
        vlan_rows=vlan_rows or [],
        prefix_rows=prefix_rows or [],
        ipaddress_rows=ipaddress_rows or [],
        inventory_rows=inventory_rows or [],
        module_rows=module_rows or [],
        namespace_name=namespace_name,
        status_name=status_name,
    )
    source.load()
    diff = source.diff_to(target)
    summary = dict(diff.summary())
    if not dryrun:
        source.sync_to(target)
    return summary


def _ensure_cloud_resource_type(name: str, provider, content_model):
    rt, _ = CloudResourceType.objects.get_or_create(name=name, defaults={"provider": provider})
    if rt.provider_id != provider.pk:
        rt.provider = provider
        rt.save()
    ct = ContentType.objects.get_for_model(content_model)
    if not rt.content_types.filter(pk=ct.pk).exists():
        rt.content_types.add(ct)
    return rt


def ensure_cloud_prerequisites(
    *,
    account_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
    service_rows: list[dict[str, Any]],
):
    """Ensure provider Manufacturers and CloudResourceTypes (with content types)
    that the cloud slices resolve by lookup."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    providers: dict[str, Any] = {}

    def provider_for(cloud_type: str):
        pname = cloud_provider_name(cloud_type)
        if pname not in providers:
            providers[pname], _ = Manufacturer.objects.get_or_create(name=pname)
        return providers[pname]

    for row in account_rows:
        provider_for(row.get("cloud_type") or "")
    for row in network_rows:
        ct = row.get("cloud_type") or ""
        kind = row.get("kind") or "vpc"
        _ensure_cloud_resource_type(
            cloud_resource_type_name(ct, kind), provider_for(ct), CloudNetwork
        )
    for row in service_rows:
        ct = row.get("cloud_type") or ""
        kind = row.get("service_kind") or ""
        _ensure_cloud_resource_type(
            cloud_resource_type_name(ct, kind), provider_for(ct), CloudService
        )


def run_contrib_cloud_sync(
    *,
    account_rows: list[dict[str, Any]],
    network_rows: list[dict[str, Any]],
    service_rows: list[dict[str, Any]],
    dryrun: bool,
    allow_delete: bool = False,
    job: Any | None = None,
) -> dict[str, int]:
    """Sync Forward cloud accounts / networks / services into Nautobot's cloud app
    via contrib CRUD. Returns the diffsync summary; dryrun computes without applying."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    if not dryrun:
        ensure_cloud_prerequisites(
            account_rows=account_rows, network_rows=network_rows, service_rows=service_rows
        )
    job = job or _StubJob()
    target = ForwardContribCloudTarget(job=job)
    target.allow_delete = bool(allow_delete)
    target.load()
    source = ForwardContribCloudSource(
        account_rows=account_rows, network_rows=network_rows, service_rows=service_rows
    )
    source.load()
    diff = source.diff_to(target)
    summary = dict(diff.summary())
    if not dryrun:
        source.sync_to(target)
        _link_cloud_relationships(network_rows=network_rows, service_rows=service_rows)
    return summary


def _link_cloud_relationships(
    *,
    network_rows: list[dict[str, Any]],
    service_rows: list[dict[str, Any]],
    namespace_name: str = "Cloud",
    status_name: str = "Active",
):
    """Wire the cloud topology relationships contrib's generic CRUD doesn't:
    subnet/VPC CIDRs -> Prefixes (in a dedicated Cloud namespace) attached via
    CloudNetwork.prefixes, and CloudService -> its VPC via cloud_networks. M2M, so
    done as an idempotent post-pass rather than diffsync attributes."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        return
    ns, _ = Namespace.objects.get_or_create(name=namespace_name)
    status = _ensure_status_with_content_types(status_name, [Prefix])
    name_by_network_id = {
        str(r.get("network_id") or "").strip(): str(r.get("name") or "").strip()
        for r in network_rows
        if r.get("network_id") and r.get("name")
    }
    # CIDRs -> Prefixes attached to their CloudNetwork.
    for row in network_rows:
        cn = CloudNetwork.objects.filter(name=str(row.get("name") or "").strip()).first()
        if cn is None:
            continue
        for cidr in row.get("cidrs") or []:
            if "/" not in str(cidr):
                continue
            prefix, _ = Prefix.objects.get_or_create(
                prefix=str(cidr), namespace=ns, defaults={"status": status}
            )
            cn.prefixes.add(prefix)
    # Service -> its VPC.
    for row in service_rows:
        svc = CloudService.objects.filter(name=str(row.get("name") or "").strip()).first()
        vpc_name = name_by_network_id.get(str(row.get("vpc_id") or "").strip())
        if svc is None or not vpc_name:
            continue
        vpc = CloudNetwork.objects.filter(name=vpc_name, parent__isnull=True).first()
        if vpc is not None:
            svc.cloud_networks.add(vpc)


def _profile_defaults(profile) -> dict[str, str]:
    """Pull the contrib prerequisite names off a connection profile (with sane
    fallbacks) so the runners can ensure them."""
    g = lambda attr, default: str(getattr(profile, attr, "") or default)  # noqa: E731
    return {
        "location_type_name": g("default_location_type_name", "Site"),
        "location_status_name": g("default_location_status_name", "Active"),
        "device_role_name": g("default_device_role_name", "Network Device"),
        "device_status_name": g("default_device_status_name", "Active"),
    }


def _cloud_query_rows(client, network_id, snapshot_id, query_file):
    """Run a bundled cloud .nqe inline via the client and return its rows.

    Cloud slices are not in the model registry/planner, so they are fetched here.
    Returns [] on any client error (e.g. a tenant with no cloud data).
    """
    from importlib import resources

    from .models import ForwardQuerySpec

    pkg = resources.files("forward_nautobot.integrations.forward.queries")
    raw = (pkg / query_file).read_text(encoding="utf-8").splitlines()
    if raw and raw[0].startswith("/*"):
        end = next((i for i, ln in enumerate(raw) if ln.rstrip().endswith("*/")), None)
        if end is not None:
            raw = raw[end + 1 :]
    text = "\n".join(ln for ln in raw if not ln.strip().startswith("@primaryKey")).strip()
    # fetch_all so large tenants are not silently truncated to one page; the
    # error propagates (a real API/permission failure must not look like
    # "no cloud" — that's the caller's distinction to make).
    return client.run_nqe_query(
        query_spec=ForwardQuerySpec(query_text=text),
        network_id=network_id,
        snapshot_id=snapshot_id,
        fetch_all=True,
    )


def run_contrib_full_sync(
    *,
    source_records: dict[str, Any],
    profile,
    dryrun: bool,
    client=None,
    network_id: str = "",
    snapshot_id: str | None = None,
    include_cloud: bool = True,
    allow_delete: bool = False,
    job: Any | None = None,
) -> dict[str, dict[str, int]]:
    """Drive the whole Forward->Nautobot import through contrib CRUD.

    `source_records` is the planner's per-slice rows (slug -> list of field dicts).
    Network slices come from there; cloud slices are fetched via `client` (if
    given) using the bundled cloud NQEs. Returns per-domain diffsync summaries.
    Delete-safe by default. This is the cutover entry point the SSoT Job calls
    when the contrib path is enabled.
    """
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")

    def rows(slug):
        return [dict(r) for r in (source_records.get(slug) or [])]

    defaults = _profile_defaults(profile)
    job = job or _StubJob()
    summaries: dict[str, dict[str, int]] = {}

    summaries["core"] = run_contrib_core_sync(
        location_rows=rows("locations"),
        device_rows=rows("devices"),
        interface_rows=rows("interfaces"),
        dryrun=dryrun,
        allow_delete=allow_delete,
        job=job,
        **defaults,
    )
    summaries["ipam_assets"] = run_contrib_extended_sync(
        vrf_rows=rows("vrfs"),
        vlan_rows=rows("vlans"),
        prefix_rows=rows("ipv4_prefixes") + rows("ipv6_prefixes"),
        ipaddress_rows=rows("ip_addresses"),
        inventory_rows=rows("inventory_items"),
        module_rows=rows("modules"),
        dryrun=dryrun,
        allow_delete=allow_delete,
        job=job,
    )
    if include_cloud and client is not None and network_id:
        # A cloud-fetch failure is isolated to the cloud domain — the network
        # sync already succeeded, so record it as a skip reason rather than
        # aborting the whole run. An empty result (no cloud accounts) is normal.
        try:
            account_rows = _cloud_query_rows(
                client, network_id, snapshot_id, "forward_cloud_accounts.nqe"
            )
            if account_rows:
                summaries["cloud"] = run_contrib_cloud_sync(
                    account_rows=account_rows,
                    network_rows=_cloud_query_rows(
                        client, network_id, snapshot_id, "forward_cloud_networks.nqe"
                    ),
                    service_rows=_cloud_query_rows(
                        client, network_id, snapshot_id, "forward_cloud_services.nqe"
                    ),
                    dryrun=dryrun,
                    allow_delete=allow_delete,
                    job=job,
                )
            else:
                summaries["cloud"] = {"skipped": "no cloud accounts"}
        except Exception as exc:  # noqa: BLE001 - isolate cloud failure from network sync
            summaries["cloud"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    return summaries
