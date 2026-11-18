"""Hand-made Nautobot objects must not break a sync.

Found by a live run: one device with no platform anywhere in Nautobot made every
Forward sync raise, because the plugin's Device model declared `platform` as a
required string while Nautobot allows it to be empty. Nautobot has many nullable
relations and people leave them empty, so this builds one hand-made object per
nullable relation or empty identifier the plugin loads that Nautobot 3.2 can
actually produce: no platform, no manufacturer, no status, and a device with no
name (plus the interface and inventory item attached to it), runs the core and extended syncs against the
table, and checks that they load without raising and leave the objects alone.

Run inside the Django app context:

    nautobot-server shell < scripts/check_hand_made_objects.py

Prints "HAND-MADE OBJECTS: PASS" or "HAND-MADE OBJECTS: FAIL ..." and cleans up
after itself, so it is safe to re-run.
"""

from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from nautobot.dcim.models import (
    Device,
    DeviceType,
    Interface,
    InventoryItem,
    Location,
    LocationType,
    Manufacturer,
    Platform,
)
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import VRF

import forward_nautobot.integrations.forward.contrib_sync as cs

MARK = "zzz-handmade"


def _cleanup() -> None:
    VRF.objects.filter(name__startswith=MARK).delete()
    InventoryItem.objects.filter(name__startswith=MARK).delete()
    Device.objects.filter(name__startswith=MARK).delete()
    Device.objects.filter(name__isnull=True, location__name__startswith=MARK).delete()
    Platform.objects.filter(name__startswith=MARK).delete()
    DeviceType.objects.filter(model__startswith=MARK).delete()
    Manufacturer.objects.filter(name__startswith=MARK).delete()
    Location.objects.filter(name__startswith=MARK).delete()


def _run() -> str:
    _cleanup()
    active = Status.objects.get(name="Active")
    device_type_ct = ContentType.objects.get_for_model(Device)
    location_type, _ = LocationType.objects.get_or_create(name="Site")
    location_type.content_types.add(device_type_ct)
    role, _ = Role.objects.get_or_create(name="Network Device")
    role.content_types.add(device_type_ct)

    location = Location.objects.create(
        name=f"{MARK}-site", location_type=location_type, status=active
    )
    manufacturer = Manufacturer.objects.create(name=f"{MARK}-mf")
    device_type = DeviceType.objects.create(manufacturer=manufacturer, model=f"{MARK}-dt")
    # Each of these leaves a nullable relation empty, as people do by hand.
    device = Device.objects.create(  # no platform
        name=f"{MARK}-dev", device_type=device_type, role=role, status=active, location=location
    )
    unnamed = Device.objects.create(  # no name at all; Nautobot allows it
        name=None, device_type=device_type, role=role, status=active, location=location
    )
    Interface.objects.create(  # on the unnamed device, so its device name is empty too
        device=unnamed, name=f"{MARK}-if", type="1000base-t", status=active
    )
    InventoryItem.objects.create(device=unnamed, name=f"{MARK}-inv-unnamed")
    Platform.objects.create(name=f"{MARK}-plat")  # no manufacturer
    InventoryItem.objects.create(device=device, name=f"{MARK}-inv")  # no manufacturer
    VRF.objects.create(name=f"{MARK}-vrf")  # no status

    defaults = dict(
        location_type_name="Site",
        location_status_name="Active",
        device_role_name="Network Device",
        device_status_name="Active",
    )
    try:
        cs.run_contrib_core_sync(
            dryrun=False,
            allow_delete=False,
            location_rows=[],
            device_rows=[],
            interface_rows=[],
            **defaults,
        )
        cs.run_contrib_extended_sync(
            dryrun=False,
            allow_delete=False,
            vrf_rows=[],
            vlan_rows=[],
            prefix_rows=[],
            ipaddress_rows=[],
            inventory_rows=[],
            module_rows=[],
        )
    except Exception as exc:  # noqa: BLE001 - the failure is the finding
        return f"FAIL a sync raised on hand-made data: {type(exc).__name__}: {str(exc)[:200]}"

    missing = [
        label
        for label, present in (
            ("device", Device.objects.filter(name=f"{MARK}-dev").exists()),
            ("unnamed device", Device.objects.filter(pk=unnamed.pk).exists()),
            ("platform", Platform.objects.filter(name=f"{MARK}-plat").exists()),
            ("inventory item", InventoryItem.objects.filter(name=f"{MARK}-inv").exists()),
            ("vrf", VRF.objects.filter(name=f"{MARK}-vrf").exists()),
        )
        if not present
    ]
    if missing:
        return f"FAIL a sync with deletes off removed hand-made objects: {missing}"
    return "PASS"


try:
    print(f"HAND-MADE OBJECTS: {_run()}")
finally:
    _cleanup()
