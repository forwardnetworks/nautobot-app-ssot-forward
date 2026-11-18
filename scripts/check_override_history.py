"""Delete-override history check against a real Nautobot database.

Unit tests stub the model; only a database can show that the migration created the
table, that a row is really written, and that it survives deleting its profile.

Run inside the Django app context:

    nautobot-server shell < scripts/check_override_history.py

Prints "OVERRIDE HISTORY: PASS" or "OVERRIDE HISTORY: FAIL ..." and cleans up after
itself, so it is safe to re-run.
"""

from __future__ import annotations

from forward_nautobot.integrations.forward.override_history import record_delete_overrides
from forward_nautobot.models import ForwardConnectionProfile, ForwardDeleteOverride

NAME = "override-history-check"
EXECUTION = {
    "summaries": {
        "network": {
            "delete_governance": {
                "deletes_overridden": [
                    {"model": "dcim.device", "would_delete": 3, "target_count": 10}
                ],
                "override": {"user": "checker", "reason": "scripted check", "at": ""},
            }
        }
    }
}


def _run() -> str:
    ForwardConnectionProfile.objects.filter(name=NAME).delete()
    ForwardDeleteOverride.objects.filter(profile_name=NAME).delete()
    profile = ForwardConnectionProfile.objects.create(name=NAME)
    try:
        if not record_delete_overrides(
            profile_name=NAME, snapshot_id="snap-check", write_execution=EXECUTION
        ):
            return "FAIL record_delete_overrides returned False"
        row = ForwardDeleteOverride.objects.get(profile_name=NAME)
        if (row.user, row.reason, row.snapshot_id) != ("checker", "scripted check", "snap-check"):
            return f"FAIL stored fields differ: {(row.user, row.reason, row.snapshot_id)}"
        if row.profile_id != profile.id:
            return "FAIL row is not linked to its profile"
        profile.delete()
        row.refresh_from_db()
        if row.profile_id is not None or row.profile_name != NAME:
            return "FAIL row did not survive deleting its profile"
        return "PASS"
    finally:
        ForwardConnectionProfile.objects.filter(name=NAME).delete()
        ForwardDeleteOverride.objects.filter(profile_name=NAME).delete()


print(f"OVERRIDE HISTORY: {_run()}")
