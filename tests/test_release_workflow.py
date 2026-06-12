from pathlib import Path


def test_release_workflow_includes_sensitive_content_gate():
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "check_sensitive_content.py" in workflow
    assert "check_harness.py" in workflow
    assert "check_release_state.py" in workflow
    assert "check_query_contracts.py" in workflow
    assert "softprops/action-gh-release" in workflow
