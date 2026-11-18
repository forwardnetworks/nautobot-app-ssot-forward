from __future__ import annotations

# sensitive-content: allow-file — this file embeds sample matching strings to
# prove the guard detects them; the static scan must skip itself.
import sys
from zipfile import ZipFile

from scripts import (
    check_installed_wheel,
    check_release_state,
    check_sensitive_content,
    check_wheel_contents,
    ci_local,
    release,
)


def test_sensitive_content_gate_blocks_customer_identifiers(tmp_path, capsys, monkeypatch):
    sample = tmp_path / "customer-note.txt"
    sample.write_text(
        "customer network_id: 248592\ncontact support+noreply@forwardnetworks.com\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(check_sensitive_content, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_sensitive_content.py", str(sample)])
    exit_code = check_sensitive_content.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Sensitive content guard failed:" in captured.out
    assert "Forward network identifier" in captured.out
    assert "Forward plus-alias email address" in captured.out


def test_sensitive_content_gate_allows_benign_content(tmp_path, capsys, monkeypatch):
    sample = tmp_path / "notes.txt"
    sample.write_text("release hardening goal\n", encoding="utf-8")

    monkeypatch.setattr(check_sensitive_content, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_sensitive_content.py", str(sample)])
    exit_code = check_sensitive_content.main()

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_wheel_contents_gate_accepts_required_files(tmp_path):
    package_version = check_wheel_contents._package_version()
    wheel_path = tmp_path / "nautobot_app_ssot_forward-test.whl"
    with ZipFile(wheel_path, "w") as wheel:
        for expected_file in check_wheel_contents.EXPECTED_FILES:
            wheel.writestr(expected_file, "ok\n")
        wheel.writestr(
            f"nautobot_app_ssot_forward-{package_version}.dist-info/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: nautobot-app-ssot-forward\n"
            f"Version: {package_version}\n",
        )

    exit_code = check_wheel_contents.main(["--wheel-path", str(wheel_path)])

    assert exit_code == 0


def test_wheel_contents_gate_rejects_missing_files(tmp_path, capsys):
    wheel_path = tmp_path / "nautobot_app_ssot_forward-test.whl"
    with ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(check_wheel_contents.EXPECTED_FILES[0], "ok\n")

    exit_code = check_wheel_contents.main(["--wheel-path", str(wheel_path)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Wheel contents check failed" in captured.out
    assert "missing wheel file:" in captured.out


def test_full_local_gate_runs_source_absent_wheel_acceptance():
    full_labels = [label for label, _argv in ci_local._gates(fast=False, sensitive=False)]
    fast_labels = [label for label, _argv in ci_local._gates(fast=True, sensitive=False)]

    assert "installed-wheel" in full_labels
    assert "installed-wheel" not in fast_labels
    assert check_installed_wheel.SUPPORTED_NAUTOBOT_VERSIONS == ("3.1.8", "3.2.9")
    assert check_installed_wheel.COMPOSE_FILE.name == "docker-compose.wheel.yml"


_README_TABLE = (
    "| Plugin | Nautobot | nautobot-ssot | Forward | Status |\n"
    "| --- | --- | --- | --- | --- |\n"
    "| `{version}` | `3.1.8` | `4.4` - `<5.0` | `26.6+` | {status} |\n"
)


def test_readme_current_row_is_found():
    text = _README_TABLE.format(version="0.9.0", status="Current")
    assert check_release_state.readme_current_versions(text) == ["0.9.0"]


def test_readme_rows_that_are_not_current_are_ignored():
    text = _README_TABLE.format(version="0.8.1", status="Superseded")
    assert check_release_state.readme_current_versions(text) == []


def test_release_state_gate_fails_when_the_readme_names_an_older_release(
    tmp_path, capsys, monkeypatch
):
    package_version = check_wheel_contents._package_version()
    readme = tmp_path / "README.md"
    readme.write_text(_README_TABLE.format(version="0.0.1", status="Current"), encoding="utf-8")
    monkeypatch.setattr(check_release_state, "README", readme)

    assert check_release_state.main() == 1
    out = capsys.readouterr().out
    assert "README compatibility table" in out
    assert package_version in out


def test_release_state_gate_passes_when_the_readme_names_this_release(
    tmp_path, capsys, monkeypatch
):
    package_version = check_wheel_contents._package_version()
    readme = tmp_path / "README.md"
    readme.write_text(
        _README_TABLE.format(version=package_version, status="Current"), encoding="utf-8"
    )
    monkeypatch.setattr(check_release_state, "README", readme)

    assert check_release_state.main() == 0


def test_release_script_moves_the_readme_current_row():
    before = _README_TABLE.format(version="0.8.1", status="Current")
    after = release.bump_readme_current_row(before, "0.8.1", "0.9.0")
    assert check_release_state.readme_current_versions(after) == ["0.9.0"]
    assert "0.8.1" not in after


def test_release_script_refuses_a_drifted_readme_table():
    import pytest

    stale = _README_TABLE.format(version="0.7.0", status="Current")
    with pytest.raises(release.ReleaseError):
        release.bump_readme_current_row(stale, "0.8.1", "0.9.0")
    with pytest.raises(release.ReleaseError):
        release.bump_readme_current_row(
            _README_TABLE.format(version="0.8.1", status="Superseded"), "0.8.1", "0.9.0"
        )
