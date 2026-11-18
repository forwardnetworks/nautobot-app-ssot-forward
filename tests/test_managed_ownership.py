"""Ownership gate on the contrib write path.

These run without a database. The mixin and the ownership helpers are pure
Python; only the custom-field creation needs Nautobot, and that is covered by
the container-backed contrib tests.

What is being pinned here is the safety property: a Forward sync may delete only
objects it created or claimed, and anything it cannot confirm as its own is
kept. That is what makes `allow_delete=True` switchable at all -- before it,
the only safe answer was to refuse every delete, which is why deletes are off
for filtered runs and for cloud.
"""

from __future__ import annotations

from forward_nautobot.integrations.forward import managed
from forward_nautobot.integrations.forward.contrib_sync import _ForwardContribDeleteMixin


class _FakeObj:
    """Stands in for a Nautobot ORM object carrying custom field data."""

    def __init__(self, cf=None):
        self.cf = {} if cf is None else cf
        self.deleted = False

    def delete(self):
        self.deleted = True


class _Adapter:
    def __init__(self, *, allow_delete=False, delete_allowed_models=None):
        self.allow_delete = allow_delete
        if delete_allowed_models is not None:
            self.delete_allowed_models = delete_allowed_models


class _Base:
    """Minimal stand-in for contrib's NautobotModel delete/save surface."""

    def __init__(self, obj, adapter, modelname="device"):
        self._obj = obj
        self.adapter = adapter
        self._modelname = modelname
        self.super_delete_called = False

    def get_from_db(self):
        return self._obj

    def delete(self):
        self.super_delete_called = True
        return self

    @classmethod
    def _update_obj_with_parameters(cls, obj, parameters, adapter):
        obj.saved_parameters = parameters
        return obj


class _Model(_ForwardContribDeleteMixin, _Base):
    pass


def _model(*, cf=None, **adapter_kwargs):
    return _Model(_FakeObj(cf), _Adapter(**adapter_kwargs))


# -- the ownership mark ------------------------------------------------------


def test_claim_marks_an_object_before_it_is_saved():
    obj = _FakeObj()
    managed.claim(obj)
    assert obj.cf[managed.FORWARD_MANAGED_KEY] is True


def test_is_managed_reads_the_mark():
    assert managed.is_managed(_FakeObj({managed.FORWARD_MANAGED_KEY: True}))
    assert not managed.is_managed(_FakeObj({managed.FORWARD_MANAGED_KEY: False}))
    assert not managed.is_managed(_FakeObj())


def test_ownership_fails_closed_on_an_object_without_custom_fields():
    """An object we cannot read a mark from is someone else's."""

    class _NoCustomFields:
        pass

    assert not managed.is_managed(_NoCustomFields())
    managed.claim(_NoCustomFields())  # must not raise


def test_claim_happens_on_the_shared_write_hook():
    """contrib routes create and update through the same classmethod."""
    obj = _FakeObj()
    _Model._update_obj_with_parameters(obj, {"name": "device-1"}, _Adapter())
    assert obj.cf[managed.FORWARD_MANAGED_KEY] is True
    assert obj.saved_parameters == {"name": "device-1"}


# -- the delete gate ---------------------------------------------------------


def test_unowned_object_is_never_deleted_even_when_deletes_are_allowed():
    """The scenario that failed on a real database.

    A device-only sync tried to delete cloud-provider manufacturers it had
    never created. Governance says deletes are allowed; ownership says no.
    """
    model = _model(allow_delete=True)  # unmarked object
    model.delete()
    assert not model.super_delete_called
    assert not model._obj.deleted


def test_owned_object_is_deleted_when_governance_allows_it():
    model = _model(cf={managed.FORWARD_MANAGED_KEY: True}, allow_delete=True)
    model.delete()
    assert model.super_delete_called


