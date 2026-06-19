"""Forward Networks SSoT integration for Nautobot."""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from nautobot.apps import NautobotAppConfig
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    NautobotAppConfig = object

from .navigation import menu

if TYPE_CHECKING:  # pragma: no cover - import-time hinting only
    from .forms import (
        DELETE_POLICY_CHOICES,
        FORWARD_PROFILE_FORM_FIELDS,
        ForwardConnectionProfileForm,
    )
    from .models import (
        ForwardConnectionProfile,
        ForwardConnectionProfileRecord,
        ForwardPluginConfiguration,
    )


class ForwardNautobotConfig(NautobotAppConfig):
    name = "forward_nautobot"
    verbose_name = "Forward Networks SSoT"
    description = "Sync Forward Networks data into Nautobot through the SSoT app."
    version = "0.2.0"
    author = "Forward Networks"
    author_email = "support@forwardnetworks.com"
    base_url = "forward"
    min_version = "3.1.0"
    home_view_name = "home"
    config_view_name = "configuration"
    jobs = "integrations.forward.jobs"
    menu = menu


config = ForwardNautobotConfig


def __getattr__(name: str):
    if name in {
        "ForwardConnectionProfile",
        "ForwardConnectionProfileRecord",
        "ForwardConnectionProfileForm",
        "ForwardPluginConfiguration",
        "FORWARD_PROFILE_FORM_FIELDS",
        "DELETE_POLICY_CHOICES",
    }:
        from .forms import DELETE_POLICY_CHOICES as _DELETE_POLICY_CHOICES
        from .forms import FORWARD_PROFILE_FORM_FIELDS as _FORWARD_PROFILE_FORM_FIELDS
        from .forms import ForwardConnectionProfileForm as _ForwardConnectionProfileForm
        from .models import ForwardConnectionProfile as _ForwardConnectionProfile
        from .models import ForwardConnectionProfileRecord as _ForwardConnectionProfileRecord
        from .models import ForwardPluginConfiguration as _ForwardPluginConfiguration

        globals().update(
            {
                "ForwardConnectionProfile": _ForwardConnectionProfile,
                "ForwardConnectionProfileRecord": _ForwardConnectionProfileRecord,
                "ForwardConnectionProfileForm": _ForwardConnectionProfileForm,
                "ForwardPluginConfiguration": _ForwardPluginConfiguration,
                "FORWARD_PROFILE_FORM_FIELDS": _FORWARD_PROFILE_FORM_FIELDS,
                "DELETE_POLICY_CHOICES": _DELETE_POLICY_CHOICES,
            }
        )
        return globals()[name]
    raise AttributeError(name)


__all__ = [
    "ForwardConnectionProfile",
    "ForwardConnectionProfileRecord",
    "ForwardConnectionProfileForm",
    "ForwardNautobotConfig",
    "ForwardPluginConfiguration",
    "FORWARD_PROFILE_FORM_FIELDS",
    "DELETE_POLICY_CHOICES",
    "config",
    "menu",
]
