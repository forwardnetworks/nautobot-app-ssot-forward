"""Navigation for the Forward Nautobot plugin."""

try:
    from django.utils.translation import gettext as _
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    def _(value):
        return value

try:
    from nautobot.apps.ui import PluginMenu
    from nautobot.apps.ui import PluginMenuButton
    from nautobot.apps.ui import PluginMenuItem
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
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

configuration = PluginMenuItem(
    link="plugins:forward_nautobot:configuration",
    link_text=_("Configuration"),
)

menu = PluginMenu(
    label="Forward Networks",
    icon_class="mdi mdi-cloud-sync",
    groups=(
        ("SSoT", (overview,)),
        ("Configuration", (configuration,)),
    ),
)
