from __future__ import annotations

import json

import forward_nautobot.integrations.forward.query_publishing as publishing
from forward_nautobot.integrations.forward.exceptions import ForwardClientError


class _FakePublishingClient:
    def __init__(self, committed: dict[str, str]):
        self.committed = dict(committed)
        self.staged: dict[str, str] = {}
        self.mutations: list[tuple[str, str]] = []
        self.head = "commit-1"

    def get_nqe_repository_query_index(self, **_kwargs):
        return {
            "by_path": {
                path: {
                    "path": path,
                    "queryId": f"query-{index}",
                    "lastCommit": {"id": self.head},
                }
                for index, path in enumerate(sorted(self.committed), start=1)
            }
        }

    def get_committed_nqe_query(self, *, query_path, **_kwargs):
        return {
            "path": query_path,
            "queryId": f"query-{query_path.rsplit('/', 1)[-1]}",
            "lastCommitId": self.head,
            "sourceCode": self.committed[query_path],
        }

    def get_nqe_query_history(self, _query_id):
        return [{"id": self.head}]

    def add_org_nqe_query(self, *, query_path, source_code):
        self.staged[query_path] = source_code
        self.mutations.append(("add", query_path))

    def edit_org_nqe_query(self, *, query_path, source_code, **_kwargs):
        self.staged[query_path] = source_code
        self.mutations.append(("edit", query_path))

    def commit_org_nqe_queries(self, *, query_paths, message):
        assert query_paths == list(self.staged)
        assert message
        self.committed.update(self.staged)
        self.staged.clear()
        self.head = "commit-2"
        self.mutations.append(("commit", self.head))
        return self.head

    def get_org_nqe_draft_changes(self):
        return []

    def dry_run_org_nqe_queries(self, *, query_paths, snapshot_id=None):
        assert query_paths == list(self.staged)
        self.mutations.append(("dry-run", snapshot_id or ""))
        return {
            "newErrors": {},
            "uses": [],
            "unauthorizedQueryChanges": [],
            "unauthorizedAccessSettingChanges": [],
        }

    def discard_org_nqe_draft_change(self, *, path):
        self.staged.pop(path, None)
        self.mutations.append(("discard", path))


def _bundle(monkeypatch):
    sources = {
        "query_one.nqe": "@query\nf() = foreach x in [1] select x;\n",
        "query_two.nqe": "@query\nf() = foreach x in [2] select x;\n",
    }
    monkeypatch.setattr(publishing, "QUERY_FILENAMES", tuple(sources))
    monkeypatch.setattr(publishing, "read_bundled_query_source", sources.__getitem__)
    paths = {filename: publishing.query_path_from_filename(filename) for filename in sources}
    return sources, paths


def test_query_publication_is_idempotent_and_source_proven(monkeypatch):
    sources, paths = _bundle(monkeypatch)
    client = _FakePublishingClient(
        {paths[filename]: source for filename, source in sources.items()}
    )

    result = publishing.publish_bundled_queries(client)

    assert result["status"] == "pass"
    assert result["changed_count"] == 0
    assert {entry["status"] for entry in result["publication"]} == {"unchanged"}
    assert result["audit"]["counts"] == {"matched": 2}
    assert client.mutations == []
    assert "sourceCode" not in json.dumps(result)


def test_query_publication_adds_missing_queries_and_commits_once(monkeypatch):
    sources, paths = _bundle(monkeypatch)
    client = _FakePublishingClient({paths["query_one.nqe"]: sources["query_one.nqe"]})

    result = publishing.publish_bundled_queries(client)

    assert result["status"] == "pass"
    assert result["changed_count"] == 1
    assert result["commit_id"] == "commit-2"
    assert client.mutations == [
        ("add", paths["query_two.nqe"]),
        ("dry-run", ""),
        ("commit", "commit-2"),
    ]


