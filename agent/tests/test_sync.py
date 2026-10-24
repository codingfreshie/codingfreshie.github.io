import json

import pytest

from agent.github_client import GitHubError, NotFound
from agent.sync import apply_sync, find_changes
from .conftest import FakeClient, project, repo

OK = lambda: (True, "")


def test_rename_deleted_private_and_transferred(settings):
    projects = [project("a", 1, name="old-name"), project("b", 2), project("c", 3), project("d", 4), project("e", 5)]
    client = FakeClient({
        "/users/octo/repos": [repo(1, "new-name")],
        "/repositories/2": NotFound(404, "gone", "x"),
        "/repositories/3": {"private": True, "full_name": "octo/c"},
        "/repositories/4": {"private": False, "full_name": "someone/d"},
        "/repositories/5": GitHubError(502, "bad gateway", "x"),
    })
    proposals, notes = find_changes(client, settings, projects)
    kinds = {(p["project_id"], p["type"]) for p in proposals}
    assert kinds == {("a", "rename"), ("b", "hide"), ("c", "hide")}
    assert any("transferred" in n for n in notes) and any("could not confirm" in n for n in notes)


def test_nothing_to_do_when_everything_matches(settings):
    proposals, notes = find_changes(FakeClient({"/users/octo/repos": [repo(1, "a")]}), settings, [project("a", 1)])
    assert proposals == [] and notes == []


def test_apply_renames_hides_and_never_deletes(tmp_path):
    data = {"schema_version": 1, "projects": [project("a", 1, name="old"), project("b", 2)]}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(data))
    props = [{"type": "rename", "project_id": "a", "old_url": "https://github.com/octo/old", "new_url": "https://github.com/octo/new"},
             {"type": "hide", "project_id": "b", "reason": "the repository was deleted, or made private"}]
    res = apply_sync(props, path, OK)
    saved = {p["id"]: p for p in json.loads(path.read_text())["projects"]}
    assert len(res["done"]) == 2 and saved["a"]["repository_url"].endswith("/new") and saved["b"]["status"] == "archived"


def test_stale_proposals_are_skipped_and_failures_roll_back(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({"schema_version": 1, "projects": [project("a", 1, status="archived")]}))
    res = apply_sync([{"type": "hide", "project_id": "a", "reason": "r"},
                      {"type": "rename", "project_id": "a", "old_url": "https://github.com/octo/other", "new_url": "https://github.com/octo/x"}], path, OK)
    assert res["done"] == [] and len(res["skipped"]) == 2
    path.write_text(json.dumps({"schema_version": 1, "projects": [project("b", 2)]}))
    before = path.read_text()
    bad = apply_sync([{"type": "hide", "project_id": "b", "reason": "r"}], path, lambda: (False, "bad"))
    assert not bad["ok"] and path.read_text() == before