def test_governance_still_refuses_before_ownership_is_consulted():
    """Ownership widens what may be deleted; it never overrides the gate."""
    model = _model(cf={managed.FORWARD_MANAGED_KEY: True}, allow_delete=False)
    model.delete()
    assert not model.super_delete_called


def test_per_model_gate_is_honoured_alongside_ownership():
    owned = {managed.FORWARD_MANAGED_KEY: True}
    permitted = _Model(_FakeObj(owned), _Adapter(delete_allowed_models={"device"}), "device")
    permitted.delete()
    assert permitted.super_delete_called

    excluded = _Model(_FakeObj(owned), _Adapter(delete_allowed_models={"interface"}), "device")
    excluded.delete()
    assert not excluded.super_delete_called


def test_an_unreadable_object_is_kept():
    """If the object cannot be fetched, keeping it is the safe answer."""

    class _Unfetchable(_Model):
        def get_from_db(self):
            raise RuntimeError("gone")

    model = _Unfetchable(_FakeObj(), _Adapter(allow_delete=True))
    model.delete()
    assert not model.super_delete_called


# -- mark_inactive parity ----------------------------------------------------


class _StatusObj(_FakeObj):
    """An object that carries a status, as the mark_inactive slices do."""

    def __init__(self, cf=None):
        super().__init__(cf)
        self.status = "Active"

    def validated_save(self):
        self.saved = True


def test_mark_inactive_changes_status_instead_of_deleting(monkeypatch):
    """Six registry slices declare mark_inactive; it must not become a delete."""
    import forward_nautobot.integrations.forward.contrib_sync as cs

    monkeypatch.setattr(cs, "_ensure_status_with_content_types", lambda name, models: name)

    owned = {managed.FORWARD_MANAGED_KEY: True}
    obj = _StatusObj(owned)
    model = _Model(obj, _Adapter(allow_delete=True), "device")
    model.adapter.mark_inactive_models = {"device"}

    model.delete()
    assert not model.super_delete_called, "mark_inactive must not delete"
    assert obj.status == "Inactive"
    assert not obj.deleted


def test_mark_inactive_only_applies_to_the_models_that_declare_it():
    owned = {managed.FORWARD_MANAGED_KEY: True}
    obj = _StatusObj(owned)
    model = _Model(obj, _Adapter(allow_delete=True), "device")
    model.adapter.mark_inactive_models = {"interface"}  # not this one

    model.delete()
    assert model.super_delete_called


def test_an_object_without_a_status_falls_through_to_delete():
    """Not every model has a status; those can only be deleted or kept."""
    owned = {managed.FORWARD_MANAGED_KEY: True}
    model = _Model(_FakeObj(owned), _Adapter(allow_delete=True), "manufacturer")
    model.adapter.mark_inactive_models = {"manufacturer"}

    model.delete()
    assert model.super_delete_called


def test_a_failed_mark_never_becomes_a_delete(monkeypatch):
    """If the status write fails, keeping the object is the safe outcome."""
    import forward_nautobot.integrations.forward.contrib_sync as cs

    def _boom(name, models):
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(cs, "_ensure_status_with_content_types", _boom)

    owned = {managed.FORWARD_MANAGED_KEY: True}
    model = _Model(_StatusObj(owned), _Adapter(allow_delete=True), "device")
    model.adapter.mark_inactive_models = {"device"}

    model.delete()
    assert not model.super_delete_called


def test_registry_policy_drives_which_models_are_marked():
    """The map is derived from the registry, not maintained separately."""
    import forward_nautobot.integrations.forward.contrib_sync as cs
    from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS

    class _FakeModel:
        _modelname = "device"

        class _model:
            class _meta:
                label_lower = "dcim.device"

    class _Target:
        device = _FakeModel

    names = cs._mark_inactive_modelnames(_Target())
    expected = {
        m.nautobot_scope for m in CORE_MODEL_MAPPINGS if m.missing_row_policy == "mark_inactive"
    }
    assert "dcim.device" in expected
    assert names == {"device"}
