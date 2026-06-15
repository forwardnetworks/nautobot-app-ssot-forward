from __future__ import annotations

import sys
from zipfile import ZipFile

from scripts import check_sensitive_content
from scripts import check_wheel_contents


def test_sensitive_content_gate_blocks_customer_identifiers(tmp_path, capsys, monkeypatch):
    sample = tmp_path / "customer-note.txt"
    sample.write_text(
        "customer network_id: 248592\n"
        "contact support+noreply@forwardnetworks.com\n",
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
    wheel_path = tmp_path / "nautobot_app_ssot_forward-test.whl"
    with ZipFile(wheel_path, "w") as wheel:
        for expected_file in check_wheel_contents.EXPECTED_FILES:
            wheel.writestr(expected_file, "ok\n")

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
