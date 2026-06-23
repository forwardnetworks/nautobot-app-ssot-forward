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
    from nautobot.dcim.models import (
        Device,
        DeviceType,
        Interface,
        Location,
        LocationType,
        Manufacturer,
        Platform,
    )
    from nautobot.extras.models import Role, Status
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


def cloud_provider_name(cloud_type: str) -> str:
    key = str(cloud_type or "").strip().upper()
    return _CLOUD_PROVIDER_NAMES.get(key, key or "Cloud")


def cloud_resource_type_name(cloud_type: str, kind: str) -> str:
    """Readable CloudResourceType name, e.g. 'AWS vpc' -> 'AWS VPC'."""
    ct = str(cloud_type or "").strip().upper()
    pretty = {
        "vpc": "VPC",
        "subnet": "Subnet",
        "load-balancer": "Load Balancer",
        "nat-gateway": "NAT Gateway",
    }.get(str(kind or "").strip(), str(kind or "").strip())
    return f"{ct} {pretty}".strip()


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

    class ForwardContribManufacturer(NautobotModel):
        _model = Manufacturer
        _modelname = "manufacturer"
        _identifiers = ("name",)
        _attributes = ()
        name: str

    class ForwardContribLocation(NautobotModel):
        _model = Location
        _modelname = "location"
        _identifiers = ("name",)
        _attributes = ("location_type__name", "status__name")
        name: str
        location_type__name: str
        status__name: str

    class ForwardContribPlatform(NautobotModel):
        _model = Platform
        _modelname = "platform"
        _identifiers = ("name",)
        _attributes = ("manufacturer__name",)
        name: str
        manufacturer__name: str

    class ForwardContribDeviceType(NautobotModel):
        _model = DeviceType
        _modelname = "device_type"
        _identifiers = ("manufacturer__name", "model")
        _attributes = ()
        manufacturer__name: str
        model: str

    class ForwardContribDevice(NautobotModel):
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

    class ForwardContribInterface(NautobotModel):
        _model = Interface
        _modelname = "interface"
        _identifiers = ("device__name", "name")
        _attributes = ("type", "status__name", "enabled", "mtu", "description")
        device__name: str
        name: str
        type: str
        status__name: str
        enabled: bool = True
        mtu: int | None = None
        description: str = ""

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

    # Nautobot Interface.type is a choice field; map unknown Forward types here.
    _INTERFACE_TYPE_FALLBACK = "other"
    _KNOWN_INTERFACE_TYPES = {
        "virtual",
        "lag",
        "bridge",
        "other",
        "1000base-t",
        "10gbase-x-sfpp",
        "25gbase-x-sfp28",
        "40gbase-x-qsfpp",
        "100gbase-x-qsfp28",
    }

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
                self.add(
                    ForwardContribInterface(
                        device__name=dev,
                        name=iname,
                        type=itype,
                        status__name=self._interface_status_name,
                        enabled=bool(row.get("enabled", True)),
                        mtu=int(mtu) if isinstance(mtu, int) else None,
                        description=str(row.get("description") or ""),
                    )
                )

    class ForwardContribCloudAccount(NautobotModel):
        _model = CloudAccount
        _modelname = "cloud_account"
        _identifiers = ("name",)
        _attributes = ("account_number", "provider__name")
        name: str
        account_number: str
        provider__name: str

    class ForwardContribCloudNetwork(NautobotModel):
        _model = CloudNetwork
        _modelname = "cloud_network"
        _identifiers = ("name",)
        _attributes = ("cloud_resource_type__name", "cloud_account__name")
        name: str
        cloud_resource_type__name: str
        cloud_account__name: str

    class ForwardContribCloudService(NautobotModel):
        _model = CloudService
        _modelname = "cloud_service"
        _identifiers = ("name",)
        _attributes = ("cloud_resource_type__name", "cloud_account__name")
        name: str
        cloud_resource_type__name: str
        cloud_account__name: str

    _CLOUD_TOP_LEVEL = ["cloud_account", "cloud_network", "cloud_service"]

    class ForwardContribCloudTarget(NautobotAdapter):
        top_level = _CLOUD_TOP_LEVEL
        cloud_account = ForwardContribCloudAccount
        cloud_network = ForwardContribCloudNetwork
        cloud_service = ForwardContribCloudService

    class ForwardContribCloudSource(Adapter):
        top_level = _CLOUD_TOP_LEVEL
        cloud_account = ForwardContribCloudAccount
        cloud_network = ForwardContribCloudNetwork
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
                self.add(
                    ForwardContribCloudNetwork(
                        name=name,
                        cloud_resource_type__name=cloud_resource_type_name(cloud_type, kind),
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
    job: Any | None = None,
) -> dict[str, int]:
    """Sync locations + the device FK chain (+ interfaces) into Nautobot via
    contrib CRUD. Returns the diffsync summary; dryrun computes without applying.
    """
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
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
    job: Any | None = None,
) -> dict[str, int]:
    """Sync Forward cloud accounts / networks / services into Nautobot's cloud app
    via contrib CRUD. Returns the diffsync summary; dryrun computes without applying."""
    if not CONTRIB_AVAILABLE:  # pragma: no cover
        raise RuntimeError("nautobot-ssot contrib path is unavailable in this environment.")
    ensure_cloud_prerequisites(
        account_rows=account_rows, network_rows=network_rows, service_rows=service_rows
    )
    job = job or _StubJob()
    target = ForwardContribCloudTarget(job=job)
    target.load()
    source = ForwardContribCloudSource(
        account_rows=account_rows, network_rows=network_rows, service_rows=service_rows
    )
    source.load()
    diff = source.diff_to(target)
    summary = dict(diff.summary())
    if not dryrun:
        source.sync_to(target)
    return summary
