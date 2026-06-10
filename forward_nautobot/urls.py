"""URL routes for the Forward Nautobot plugin scaffold."""

try:
    from django.urls import path
except ModuleNotFoundError:  # pragma: no cover - local scaffold import path
    def path(route, view, name=None):  # type: ignore[no-redef]
        return (route, view, name)

from .views import ForwardConfigurationView
from .views import ForwardHomeView


urlpatterns = [
    path("", ForwardHomeView.as_view(), name="home"),
    path("configuration/", ForwardConfigurationView.as_view(), name="configuration"),
]

