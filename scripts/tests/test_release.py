"""Unit tests for the pure helpers in scripts/release.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "release", Path(__file__).resolve().parents[1] / "release.py"
)
release = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(release)


class BumpVersionText(unittest.TestCase):
    def test_bumps_single_occurrence(self):
        text = 'name = "x"\nversion = "0.2.0"\n'
        out = release.bump_version_text(text, "0.2.0", "0.3.0")
        self.assertIn('version = "0.3.0"', out)
        self.assertNotIn('"0.2.0"', out)

    def test_raises_when_old_absent(self):
        with self.assertRaises(release.ReleaseError):
            release.bump_version_text('version = "9.9.9"', "0.2.0", "0.3.0")

    def test_raises_when_multiple(self):
        text = 'version = "0.2.0"\nversion = "0.2.0"\n'
        with self.assertRaises(release.ReleaseError):
            release.bump_version_text(text, "0.2.0", "0.3.0")

    def test_custom_key(self):
        out = release.bump_version_text(
            'min_version = "3.1.0"', "3.1.0", "3.2.0", key="min_version"
        )
        self.assertIn('min_version = "3.2.0"', out)


class ReadVersions(unittest.TestCase):
    def test_read_pyproject_version(self):
        text = '[tool.poetry]\nname = "p"\nversion = "1.2.3"\n'
        self.assertEqual(release.read_pyproject_version(text), "1.2.3")

    def test_read_pyproject_missing(self):
        with self.assertRaises(release.ReleaseError):
            release.read_pyproject_version("name = 'p'")

    def test_read_init_version_indented(self):
        text = "class C:\n    name = 'x'\n    version = \"0.4.0\"\n"
        self.assertEqual(release.read_init_version(text), "0.4.0")

    def test_read_init_missing(self):
        with self.assertRaises(release.ReleaseError):
            release.read_init_version("class C:\n    name = 'x'\n")


class PlanScaffold(unittest.TestCase):
    def test_filename(self):
        self.assertEqual(
            release.plan_filename("0.3.0", "2026-06-19"),
            "2026-06-19-release-0.3.0.md",
        )

    def test_scaffold_contains_version_and_summary(self):
        out = release.plan_scaffold("0.3.0", "gitops", "2026-06-19")
        self.assertIn("# Release 0.3.0", out)
        self.assertIn("gitops", out)
        self.assertIn("2026-06-19", out)
        self.assertIn("--publish", out)


class DistributionFilenames(unittest.TestCase):
    def test_returns_exact_wheel_and_sdist_names(self):
        self.assertEqual(
            release.distribution_filenames("0.6.1"),
            (
                "nautobot_app_ssot_forward-0.6.1-py3-none-any.whl",
                "nautobot_app_ssot_forward-0.6.1.tar.gz",
            ),
        )

    def test_publish_uploads_the_same_local_artifacts_to_both_destinations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            dist_dir = repo_root / "dist"
            dist_dir.mkdir()
            for name in release.distribution_filenames("0.6.1"):
                (dist_dir / name).write_bytes(b"test artifact")

            with (
                mock.patch.object(release, "REPO_ROOT", repo_root),
                mock.patch.object(release, "DIST_DIR", dist_dir),
                mock.patch.object(release, "run") as run_mock,
            ):
                release.stage_publish("0.6.1", summary="test release")

            commands = [call.args[0] for call in run_mock.call_args_list]
            github_upload = next(
                command for command in commands if command[:3] == ["gh", "release", "create"]
            )
            pypi_upload = next(
                command
                for command in commands
                if command[:5] == [sys.executable, "-m", "twine", "upload", "--non-interactive"]
            )
            expected_artifacts = [
                f"dist/{name}" for name in release.distribution_filenames("0.6.1")
            ]
            self.assertEqual(github_upload[-2:], expected_artifacts)
            self.assertEqual(pypi_upload[-2:], expected_artifacts)


if __name__ == "__main__":
    unittest.main()


class PlanScaffoldHygiene(unittest.TestCase):
    def test_no_trailing_whitespace(self):
        out = release.plan_scaffold("0.3.0", "summary", "2026-06-23")
        offenders = [ln for ln in out.splitlines() if ln != ln.rstrip()]
        self.assertEqual(offenders, [], f"trailing whitespace in scaffold: {offenders}")
