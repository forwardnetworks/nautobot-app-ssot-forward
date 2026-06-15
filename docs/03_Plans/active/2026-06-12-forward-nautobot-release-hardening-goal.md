# Forward Nautobot Release Hardening Goal

## Goal

Make the Forward Nautobot plugin release process boring: no customer data in tracked content or release artifacts, bounded live smoke coverage for the core preview/sync path, and a fully green test/build/release pipeline.

## Scope

- keep release and packaging gates deterministic
- keep sensitive-content checks strong enough to block customer-derived identifiers
- keep live smoke tests bounded and representative
- keep scope-parameter regression coverage aligned with the bundled NQE contracts
- keep the release workflow publishable from a tagged commit

## Checklist

| Item | Evidence | Status |
| --- | --- | --- |
| Full pytest suite passes | `tests/` | done |
| Wheel and sdist build cleanly | `python -m build` | done |
| Tag-triggered release workflow succeeds | `.github/workflows/release.yml` | done |
| Sensitive-content gate passes | `scripts/check_sensitive_content.py` | done |
| Sensitive-content gate has direct regression coverage | `tests/test_release_gates.py` | done |
| Live preview/sync smoke is bounded | `tests/test_live_ingestion.py` | done |
| Scope-parameter regression coverage is in place | `tests/test_planner.py`, `tests/test_runner.py`, `forward_nautobot/integrations/forward/registry.py` | done |
| Wheel verification gate has direct regression coverage | `tests/test_release_gates.py` | done |

## Next Tranche

1. Expand live smoke coverage only where it adds new signal, not duplicate call volume.
2. Tighten release notes and operator-facing guidance as the supported slice set grows.
3. Add more coverage for any future Nautobot object types introduced by new slices.

## Exit Criteria

- no sensitive identifiers appear in tracked files or release artifacts
- the release workflow succeeds from a tagged commit
- live preview/sync smokes remain bounded and representative
- the current supported slice set has regression coverage for query scope, contract drift, and packaging
