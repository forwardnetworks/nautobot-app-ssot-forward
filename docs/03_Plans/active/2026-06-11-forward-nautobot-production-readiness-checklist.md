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
| Sanitized fixture coverage | `tests/fixtures/forward_ingestion_sample.json`, `tests/test_fixture_ingestion.py`, `tests/test_dry_run.py` | done |
| Query contract drift checks | `scripts/check_query_contracts.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | done |
| Wheel/build/release gates | `scripts/check_wheel_contents.py`, `scripts/check_release_state.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` | done |
| User-facing SSoT wording | `README.md`, `ARCHITECTURE.md`, `forward_nautobot/views.py` | done |
| Sync log object linkage | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` | done |
| Persistent SSoT profile selection | `forward_nautobot/forms.py`, `forward_nautobot/models.py`, `forward_nautobot/views.py` | pending |
| Deeper NautobotAdapter integration | `forward_nautobot/integrations/forward/adapters.py`, `forward_nautobot/integrations/forward/write_executor.py` | pending |

## Remaining Gaps

1. Move runtime configuration closer to an explicit SSoT profile selection flow so credentials and
   defaults are not only job arguments.
2. Replace the current planned-target adapter path with deeper Nautobot-adapter integration where it
   improves write fidelity and log attribution.

## Exit Criteria

Production quality is not complete until the checklist above is entirely done, the repo gates pass,
and the SSoT sync path has fixture-based regression coverage for the supported slice set.
