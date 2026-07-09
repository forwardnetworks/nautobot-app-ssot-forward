from __future__ import annotations

from types import SimpleNamespace

from forward_nautobot.integrations.forward.metrics import parse_epoch, render_prometheus


def _rec(name, *, ready=True, last_run_at="", last_failure=""):
    return SimpleNamespace(
        name=name, write_ready=ready, last_run_at=last_run_at, last_failure=last_failure
    )


def test_parse_epoch_handles_iso_and_garbage():
    assert parse_epoch("2026-07-09T00:00:00+00:00") is not None
    assert parse_epoch("2026-07-09T00:00:00") is not None  # naive -> assumed UTC
    assert parse_epoch("") is None
    assert parse_epoch("not-a-date") is None


def test_render_counts_and_readiness():
    out = render_prometheus(
        [_rec("a", ready=True), _rec("b", ready=False)],
        now_epoch=1_800_000_000.0,
    )
    assert "forward_profiles_total 2" in out
    assert "forward_profiles_ready 1" in out
    assert "forward_profiles_needs_attention 1" in out
    # HELP/TYPE lines present for a metric
    assert "# TYPE forward_profiles_total gauge" in out


def test_render_per_profile_failure_and_timestamp():
    out = render_prometheus(
        [_rec("prod", last_run_at="2026-07-09T00:00:00+00:00", last_failure="boom")],
        now_epoch=parse_epoch("2026-07-09T00:01:00+00:00"),
    )
    assert 'forward_profile_last_run_failed{profile="prod"} 1' in out
    assert 'forward_profile_last_run_age_seconds{profile="prod"} 60' in out


def test_render_omits_timestamp_when_never_run_and_escapes_labels():
    out = render_prometheus([_rec('we"ird', last_run_at="")], now_epoch=1_800_000_000.0)
    assert 'forward_profile_last_run_failed{profile="we\\"ird"} 0' in out
    assert "forward_profile_last_run_timestamp_seconds{" not in out  # never ran


def test_render_includes_ssot_count_when_provided():
    out = render_prometheus([], now_epoch=1_800_000_000.0, ssot_sync_count=7)
    assert "forward_ssot_syncs_total 7" in out
