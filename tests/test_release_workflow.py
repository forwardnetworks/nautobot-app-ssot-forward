from pathlib import Path


def test_security_policy_documents_enterprise_credential_handling():
    security = Path("SECURITY.md").read_text(encoding="utf-8")

    assert "Fernet" in security
    assert "SECRET_KEY" in security
    assert "trust_env=True" in security
    assert "https://fwd.app" in security


def test_validation_matrix_pins_blake_regression_and_live_gate():
    matrix = Path("docs/00_Project_Knowledge/validation-matrix.md").read_text(encoding="utf-8")

    assert "ForwardInventoryDataSource" in matrix
    assert "FORWARD_LIVE_ASYNC_QUERY_PATH" in matrix
    assert "FORWARD_STRICT_NO_SKIPS=1" in matrix
    assert "python scripts/ci_local.py" in matrix
    assert "No live customer credentials" in matrix
    assert "No skipped non-integration tests" in matrix


def test_github_validation_is_removed_and_release_workflow_is_delivery_only():
    assert not Path(".github/workflows/ci.yml").exists()

    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "python -m build" in workflow
    assert "softprops/action-gh-release" in workflow
    assert "pypa/gh-action-pypi-publish" in workflow
    assert "check_sensitive_content.py" not in workflow
    assert "check_harness.py" not in workflow
    assert "check_release_state.py" not in workflow
    assert "check_query_contracts.py" not in workflow
    assert "generate_contract_diff_report.py" not in workflow
    assert "check_wheel_contents.py" not in workflow
    assert "python -m pytest" not in workflow


def test_readme_documents_release_readiness_checks():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Release Readiness" in readme
    assert "Validation Matrix" in readme
    assert "Security Policy" in readme
    assert "python -m pytest -q" in readme
    assert "python scripts/check_sensitive_content.py --all-history" in readme
    assert "python scripts/check_wheel_contents.py" in readme
    assert "async full-query execution with exact-set device scope filtering" in readme
    assert "strict NQE diff execution across two processed snapshots" in readme
    assert "exact committed-source audit for every bundled query" in readme
    assert "packaged source inline through the same async API" in readme
