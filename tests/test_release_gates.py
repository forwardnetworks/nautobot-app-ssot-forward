from __future__ import annotations

# sensitive-content: allow-file — this file embeds sample matching strings to
# prove the guard detects them; the static scan must skip itself.
import sys
from zipfile import ZipFile

from scripts import check_installed_wheel, check_sensitive_content, check_wheel_contents, ci_local


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
    assert check_installed_wheel.SUPPORTED_NAUTOBOT_VERSIONS == ("3.1.8", "3.2.2")
    assert check_installed_wheel.COMPOSE_FILE.name == "docker-compose.wheel.yml"
