# Forward Nautobot Production Readiness Checklist

## Goal

Map each SSoT capability to concrete repository evidence and isolate the remaining work needed to
reach full production quality.

## Scope

- SSoT sync job registration and execution flow
- bundled-contract query inputs
- dry-run safety and non-dry-run persistence
- support-bundle capture and redaction
- sanitized fixture coverage
- build and release gates

## Checklist

| Capability | Repo evidence | Status |
| --- | --- | --- |
| Single registered SSoT sync job | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` | done |
| Bundled NQE inputs only | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py`, `forward_nautobot/integrations/forward/planner.py` | done |
| Dry-run safety gate | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py`, `tests/test_dry_run.py` | done |
| Non-dry-run write execution | `forward_nautobot/integrations/forward/jobs.py`, `forward_nautobot/integrations/forward/write_executor.py`, `tests/test_plugin.py` | done |
| Sync diff persistence | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` | done |
| Support-bundle capture and redaction | `forward_nautobot/integrations/forward/support.py`, `tests/test_support.py` | done |
| Resolved query identity and commit pinning | `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/integrations/forward/models.py`, `tests/test_client.py` | done |
| Sanitized fixture coverage | `tests/fixtures/forward_ingestion_sample.json`, `tests/test_fixture_ingestion.py`, `tests/test_dry_run.py` | done |
| Query contract drift checks | `scripts/check_query_contracts.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | done |
| Wheel/build/release gates | `scripts/check_wheel_contents.py`, `scripts/check_release_state.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | done |
| User-facing SSoT wording | `README.md`, `ARCHITECTURE.md`, `forward_nautobot/views.py` | done |
| Sync log object linkage | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` | done |
| Persistent SSoT profile selection | `forward_nautobot/forms.py`, `forward_nautobot/models.py`, `forward_nautobot/views.py`, `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` | done |
| Deeper NautobotAdapter integration | `forward_nautobot/integrations/forward/adapters.py`, `forward_nautobot/integrations/forward/planner.py`, `tests/test_target_adapter.py`, `tests/test_planner.py` | done |

## Next Tranche

1. Increase target-state fidelity as additional write-model slices are enabled.
2. Expand ingestion tests around the SSoT job surface as new Nautobot object types are introduced.
3. Use [`2026-06-11-forward-nautobot-future-improvements.md`](./2026-06-11-forward-nautobot-future-improvements.md) as the canonical ordering for later hardening work.

## Exit Criteria

Current scope is production-ready once the repo gates pass and the SSoT sync path has
fixture-based regression coverage for the supported slice set.

For post-baseline hardening, follow the roadmap in
[`2026-06-11-forward-nautobot-future-improvements.md`](./2026-06-11-forward-nautobot-future-improvements.md).
