"""Forward Networks Nautobot plugin."""

try:
    from nautobot.apps import NautobotAppConfig
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
    NautobotAppConfig = object

from .navigation import menu


class ForwardNautobotConfig(NautobotAppConfig):
    name = "forward_nautobot"
    verbose_name = "Forward Nautobot Plugin"
    description = "Sync Forward Networks data into Nautobot."
    version = "0.1.0"
    author = "Forward Networks"
    author_email = "support@forwardnetworks.com"
    base_url = "forward"
    min_version = "3.1.0"
    home_view_name = "home"
    config_view_name = "configuration"
    jobs = "integrations.forward.jobs"
    menu = menu


config = ForwardNautobotConfig
