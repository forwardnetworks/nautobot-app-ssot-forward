from __future__ import annotations

import contextlib
import importlib
import os
import sys
import types
from types import SimpleNamespace
from collections import namedtuple

import pytest


def _load_refresh_contract():
    try:
        import django
    except ModuleNotFoundError as exc:  # pragma: no cover - local shell without Django deps
        pytest.skip(f"Django is required for the Nautobot job refresh regression test: {exc}")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nautobot_config")

    try:
        django.setup()
        from nautobot.extras import utils as nautobot_utils
    except Exception as exc:  # pragma: no cover - local shell without Nautobot deps
        pytest.skip(f"Nautobot job refresh regression test is unavailable: {exc}")

    return nautobot_utils


def _import_forward_job_class(monkeypatch):
    base_stub = types.ModuleType("nautobot.apps.models")
    base_stub.BaseModel = type("BaseModel", (), {})

    jobs_stub = types.ModuleType("nautobot.apps.jobs")

    class _Var:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class BooleanVar(_Var):
        pass

    class ChoiceVar(_Var):
        pass

    class IntegerVar(_Var):
        pass

    class StringVar(_Var):
        pass

    def register_jobs(*_jobs):
        return None

    jobs_stub.BooleanVar = BooleanVar
    jobs_stub.ChoiceVar = ChoiceVar
    jobs_stub.IntegerVar = IntegerVar
    jobs_stub.StringVar = StringVar
    jobs_stub.register_jobs = register_jobs

    ssot_base_stub = types.ModuleType("nautobot_ssot.jobs.base")
    ssot_base_stub.DataMapping = namedtuple(
        "DataMapping",
        ["source_name", "source_url", "target_name", "target_url"],
    )

    class DataSource:  # type: ignore[too-many-ancestors]
        logger = None
        job_result = None

    ssot_base_stub.DataSource = DataSource

    monkeypatch.delitem(sys.modules, "forward_nautobot.models", raising=False)
    monkeypatch.delitem(sys.modules, "forward_nautobot.integrations.forward.jobs", raising=False)
    monkeypatch.setitem(sys.modules, "nautobot.apps.models", base_stub)
    monkeypatch.setitem(sys.modules, "nautobot.apps.jobs", jobs_stub)
    monkeypatch.setitem(sys.modules, "nautobot_ssot.jobs.base", ssot_base_stub)

    module = importlib.import_module("forward_nautobot.integrations.forward.jobs")
    return module.ForwardInventoryDataSource


class _NullQuerySet:
    def exclude(self, **_kwargs):
        return self

    def values_list(self, *_args, **_kwargs):
        return []


class _FakeJobQueueManager:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def get_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(name=kwargs["name"]), True


class _FakeJobQueue:
    objects = _FakeJobQueueManager()


class _FakeJobModel:
    def __init__(self, **fields):
        self.__dict__.update(fields)
        self.job_queues = SimpleNamespace(set=self._set_job_queues)
        self.saved = False
        self._job_queues: tuple[object, ...] = ()

    def _set_job_queues(self, queues):
        self._job_queues = tuple(queues)

    def save(self):
        self.saved = True


class _FakeJobModelManager:
    def __init__(self):
        self.filter_calls: list[dict[str, object]] = []
        self.get_or_create_calls: list[dict[str, object]] = []

    def filter(self, **kwargs):
        self.filter_calls.append(kwargs)
        return _NullQuerySet()

    def get_or_create(self, **kwargs):
        self.get_or_create_calls.append(kwargs)
        defaults = dict(kwargs.get("defaults", {}))
        defaults["module_name"] = kwargs["module_name"]
        defaults["job_class_name"] = kwargs["job_class_name"]
        defaults["grouping"] = kwargs["defaults"]["grouping"]
        defaults["name"] = kwargs["defaults"]["name"]
        defaults["job_queues_override"] = False
        model = _FakeJobModel(**defaults)
        model.module_name = kwargs["module_name"]
        model.job_class_name = kwargs["job_class_name"]
        model.name_override = False
        model.job_queues_override = False
        model.enabled = kwargs["defaults"]["enabled"]
        model.installed = kwargs["defaults"]["installed"]
        model.is_job_hook_receiver = kwargs["defaults"]["is_job_hook_receiver"]
        model.is_job_button_receiver = kwargs["defaults"]["is_job_button_receiver"]
        model.read_only = kwargs["defaults"]["read_only"]
        model.supports_dryrun = kwargs["defaults"]["supports_dryrun"]
        model.default_job_queue = kwargs["defaults"]["default_job_queue"]
        model.is_singleton = kwargs["defaults"]["is_singleton"]
        return model, True


def test_forward_job_refresh_contract_smoke(monkeypatch):
    nautobot_utils = _load_refresh_contract()
    forward_job_class = _import_forward_job_class(monkeypatch)

    monkeypatch.setattr(
        nautobot_utils.transaction,
        "atomic",
        lambda: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        nautobot_utils.settings,
        "CELERY_TASK_DEFAULT_QUEUE",
        "default",
        raising=False,
    )

    job_model_class = SimpleNamespace(objects=_FakeJobModelManager())
    job_model, created = nautobot_utils.refresh_job_model_from_job_class(
        job_model_class,
        forward_job_class,
        _FakeJobQueue,
    )

    assert created is True
    assert job_model.grouping == forward_job_class.grouping
    assert job_model.name == forward_job_class.name
    assert job_model.description == forward_job_class.description
    assert job_model.console_log_default is forward_job_class.console_log_default
    assert job_model.dryrun_default is forward_job_class.dryrun_default
    assert job_model.hidden is forward_job_class.hidden
    assert job_model.soft_time_limit == forward_job_class.soft_time_limit
    assert job_model.time_limit == forward_job_class.time_limit
    assert job_model.has_sensitive_variables is forward_job_class.has_sensitive_variables
    assert job_model.is_singleton is forward_job_class.is_singleton
    assert job_model.saved is True
    assert job_model._job_queues[0].name == "default"

    for field_name in nautobot_utils.JOB_OVERRIDABLE_FIELDS:
        assert hasattr(forward_job_class, field_name), field_name
