# Forward Nautobot Future Improvements

## Goal

Define the remaining work that takes the current SSoT integration from release-ready to the highest
practical production quality for this repo.

## Baseline

The repo already has the production core in place:

- a single SSoT sync job
- bundled Forward NQE contracts only
- dry-run and non-dry-run execution paths
- sync diff persistence in Nautobot SSoT
- support-bundle capture and redaction
- query identity resolution and commit pinning for repository-path queries
- sanitized fixture-backed regression coverage
- release and packaging gates
- hydrated Nautobot target-state loading for the current supported slices

## Architectural Transfer

The most useful hardening patterns to keep carrying forward are contractual:

| Pattern | Why it matters here | Evidence to add or keep |
| --- | --- | --- |
| Query identity resolution | Treat inline NQE as a valid fallback, but prefer repository-path or direct query-ID execution so the run can resolve a live query ID and commit ID and become eligible for `nqe-diffs`. | `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/integrations/forward/models.py`, `tests/test_client.py`, `tests/test_runner.py` |
| Bundled query drift checks | Keep the shipped query text, field contract, and contract version checked in CI so query shape changes are visible before release. | `forward_nautobot/integrations/forward/queries/`, `scripts/check_query_contracts.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` |
| Canonical support bundles | Keep the full troubleshooting payload and the redacted shareable view in sync so operators can hand off evidence safely. | `forward_nautobot/integrations/forward/support.py`, `forward_nautobot/views.py`, `tests/test_support.py` |
| Replayable dry runs | Preserve enough fixture and bundle structure to reproduce a failure locally without live credentials. | `forward_nautobot/management/commands/forward_dry_run.py`, `forward_nautobot/integrations/forward/dry_run.py`, `README.md` |
| Request pressure controls | Make every Forward request explicit and bounded so the client does not create avoidable load. | `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/integrations/forward/planner.py` |
| Release hygiene gates | Keep wheel contents, release state, and sensitive-content checks deterministic and visible in CI. | `scripts/check_wheel_contents.py`, `scripts/check_release_state.py`, `scripts/check_sensitive_content.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` |

## Roadmap

| Tranche | Outcome | Evidence to add or keep |
| --- | --- | --- |
| Expand object lookup coverage | Add `lookup_object()` support for any new Nautobot object types introduced by future slices. | `forward_nautobot/integrations/forward/jobs.py`, `tests/test_plugin.py` |
| Expand ingestion regression coverage | Grow sanitized fixture coverage and live subset checks as more slices are enabled, including the supported IPAM and asset slices. | `tests/fixtures/`, `tests/test_fixture_ingestion.py`, `tests/test_live_ingestion.py` |
| Improve replay and support workflows | Make issue reporting, query identity validation, support-bundle handling, and replay workflows easier for operators. | `forward_nautobot/integrations/forward/support.py`, `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/management/commands/forward_dry_run.py`, `README.md` |
| Enable query-ID-backed NQE diffs | Prefer `nqe-diffs` for repository-path and direct query-ID runs when the snapshot pair is known; keep inline query text as the fallback for one-off or ad hoc runs. | `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/integrations/forward/planner.py`, `forward_nautobot/integrations/forward/runner.py`, `tests/test_client.py`, `tests/test_runner.py` |
| Increase target-state fidelity | Keep deep Nautobot target hydration aligned with real ORM state as the write model grows. | `forward_nautobot/integrations/forward/adapters.py`, `forward_nautobot/integrations/forward/planner.py`, `tests/test_target_adapter.py`, `tests/test_planner.py` |
| Reduce query load and request pressure | Minimize unnecessary Forward API calls, avoid repeated repository lookups, keep request shapes explicit and efficient, and scope child queries from already loaded parent keys when possible. | `forward_nautobot/integrations/forward/client.py`, `forward_nautobot/integrations/forward/planner.py`, query contracts |
| Tighten contract governance | Keep bundled contracts versioned and detect drift quickly in CI. | `forward_nautobot/integrations/forward/queries/`, `scripts/check_query_contracts.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` |
| Strengthen release automation | Keep wheel contents, release state, and artifact publishing deterministic. | `scripts/check_wheel_contents.py`, `scripts/check_release_state.py`, `.github/workflows/ci.yml`, `.github/workflows/release.yml` |
| Improve operator UX | Surface clearer readiness, status, and failure context in the UI and job output. | `forward_nautobot/views.py`, `forward_nautobot/jobs.py`, `forward_nautobot/integrations/forward/jobs.py`, `forward_nautobot/integrations/forward/support.py` |

## 100% Production Quality

For this repo, "100% production quality" means:

1. Every supported slice has a tested, bundled contract and a clear target-state mapping.
2. The SSoT job remains the only registered sync job.
3. Query inputs remain contract-stable and raw, with no Python-side normalization of source fields.
4. Support, replay, and query-identity artifacts are safe to share and easy to act on.
5. The repo gates stay green on build, wheel contents, contract drift, harness validation, release state, and sensitive-content checks.
6. The roadmap above is the active source of truth for any new tranche of hardening work.

## Out of Scope

- Reintroducing legacy preview/sync jobs
- Moving field reshaping into Python instead of NQE
- Adding undocumented customer-specific references

## Next Step

Treat the roadmap table above as the ordering for any future tranche after the current release-ready
baseline.
