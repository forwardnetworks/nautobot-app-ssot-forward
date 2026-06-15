from pathlib import Path


def test_release_workflow_includes_sensitive_content_gate():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "check_sensitive_content.py" in workflow
    assert "check_harness.py" in workflow
    assert "check_release_state.py" in workflow
    assert "check_query_contracts.py" in workflow
    assert "softprops/action-gh-release" in workflow


def test_readme_documents_release_readiness_checks():
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "## Release Readiness" in readme
    assert "python -m pytest -q" in readme
    assert "python scripts/check_sensitive_content.py --all-history" in readme
    assert "python scripts/check_wheel_contents.py" in readme
    assert "preview/sync on `locations`" in readme
    assert "preview/sync on `devices` with explicit `forward_location_names`" in readme
