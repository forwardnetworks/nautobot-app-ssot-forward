"""URL routes for the Forward Networks SSoT integration."""

try:
    from django.urls import path
except ModuleNotFoundError:  # pragma: no cover - local compatibility import path
    def path(route, view, name=None):  # type: ignore[no-redef]
        return (route, view, name)

from .views import ForwardConfigurationView
from .views import ForwardHomeView
from .views import ForwardDiagnosticsView
from .views import ForwardSliceDetailView
from .views import ForwardStatusView


urlpatterns = [
    path("", ForwardHomeView.as_view(), name="home"),
    path("diagnostics/", ForwardDiagnosticsView.as_view(), name="diagnostics"),
    path("status/", ForwardStatusView.as_view(), name="status"),
    path("configuration/", ForwardConfigurationView.as_view(), name="configuration"),
    path("slices/<slug:model_slug>/", ForwardSliceDetailView.as_view(), name="slice-detail"),
]
