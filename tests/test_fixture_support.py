from forward_nautobot.fixture_support import (
    fixture_coverage,
    fixture_path,
    fixture_payload,
    profile_record,
    seed_profile,
)
from forward_nautobot.integrations.forward.registry import CORE_MODEL_MAPPINGS, CORE_MODEL_SLUGS
from forward_nautobot.management.commands.forward_fixture_seed import Command


def test_profile_record_is_write_ready():
    profile = profile_record()

    assert profile.name == "replay"
    assert profile.base_url == "https://fwd.app"
    assert profile.enabled_models[0] == "locations"
    assert profile.write_ready is True
    assert profile.effective_delete_policy == "mark_inactive"


def test_fixture_payload_is_packaged_and_has_expected_slices():
    payload = fixture_payload()
    coverage = fixture_coverage()

    assert fixture_path().endswith("forward_sample_ingestion.json")
    assert "devices" in payload
    assert payload["devices"][0]["name"] == "cdl1alfabbcn001"
    assert {
        "locations",
        "devices",
        "interfaces",
        "vlans",
        "vrfs",
        "ipv4_prefixes",
        "ipv6_prefixes",
        "modules",
    }.issubset(payload)
    assert len(coverage) == 12
    assert tuple(entry["slug"] for entry in coverage) == CORE_MODEL_SLUGS
    assert all(entry["count"] >= 1 for entry in coverage)
    assert coverage[0]["sample_key"] == "CDL0_DC00-Roseland NJ (NJRSL)"
    assert all(entry["description"] for entry in coverage)
    assert {entry["slug"] for entry in coverage} == set(CORE_MODEL_SLUGS)


def test_fixture_coverage_tracks_supported_registry_slices():
    payload = fixture_payload()
    coverage = {entry["slug"]: entry for entry in fixture_coverage()}

    assert set(payload) == set(CORE_MODEL_SLUGS)
    assert tuple(coverage) == CORE_MODEL_SLUGS

    for mapping in CORE_MODEL_MAPPINGS:
        entry = coverage[mapping.slug]
        rows = payload[mapping.slug]

        assert entry["contract_version"] == mapping.contract_version
        assert entry["description"] == mapping.description
        assert entry["count"] == len(rows)
        assert entry["sample_rows"]
        assert entry["sample_key"]
        assert all(
            str(entry["sample_rows"][0].get(field_name) or "").strip()
            for field_name in mapping.identity_fields
        )


def test_seed_profile_updates_manager():
    class _StoredProfile:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def save(self, update_fields=None):  # pragma: no cover - exercised by call path
            return None

        def to_record(self):
            from forward_nautobot.models import ForwardConnectionProfileRecord

            return ForwardConnectionProfileRecord.from_mapping(self.__dict__)

    class _FakeManager:
        def __init__(self):
            self.rows = {}

        def all(self):
            return list(self.rows.values())

        def get(self, name):
            return self.rows[name]

        def update_or_create(self, name, defaults):
            row = self.rows.get(name)
            if row is None:
                row = _StoredProfile(name=name, **defaults)
                self.rows[name] = row
            else:
                row.__dict__.update(defaults)
            return row, True

    manager = _FakeManager()

    profile = seed_profile(manager=manager)

    assert profile is not None
    assert profile.name == "replay"
    assert profile.is_default is True
    assert profile.write_ready is True
    assert manager.rows["replay"].enabled_models == list(profile.enabled_models)


def test_fixture_seed_command_reports_fixture_details(monkeypatch):
    from forward_nautobot.fixture_support import profile_record

    monkeypatch.setattr(
        "forward_nautobot.management.commands.forward_fixture_seed.seed_profile",
        lambda: profile_record(),
    )

    command = Command()

    class _Capture:
        message = ""

        def write(self, message):
            self.message = message

    capture = _Capture()
    command.stdout = capture
    command.handle()

    output = capture.message
    assert "forward_sample_ingestion.json" in output
    assert '"profile_name": "replay"' in output
