# Forward Nautobot Scope Expansion

## Purpose

Expand the plugin scope only where it improves production readiness, supportability, and contract confidence.

The goal is to harden the implementation boundary, not to broaden the contract surface or add normalization logic in Python.

## Status

Implemented and verified.

The codebase now includes the scope-expansion hardening points described below, with regression coverage for live ingestion, contract validation, support-bundle redaction, retry behavior, pagination safety, and query efficiency.

## Expand In Scope

| Area | What to Expand | Why |
| --- | --- | --- |
| Live ingestion coverage | Add more representative sanitized fixtures and live ingestion checks | Proves the plugin works beyond one dataset and catches contract drift earlier |
| Contract validation | Add stronger assertions on exact NQE output shape, types, and versions | Protects the raw-contract rule and makes breaking changes visible |
| Failure handling | Cover partial fetches, auth failures, stale snapshots, and retry behavior | Production failures usually happen in the edge cases |
| Supportability | Improve support bundles, redaction, and replay context | Makes issue reports actionable without another round trip |
| Release gates | Keep CI, packaging, and wheel contents under test | Prevents regressions from reaching users |
| Query efficiency | Reduce unnecessary queries and prefer parameterized requests when possible | Lowers load on the Forward service and keeps runs predictable |

## Keep Out Of Scope

| Area | Why Not |
| --- | --- |
| Python-side normalization | Contract shaping belongs in NQE |
| Broad UI redesign | Adds risk without improving the ingestion boundary |
| New slice explosion | Scope should widen only after current slices are stable |
| Customer-specific logic | The repo should stay customer-neutral |
| Hidden inference rules | Matching and policy should stay explicit |

## Working Rule

1. Keep the Python layer raw.
2. Push field shaping into NQE.
3. Expand validation and operational surfaces before expanding model breadth.
4. Add each new slice or capability only with contract tests and fixture coverage.

## Acceptance Signal

The scope has been expanded correctly when:

- more real-world failure modes are covered by tests,
- the raw contract is still enforced by the plugin,
- support evidence is easier to collect and share, and
- the Forward backend sees fewer avoidable or redundant requests.

## Verification

| Area | Evidence |
| --- | --- |
| Live ingestion coverage | `tests/test_live_ingestion.py` covers live devices, locations, platforms, device types, and combined planning |
| Contract validation | `scripts/check_query_contracts.py` and `tests/test_queries.py` enforce the bundled NQE field contracts |
| Failure handling | `tests/test_client.py` covers transient retry, auth failure, and stalled pagination safeguards |
| Supportability | `tests/test_support.py` covers redaction, classification, and shared bundle output |
| Release gates | `scripts/check_release_state.py`, `scripts/check_wheel_contents.py`, and the CI workflow enforce packaged release shape |
| Query efficiency | `tests/test_client.py` and `tests/test_runner.py` prove query resolution, snapshot caching, and parameterized request usage |

## Notes

- This note is intentionally additive. It does not replace the implementation plan.
- If a change can be done in NQE, do it there instead of adding Python mutation.
- If a change expands surface area without improving operational confidence, defer it.
