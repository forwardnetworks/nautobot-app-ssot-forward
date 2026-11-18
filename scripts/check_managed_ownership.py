"""Managed-object ownership check against a real Nautobot database.

This is the scenario that failed on a real box and forced deletes to be
disabled everywhere: a scoped sync delete-reconciles the whole target table and
tries to remove objects it never created. Unit tests pin the gate's logic with
stubs; only a database can show that the mark is really written, really read
back, and really stops the delete.

Three things are asserted:

1. An unmanaged object survives a sync that is allowed to delete. This is the
   safety property. Before the ownership gate, a device-only sync tried to
   delete cloud-provider manufacturers.
2. Objects the plugin creates carry the ownership mark. Without this the gate
   would be trivially safe and equally useless, since nothing would ever be
   deletable.
3. Adoption works. An unmarked object is claimed by the next sync, because the
   mark is a synced attribute: the target reads it absent, the source asserts
   it, and the difference forces the update that writes it. This is what lets a
   cutover adopt what the legacy write path created.

Run inside the Django app context:

    nautobot-server shell < scripts/check_managed_ownership.py

Prints "OWNERSHIP: PASS" or "OWNERSHIP: FAIL ..." and is safe to re-run.
"""

from __future__ import annotations

_MARK = "zzz-own-check"
_ORPHAN = f"{_MARK}-orphan-manufacturer"

import forward_nautobot.integrations.forward.contrib_sync as cs  # noqa: E402
from forward_nautobot.integrations.forward import managed  # noqa: E402

location_rows = [{"name": f"{_MARK}-site", "city": "", "country": ""}]
device_rows = [
    {
        "name": f"{_MARK}-dev",
        "location": f"{_MARK}-site",
        "vendor": f"{_MARK}-vendor",
        "model": f"{_MARK}-model",
        "device_type": f"{_MARK}-model",
    }
]

kwargs = dict(
    location_rows=location_rows,
    device_rows=device_rows,
    interface_rows=[],
    location_type_name="Site",
    location_status_name="Active",
    device_role_name="Network Device",
    device_status_name="Active",
)


def _cleanup() -> None:
    from nautobot.dcim.models import Device, DeviceType, Location, Manufacturer

    Device.objects.filter(name__startswith=_MARK).delete()
    DeviceType.objects.filter(model__startswith=_MARK).delete()
    Location.objects.filter(name__startswith=_MARK).delete()
    Manufacturer.objects.filter(name__startswith=_MARK).delete()


failures: list[str] = []

try:
    from nautobot.dcim.models import Manufacturer

    _cleanup()

    # An object nobody told the plugin about. It is not in the source rows, so a
    # delete-reconciling sync would remove it if ownership were not consulted.
    orphan = Manufacturer.objects.create(name=_ORPHAN)
    if managed.is_managed(orphan):
        failures.append("a hand-created object was already marked as Forward-managed")

    # Deletes fully enabled: governance must not be what saves the orphan here.
    cs.run_contrib_core_sync(dryrun=False, allow_delete=True, **kwargs)

    if not Manufacturer.objects.filter(name=_ORPHAN).exists():
        failures.append(
            "UNMANAGED OBJECT WAS DELETED — the ownership gate did not hold. "
            "This is the exact failure that forced deletes to be disabled."
        )

    # The plugin's own objects must carry the mark, or nothing is ever deletable.
    created = Manufacturer.objects.filter(name__iexact=f"{_MARK}-vendor").first()
    if created is None:
        failures.append("expected the sync to have created the vendor manufacturer")
    elif not managed.is_managed(created):
        failures.append("a Forward-created object did not carry the ownership mark")

    # Adoption. Strip the mark to imitate an object the legacy write path created,
    # then re-sync: the next pass must claim it without anything else changing.
    if created is not None:
        created.cf[managed.FORWARD_MANAGED_KEY] = False
        created.validated_save()
        cs.run_contrib_core_sync(dryrun=False, allow_delete=False, **kwargs)
        refreshed = Manufacturer.objects.get(pk=created.pk)
        if not managed.is_managed(refreshed):
            failures.append(
                "an unmarked object was NOT adopted by the next sync — objects from "
                "the legacy write path would stay undeletable forever"
            )

    # Adoption must not be indiscriminate: claiming happens for objects the sync
    # actually covers, not for every row in the table.
    if Manufacturer.objects.filter(name=_ORPHAN).exists():
        orphan_after = Manufacturer.objects.get(name=_ORPHAN)
        if managed.is_managed(orphan_after):
            failures.append(
                "an object outside the sync was claimed — ownership must not spread "
                "to objects the source never produced"
            )

    if failures:
        print("OWNERSHIP: FAIL — " + "; ".join(failures))
    else:
        print(
            "OWNERSHIP: PASS (orphan survived unclaimed, created objects marked, "
            "unmarked objects adopted)"
        )
finally:
    _cleanup()
