"""Navigation for the Forward Networks SSoT integration."""

try:
    from django.utils.translation import gettext_lazy as _
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path

    def _(value):
        return value


try:
    from nautobot.apps.ui import PluginMenu, PluginMenuButton, PluginMenuItem
except Exception:  # pragma: no cover - local compatibility import path
    from dataclasses import dataclass

    @dataclass(slots=True)
    class PluginMenuButton:  # type: ignore[too-many-ancestors]
        link: str
        title: str
        icon_class: str = ""
        permissions: tuple[str, ...] = ()

    @dataclass(slots=True)
    class PluginMenuItem:  # type: ignore[too-many-ancestors]
        link: str
        link_text: str
        buttons: tuple[PluginMenuButton, ...] = ()
        permissions: tuple[str, ...] = ()

    @dataclass(slots=True)
    class PluginMenu:  # type: ignore[too-many-ancestors]
        label: str
        icon_class: str = ""
        groups: tuple[tuple[str, tuple[PluginMenuItem, ...]], ...] = ()


overview = PluginMenuItem(
    link="plugins:forward_nautobot:home",
    link_text=_("Overview"),
)

diagnostics = PluginMenuItem(
    link="plugins:forward_nautobot:diagnostics",
    link_text=_("Diagnostics"),
)

status = PluginMenuItem(
    link="plugins:forward_nautobot:status",
    link_text=_("Status"),
)

configuration = PluginMenuItem(
    link="plugins:forward_nautobot:configuration",
    link_text=_("Configuration"),
)

menu = PluginMenu(
    label="Forward Networks",
    icon_class="mdi mdi-cloud-sync",
    groups=(
        ("SSoT", (overview, diagnostics, status)),
        ("Configuration", (configuration,)),
    ),
)
