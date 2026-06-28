"""Repeat-apply idempotence check for the contrib sync.

Runs run_contrib_core_sync twice over a tiny scratch fixture against a real
Nautobot DB and asserts the SECOND pass is a no-op (zero create / zero update) —
i.e. the source adapter's load() round-trips cleanly with no phantom UPDATE. Also
exercises the Interface.mac_address attribute, whose value Nautobot normalizes
(a normalization asymmetry would surface here as a phantom update). Cleans up the
scratch objects afterward.

Run inside the Django app context:

    nautobot-server shell < scripts/check_contrib_idempotence.py

Prints "IDEMPOTENCE: PASS" / "IDEMPOTENCE: FAIL ..." and is safe to re-run.
"""

from __future__ import annotations

_MARK = "zzz-idem-check"

import forward_nautobot.integrations.forward.contrib_sync as cs  # noqa: E402

location_rows = [{"name": f"{_MARK}-site", "city": "", "country": ""}]
device_rows = [
    {
        "name": f"{_MARK}-dev",
        "location": f"{_MARK}-site",
        "vendor": "cisco",
        "model": f"{_MARK}-model",
        "device_type": f"{_MARK}-model",
    }
]
interface_rows = [
    {
        "device": f"{_MARK}-dev",
        "name": "Ethernet1/1",
        "type": "10gbase-t",
        "enabled": True,
        "mtu": 1500,
        "description": "idempotence probe",
        "mac_address": "00:11:22:33:44:55",
    }
]

kwargs = dict(
    location_rows=location_rows,
    device_rows=device_rows,
    interface_rows=interface_rows,
    location_type_name="Site",
    location_status_name="Active",
    device_role_name="Network Device",
    device_status_name="Active",
)


def _cleanup() -> None:
    from nautobot.dcim.models import Device, DeviceType, Location

    Device.objects.filter(name__startswith=_MARK).delete()
    DeviceType.objects.filter(model__startswith=_MARK).delete()
    Location.objects.filter(name__startswith=_MARK).delete()


try:
    _cleanup()  # start from a clean slate
    first = cs.run_contrib_core_sync(dryrun=False, **kwargs)
    second = cs.run_contrib_core_sync(dryrun=False, **kwargs)
    created = int(second.get("create", 0) or 0)
    updated = int(second.get("update", 0) or 0)
    if created == 0 and updated == 0:
        print(f"IDEMPOTENCE: PASS (first={first}, second={second})")
    else:
        print(
            f"IDEMPOTENCE: FAIL — second pass not a no-op "
            f"(create={created}, update={updated}); second={second}"
        )
finally:
    _cleanup()
