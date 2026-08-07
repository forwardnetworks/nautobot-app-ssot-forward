# Local-Only Release Operations

Date: 2026-08-06
Status: complete

## Goal

Remove all GitHub-hosted automation and make validation, artifact creation, and
publication explicitly maintainer-run from the local checkout.

## Scope

- Disable GitHub Actions for the repository.
- Delete every GitHub Actions workflow and the Dependabot configuration.
- Remove the unused package-publishing environment from GitHub.
- Preserve local validation through `pre-commit` and `scripts/ci_local.py`.
- Build locally and upload the exact local wheel and sdist through
  `scripts/release.py --publish`.
- Keep publishing credentials outside the repository.

## Checklist

- [x] Repository Actions disabled.
- [x] Package-publishing GitHub environment removed.
- [x] Workflow and Dependabot files removed from the default branch.
- [x] Local release helper uploads local artifacts to GitHub Releases and PyPI.
- [x] Full local release gate passes.
- [x] Default branch and GitHub settings re-audited after merge.

## Exit Criteria

- GitHub reports repository Actions disabled.
- No workflow, Dependabot, branch-protection, ruleset, or deployment-environment
  gate remains.
- The repository harness rejects any future workflow or Dependabot file.
- Local release validation passes and the default branch is clean.
