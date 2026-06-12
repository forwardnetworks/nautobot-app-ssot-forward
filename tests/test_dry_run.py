import io
import json

from forward_nautobot.fixture_support import fixture_path
from forward_nautobot.integrations.forward.dry_run import run_fixture_dry_run
from forward_nautobot.management.commands.forward_dry_run import Command


def test_fixture_dry_run_reports_write_and_diff_summaries():
    replay_path = fixture_path()
    result = run_fixture_dry_run(replay_path)

    assert result.report.mode == "dry-run"
    assert result.write_summary["create"] == 15
    assert result.diff_summary["create"] == 15
    assert result.configuration_status["profile_provided"] is False
    assert result.configuration_status["delete_policy"] == "ignore"
    assert result.configuration_status["missing_defaults"] == []
    assert result.failure_classification == "clean"
    assert result.support_bundle.write_summary["create"] == 15
    assert result.support_bundle.diagnostics["fixture_path"].endswith(
        "forward_sample_ingestion.json"
    )
    assert result.support_bundle_shared["write_summary"]["create"] == 15


def test_fixture_dry_run_subset_models_uses_only_selected_rows():
    replay_path = fixture_path()
    result = run_fixture_dry_run(
        replay_path,
        model_names=("locations", "devices", "interfaces"),
        sample_size=1,
        sharing_profile="external",
    )

    assert result.report.planned_models == ("locations", "devices", "interfaces")
    assert result.report.row_count == 5
    assert result.source_summary["model_counts"] == {
        "locations": 2,
        "devices": 1,
        "interfaces": 2,
    }
    assert result.write_summary["create"] == 5
    assert result.diff_summary["create"] == 5
    assert result.support_bundle.row_count == 5
    assert result.support_bundle.diagnostics["fixture_path"].endswith(
        "forward_sample_ingestion.json"
    )
    assert result.support_bundle_shared["planned_models"] == [
        "locations",
        "devices",
        "interfaces",
    ]


def test_fixture_dry_run_management_command_matches_helper():
    command = Command()
    command.stdout = io.StringIO()

    command.handle(
        fixture=fixture_path(),
        models="",
        sample_size=3,
        sharing_profile="internal",
    )

    output = json.loads(command.stdout.getvalue())
    assert output["fixture_path"].endswith("forward_sample_ingestion.json")
    assert output["write_summary"]["create"] == 15
    assert output["configuration_status"]["delete_policy"] == "ignore"
    assert output["failure_classification"] == "clean"
    assert output["support_bundle_shared"]["write_summary"]["create"] == 15
    assert output["support_bundle_shared"]["source_url"] == "fixture://local"


def test_fixture_dry_run_management_command_writes_full_and_shared_outputs(tmp_path):
    command = Command()
    command.stdout = io.StringIO()
    full_output = tmp_path / "replay" / "full.json"
    shared_output = tmp_path / "replay" / "shared.json"

    command.handle(
        fixture=fixture_path(),
        models="locations,devices,interfaces",
        sample_size=1,
        sharing_profile="external",
        output=full_output,
        shared_output=shared_output,
    )

    output = json.loads(command.stdout.getvalue())
    full_payload = json.loads(full_output.read_text(encoding="utf-8"))
    shared_payload = json.loads(shared_output.read_text(encoding="utf-8"))

    assert full_output.is_file()
    assert shared_output.is_file()
    assert full_payload["support_bundle_shared"]["planned_models"] == [
        "locations",
        "devices",
        "interfaces",
    ]
    assert shared_payload["planned_models"] == [
        "locations",
        "devices",
        "interfaces",
    ]
    assert shared_payload["source_url"] == "[REDACTED]"
    assert output["support_bundle_shared"]["source_url"] == "[REDACTED]"
