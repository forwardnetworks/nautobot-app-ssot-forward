from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    import forward_nautobot.api.views as api_views

    _HAVE_DRF = True
except Exception:  # pragma: no cover - rest_framework/nautobot absent locally
    api_views = None
    _HAVE_DRF = False


pytestmark = pytest.mark.skipif(not _HAVE_DRF, reason="REST API requires rest_framework/nautobot")


def _fake_request(**params):
    return SimpleNamespace(query_params=params)


def test_health_reports_healthy(monkeypatch):
    monkeypatch.setattr(
        api_views,
        "_summary",
        lambda: {"profiles": [{"name": "p"}], "needs_attention_profiles": 0, "last_failure": ""},
    )
    resp = api_views.ForwardHealthAPIView().get(_fake_request())
    assert resp.data["status"] == "healthy"
    assert resp.data["healthy"] is True
    assert "plugin_version" in resp.data


def test_health_degraded_on_failure(monkeypatch):
    monkeypatch.setattr(
        api_views,
        "_summary",
        lambda: {
            "profiles": [{"name": "p"}],
            "needs_attention_profiles": 0,
            "last_failure": "boom",
        },
    )
    resp = api_views.ForwardHealthAPIView().get(_fake_request())
    assert resp.data["status"] == "degraded"
    assert resp.data["healthy"] is False


def test_health_unconfigured_without_profiles(monkeypatch):
    monkeypatch.setattr(api_views, "_summary", lambda: {"profiles": []})
    resp = api_views.ForwardHealthAPIView().get(_fake_request())
    assert resp.data["status"] == "unconfigured"


def test_support_bundle_404_when_none(monkeypatch):
    monkeypatch.setattr(api_views, "_iter_persisted_profile_records", lambda: ())
    monkeypatch.setattr(api_views, "_select_profile_for_bundle", lambda profiles, name: None)
    resp = api_views.ForwardSupportBundleAPIView().get(_fake_request())
    assert resp.status_code == 404


def test_support_bundle_returns_bundle_and_grade(monkeypatch):
    profile = SimpleNamespace(
        name="primary",
        last_support_bundle_json='{"failure_classification":"clean","row_count":5,"diff_summary":{"create":5}}',
    )
    monkeypatch.setattr(api_views, "_iter_persisted_profile_records", lambda: (profile,))
    monkeypatch.setattr(api_views, "_select_profile_for_bundle", lambda profiles, name: profile)
    resp = api_views.ForwardSupportBundleAPIView().get(_fake_request())
    assert resp.data["profile"] == "primary"
    assert resp.data["bundle"]["row_count"] == 5
    assert resp.data["grade"]["status"] == "pass"
