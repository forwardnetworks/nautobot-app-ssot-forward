# Project Knowledge

## Purpose

Keep the Forward Nautobot integration legible for both humans and agents.

## Rules

- Put architecture decisions in `ARCHITECTURE.md`.
- Put live implementation work in code, not in long prompt history.
- Put active multi-step work in `docs/03_Plans/active/`.
- Keep validation surfaces small and repeatable.
- Keep credentials out of source control and pass them via environment or deployment secrets.

## Validation Surface

- `pytest -q`
- import checks for `forward_nautobot`
- job registration checks for `forward_nautobot.jobs`
- `python scripts/check_sensitive_content.py --all-history`
- `python scripts/check_harness.py`
- `python scripts/check_query_contracts.py`
- `python scripts/check_wheel_contents.py`
- `python scripts/check_release_state.py`
- live ingestion checks when `FORWARD_LIVE_*` environment variables are set
