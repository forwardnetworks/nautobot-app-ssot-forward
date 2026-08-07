# Forward Nautobot Plugin Documentation

This repo is in an early alpha stage; documentation is intentionally compact and
focused on run behavior and validation.

## Core Docs

- [Architecture](../ARCHITECTURE.md)
- [Architecture flow — end-to-end diagrams](architecture-flow.md)
- [Project Knowledge](00_Project_Knowledge/README.md)
- [Active plans](03_Plans/active/)

## Data and Runtime Files

- [Shipped queries](../forward_nautobot/integrations/forward/queries/README.md)
- [Fixture seed payload](../forward_nautobot/fixtures/forward_sample_ingestion.json)
- [NQE queries](../forward_nautobot/integrations/forward/queries/)

## Release and Validation Surface

Local release process:

- `python scripts/ci_local.py` — complete local release gate (`--fast` skips build/wheel)
- `python scripts/release.py X.Y.Z --summary "..."` — prepare (bump pyproject + `__init__` in lockstep, scaffold plan) + verify
- `python scripts/release.py X.Y.Z --summary "..." --publish` — branch → push → fast-forward main → tag → upload the local wheel/sdist to GitHub Releases and PyPI
- `pre-commit run --all-files` — ruff lint + format + sensitive-content + whitespace/yaml/json hooks

Validation and publishing are local-only. The repository has no GitHub Actions or
Dependabot automation. PyPI credentials come from the maintainer's local keyring
or Twine environment variables and are never stored in the repository.

Individual gates (run by `ci_local.py`):

- `python -m build`
- `python scripts/check_sensitive_content.py --all-history`
- `python scripts/check_harness.py`
- `python scripts/check_query_contracts.py`
- `python scripts/check_wheel_contents.py`
- `python -m twine check dist/*.whl dist/*.tar.gz`
- `python scripts/check_release_state.py` — also fails on pyproject/`__init__` version drift
- `python -m unittest discover -s scripts/tests -p 'test_*.py'`
- `pytest -q`

## Operational Notes

- Static data and query behavior are intentionally preserved in tests via fixtures.
- Live API tests require `FORWARD_LIVE_*` environment values.
- Keep all credentials, tenants, and snapshots in env vars or deployment secrets.
