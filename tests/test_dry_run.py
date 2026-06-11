from pathlib import Path
import io
import json

from forward_nautobot.integrations.forward.dry_run import run_fixture_dry_run
from forward_nautobot.management.commands.forward_dry_run import Command


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "forward_ingestion_sample.json"


def test_fixture_dry_run_reports_write_and_diff_summaries():
    result = run_fixture_dry_run(FIXTURE_PATH)

    assert result.report.mode == "dry-run"
    assert result.write_summary["create"] == 14
    assert result.diff_summary["create"] == 14
    assert result.configuration_status["profile_provided"] is False
    assert result.configuration_status["delete_policy"] == "ignore"
    assert result.configuration_status["missing_defaults"] == []
    assert result.failure_classification == "clean"
    assert result.support_bundle.write_summary["create"] == 14
    assert result.support_bundle.diagnostics["fixture_path"].endswith(
        "forward_ingestion_sample.json"
    )
    assert result.support_bundle_shared["write_summary"]["create"] == 14


def test_fixture_dry_run_management_command_matches_helper():
    command = Command()
    command.stdout = io.StringIO()

    command.handle(
        fixture=FIXTURE_PATH,
        models="",
        sample_size=3,
        sharing_profile="internal",
    )

    output = json.loads(command.stdout.getvalue())
    assert output["fixture_path"].endswith("forward_ingestion_sample.json")
    assert output["write_summary"]["create"] == 14
    assert output["configuration_status"]["delete_policy"] == "ignore"
    assert output["failure_classification"] == "clean"
    assert output["support_bundle_shared"]["write_summary"]["create"] == 14
    assert output["support_bundle_shared"]["source_url"] == "fixture://local"
