"""Managed-object ownership for the contrib write path.

contrib's ``source.sync_to(target)`` delete-reconciles the whole target table:
anything the source does not contain is a delete candidate. The plugin imports a
scoped subset, so that default would remove Nautobot objects it never created --
manually added devices, another integration's data, cloud providers. This was
observed on a real database, where a device-only sync tried to delete
cloud-provider manufacturers.

Until now the answer was to refuse every delete. That is safe but it is why
deletes are disabled for filtered runs and for cloud entirely. This module
supplies the missing half: a durable mark saying "this plugin created or claimed
this object", so a delete can be allowed for exactly those and refused for
everything else.

The mark is a Nautobot custom field rather than a tag, because ``Manufacturer``
and ``Platform`` are not taggable while every model the plugin writes supports
custom fields.

Ownership is claimed on create and on update, through the one hook contrib routes
both through. Note what that does *not* cover: contrib issues an update only when
a synced attribute differs, so an object that already matches is never written and
a missing mark is never repaired. Verified against a real database.

The consequence is deliberate but worth knowing. Objects this plugin creates are
managed from birth. Objects created by the legacy write path, or by hand, stay
unmanaged until a sync actually changes one of their attributes -- and until then
they cannot be deleted by a sync. That errs toward keeping data, which is the
right direction, but it means a cutover does not retroactively adopt what the old
path created.
"""

from __future__ import annotations

from typing import Any

#: Custom field key carrying the ownership mark. Changing this orphans every
#: object stamped by an earlier version, so it is a migration, not a rename.
FORWARD_MANAGED_KEY = "forward_managed"

FORWARD_MANAGED_LABEL = "Forward Managed"

FORWARD_MANAGED_DESCRIPTION = (
    "Set by the Forward Field Integration on objects it creates or updates. "
    "Only objects carrying this mark may be deleted by a Forward sync."
)


def ensure_managed_custom_field(models: list[Any]) -> Any:
    """Create the ownership custom field and attach it to these content types.

    Safe to call repeatedly. Returns the ``CustomField``, or ``None`` when
    Nautobot is unavailable, so a caller in a bare environment is not forced to
    guard the call.
    """
    try:
        from django.contrib.contenttypes.models import ContentType
        from nautobot.extras.choices import CustomFieldTypeChoices
        from nautobot.extras.models import CustomField
    except Exception:  # pragma: no cover - no Nautobot in this environment
        return None

    field, _ = CustomField.objects.get_or_create(
        key=FORWARD_MANAGED_KEY,
        defaults={
            "label": FORWARD_MANAGED_LABEL,
            "type": CustomFieldTypeChoices.TYPE_BOOLEAN,
            "description": FORWARD_MANAGED_DESCRIPTION,
            "default": False,
        },
    )
    for model in models:
        content_type = ContentType.objects.get_for_model(model)
        if not field.content_types.filter(pk=content_type.pk).exists():
            field.content_types.add(content_type)
    return field


def claim(obj: Any) -> None:
    """Mark an ORM object as Forward-managed, without saving it.

    Called before the object is written so the mark lands in the same save
    rather than costing a second round trip.
    """
    custom_fields = getattr(obj, "cf", None)
    if custom_fields is None:
        return
    try:
        custom_fields[FORWARD_MANAGED_KEY] = True
    except Exception:  # pragma: no cover - object does not carry custom fields
        return


def is_managed(obj: Any) -> bool:
    """Is this object one the plugin created or claimed?

    Anything unmarked is treated as not ours, so an unreadable or absent mark
    fails closed: the object is kept, never deleted.
    """
    custom_fields = getattr(obj, "cf", None)
    if not custom_fields:
        return False
    try:
        return bool(custom_fields.get(FORWARD_MANAGED_KEY))
    except Exception:  # pragma: no cover - unexpected custom field container
        return False
