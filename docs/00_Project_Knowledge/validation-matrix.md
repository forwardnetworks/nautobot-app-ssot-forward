# Validation Matrix

Run the smallest gate that proves the change, then run the release gate before
publishing.

| Change type | Required validation |
| --- | --- |
| Documentation only | `python scripts/check_harness.py`, `python -m pytest -q tests/test_release_workflow.py` |
| Forward API client change | `python -m pytest -q tests/test_client.py tests/test_runner.py`, `python -m pytest -q tests/test_support_grader.py` |
| NQE contract or registry change | `python scripts/check_query_contracts.py`, `python scripts/generate_contract_diff_report.py --baseline-ref HEAD~1 --output dist/contract-diff-report.json`, `python -m pytest -q tests/test_queries.py tests/test_registry.py` |
| Planner or write-path change | `python -m pytest -q tests/test_planner.py tests/test_write_path.py tests/test_write_executor.py tests/test_target_adapter.py` |
| SSoT job or Nautobot UI change | `python -m pytest -q tests/test_plugin.py tests/test_views.py tests/test_nautobot_job_refresh.py` |
| Security or credential handling change | `python -m pytest -q tests/test_configuration.py tests/test_release_gates.py`, `python scripts/check_sensitive_content.py --all-history` |
| Release workflow or packaging change | `python scripts/ci_local.py`, then confirm GitHub CI is green on `main` |
| Device-filter or query-publication change | publisher unit tests, filtered-delete safety tests, exact committed-source audit, async full-query live smoke, strict NQE-diff live smoke |

## Release Gate

```bash
python scripts/ci_local.py
```

The local CI mirror runs the same core checks as GitHub CI:

- sensitive-content history scan
- harness check
- release-state check
- query-contract check
- contract-diff report generation
- non-live pytest suite
- build
- wheel-content check
- disposable PostgreSQL/Redis stacks for Nautobot 3.1.8 and 3.2.2 in GitHub CI

The non-live pytest gate runs with `FORWARD_STRICT_NO_SKIPS=1`; any skipped
non-integration test fails the release gate.

## Live Gate

Live Forward tests are opt-in because they require customer-approved credentials
and a prepared validation NQE folder.

```bash
FORWARD_LIVE_BASE_URL=https://fwd.app \
FORWARD_LIVE_USERNAME=<user> \
FORWARD_LIVE_PASSWORD=<password> \
FORWARD_LIVE_NETWORK_ID=<network-id> \
python -m pytest -q -m integration
```

Use `FORWARD_LIVE_ASYNC_QUERY_PATH` only when the target host publishes a
different read-only NQE path for async transport smoke tests.

Before a release, publish or audit the bundle with `forward_publish_queries --fail-on-gap`.
The live proof must show all packaged paths matched exact committed source, one full run used
async query-ID execution, and a two-snapshot run used `nqe-diffs` without fallback.

## Non-Negotiable Release Checks

- No live customer credentials, tenant IDs, network IDs, snapshot IDs, or
  screenshots in source or artifacts.
- No static demo data promoted as live import evidence.
- No skipped non-integration tests in the release gate.
- Support bundles must have an external redacted form.
- The SSoT DataSource class path must stay non-empty:
  `forward_nautobot.integrations.forward.jobs.ForwardInventoryDataSource`.
- Default CI excludes live integration tests; live validation is a separate,
  credentialed gate.
