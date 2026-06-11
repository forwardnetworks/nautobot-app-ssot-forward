"""URL routes for the Forward Networks SSoT integration."""

try:
    from django.urls import path
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    def path(route, view, name=None):  # type: ignore[no-redef]
        return (route, view, name)

from .views import ForwardConfigurationView
from .views import ForwardHomeView


urlpatterns = [
    path("", ForwardHomeView.as_view(), name="home"),
    path("configuration/", ForwardConfigurationView.as_view(), name="configuration"),
]
