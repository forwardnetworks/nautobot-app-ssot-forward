"""REST API endpoints for Forward Field Integration.

Loaded only inside a running Nautobot (DRF present). Provides machine-readable
health / status / support-bundle endpoints for monitoring and automation — the
data the HTML diagnostic pages render, without scraping HTML, and never exposing a
stored credential.
"""

from __future__ import annotations

import json

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from forward_nautobot import ForwardNautobotConfig
from forward_nautobot.integrations.forward.support import grade_support_bundle
from forward_nautobot.models import ForwardPluginConfiguration
from forward_nautobot.views import _iter_persisted_profile_records, _select_profile_for_bundle


def _summary() -> dict:
    profiles = _iter_persisted_profile_records()
    return ForwardPluginConfiguration(default_profile_name="", profiles=profiles).status_summary()


def _nautobot_version() -> str:
    try:
        from nautobot import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - defensive
        return "unknown"


class ForwardHealthAPIView(APIView):
    """GET → a compact liveness/health verdict for monitoring probes."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        summary = _summary()
        profile_count = len(summary.get("profiles", []))
        needs_attention = int(summary.get("needs_attention_profiles", 0) or 0)
        last_failure = str(summary.get("last_failure") or "")
        if profile_count == 0:
            status = "unconfigured"
        elif last_failure or needs_attention:
            status = "degraded"
        else:
            status = "healthy"
        return Response(
            {
                "status": status,
                "healthy": status == "healthy",
                "plugin_version": ForwardNautobotConfig.version,
                "nautobot_version": _nautobot_version(),
                "profiles": profile_count,
                "ready_profiles": int(summary.get("ready_profiles", 0) or 0),
                "needs_attention_profiles": needs_attention,
                "last_run": summary.get("last_run") or "not recorded",
                "last_failure": last_failure or None,
            }
        )


class ForwardStatusAPIView(APIView):
    """GET → the full per-profile operational status summary as JSON."""

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(_summary())


class ForwardSupportBundleAPIView(APIView):
    """GET → the last persisted (redacted) support bundle + its offline grade.

    ``?profile=<name>`` selects a profile; the default profile is used otherwise.
    ``?grade=false`` omits the grade.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        requested = str(request.query_params.get("profile") or "").strip()
        profile = _select_profile_for_bundle(_iter_persisted_profile_records(), requested)
        payload = getattr(profile, "last_support_bundle_json", "") if profile is not None else ""
        if not payload:
            return Response({"detail": "No support bundle has been captured yet."}, status=404)
        bundle = json.loads(payload)
        body = {"profile": getattr(profile, "name", ""), "bundle": bundle}
        if str(request.query_params.get("grade") or "true").lower() != "false":
            body["grade"] = grade_support_bundle(bundle)
        return Response(body)
