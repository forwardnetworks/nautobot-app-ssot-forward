"""REST API routes for Forward Field Integration.

Nautobot mounts these under ``/api/plugins/forward/``.
"""

from django.urls import path

from forward_nautobot.api.views import (
    ForwardHealthAPIView,
    ForwardStatusAPIView,
    ForwardSupportBundleAPIView,
)

app_name = "forward_nautobot-api"

urlpatterns = [
    path("health/", ForwardHealthAPIView.as_view(), name="health"),
    path("status/", ForwardStatusAPIView.as_view(), name="status"),
    path("support-bundle/", ForwardSupportBundleAPIView.as_view(), name="support-bundle"),
]