def test_query_publication_creates_missing_enclosing_directory(monkeypatch):
    sources, paths = _bundle(monkeypatch)

    class _MissingDirectoryClient(_FakePublishingClient):
        directory_exists = False

        def add_org_nqe_query(self, *, query_path, source_code):
            if not self.directory_exists:
                raise ForwardClientError('{"reason":"ENCLOSING_DIR_DOES_NOT_EXIST"}')
            super().add_org_nqe_query(query_path=query_path, source_code=source_code)

        def add_org_nqe_directory(self, *, directory_path):
            assert directory_path == "/forward_nautobot_validation"
            self.directory_exists = True
            self.mutations.append(("add-dir", directory_path))

    client = _MissingDirectoryClient({paths["query_one.nqe"]: sources["query_one.nqe"]})
    result = publishing.publish_bundled_queries(client)

    assert result["status"] == "pass"
    assert result["changed_count"] == 1
    assert client.mutations == [
        ("add-dir", "/forward_nautobot_validation"),
        ("add", paths["query_two.nqe"]),
        ("dry-run", ""),
        ("commit", "commit-2"),
    ]


def test_query_publication_refuses_stale_source_without_overwrite(monkeypatch):
    sources, paths = _bundle(monkeypatch)
    client = _FakePublishingClient(
        {
            paths["query_one.nqe"]: "stale source",
            paths["query_two.nqe"]: sources["query_two.nqe"],
        }
    )

    result = publishing.publish_bundled_queries(client, overwrite=False)

    assert result["status"] == "fail"
    assert result["changed_count"] == 0
    assert result["audit"]["counts"] == {"stale": 1, "matched": 1}
    assert client.mutations == []


def test_query_publication_updates_stale_source_when_explicit(monkeypatch):
    sources, paths = _bundle(monkeypatch)
    client = _FakePublishingClient(
        {
            paths["query_one.nqe"]: "stale source",
            paths["query_two.nqe"]: sources["query_two.nqe"],
        }
    )

    result = publishing.publish_bundled_queries(client, overwrite=True)

    assert result["status"] == "pass"
    assert result["changed_count"] == 1
    assert client.mutations == [
        ("edit", paths["query_one.nqe"]),
        ("dry-run", ""),
        ("commit", "commit-2"),
    ]


def test_query_publication_discards_only_touched_paths_when_dry_run_fails(monkeypatch):
    sources, paths = _bundle(monkeypatch)

    class _InvalidDryRunClient(_FakePublishingClient):
        def dry_run_org_nqe_queries(self, *, query_paths, snapshot_id=None):
            self.mutations.append(("dry-run", snapshot_id or ""))
            return {
                "newErrors": {query_paths[0]: [{"severity": "ERROR"}]},
                "uses": [],
                "unauthorizedQueryChanges": [],
                "unauthorizedAccessSettingChanges": [],
            }

    client = _InvalidDryRunClient(
        {
            paths["query_one.nqe"]: "stale source",
            paths["query_two.nqe"]: sources["query_two.nqe"],
        }
    )

    result = publishing.publish_bundled_queries(client, overwrite=True, snapshot_id="snap-current")

    assert result["status"] == "fail"
    assert result["commit_id"] == ""
    assert result["dry_run"]["status"] == "fail"
    assert result["dry_run"]["snapshot_aware"] is True
    assert client.mutations == [
        ("edit", paths["query_one.nqe"]),
        ("dry-run", "snap-current"),
        ("discard", paths["query_one.nqe"]),
    ]


def test_query_publication_refuses_to_overwrite_preexisting_user_draft(monkeypatch):
    sources, paths = _bundle(monkeypatch)

    class _ExistingDraftClient(_FakePublishingClient):
        def get_org_nqe_draft_changes(self):
            return [{"type": "QUERY_EDIT", "basis": {"path": paths["query_one.nqe"]}}]

    client = _ExistingDraftClient(
        {
            paths["query_one.nqe"]: "stale source",
            paths["query_two.nqe"]: sources["query_two.nqe"],
        }
    )

    result = publishing.publish_bundled_queries(client, overwrite=True)

    assert result["status"] == "fail"
    assert result["dry_run"]["status"] == "blocked-existing-drafts"
    assert result["dry_run"]["conflicting_paths"] == [paths["query_one.nqe"]]
    assert client.mutations == []
