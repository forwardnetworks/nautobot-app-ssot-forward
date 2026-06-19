from forward_nautobot.integrations.forward.contract_diff import (
    ContractDiffEntry,
    ContractSnapshot,
    diff_contract_snapshots,
)


def test_contract_diff_report_tracks_modified_contracts():
    current = ContractSnapshot(
        source="current",
        contracts={
            "forward_devices.nqe": {"contract_version": "v2", "fields": ("name", "location")},
            "forward_locations.nqe": {
                "contract_version": "v1",
                "fields": ("name", "city", "country"),
            },
        },
    )
    baseline = ContractSnapshot(
        source="baseline",
        contracts={
            "forward_devices.nqe": {
                "contract_version": "v1",
                "fields": ("name", "location", "vendor"),
            },
            "forward_locations.nqe": {
                "contract_version": "v1",
                "fields": ("name", "city", "country"),
            },
        },
    )

    report = diff_contract_snapshots(current, baseline)

    assert len(report.entries) == 1
    assert report.entries[0] == ContractDiffEntry(
        filename="forward_devices.nqe",
        change_type="modified",
        current={"contract_version": "v2", "fields": ("name", "location")},
        baseline={"contract_version": "v1", "fields": ("name", "location", "vendor")},
    )
    assert report.as_dict()["changed_files"] == ["forward_devices.nqe"]
