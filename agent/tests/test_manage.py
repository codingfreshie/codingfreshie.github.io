import json

import pytest

from agent import manage
from agent.github_client import GitHubError
from .conftest import FakeClient


def full(pid, rid, **kw):
    p = dict(id=pid, repository_id=rid, name=pid.title(), description="A description that is long enough.",
             overview=None, features=["One feature"], primary_category="ai-llm", tags=["RAG"], tech_stack=["Python"],
             repository_url=f"https://github.com/octo/{pid}", demo_url=None, image=None, status="active",
             created_at="2026-01-01", last_updated="2026-02-01", last_analyzed_commit="a" * 40, confidence=0.9,
             needs_review=False, evidence=[], updates=[{"commit": "b" * 40, "date": "2026-02-01", "type": "feature",
                                                        "summary": "Added a thing worth noting."}])
    p.update(kw)
    return p


@pytest.fixture
def mg(tmp_path, monkeypatch):
    projects, settings = tmp_path / "projects.json", tmp_path / "settings.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [full("demo", 7), full("other", 8)]}))
    settings.write_text(json.dumps({"github_username": "octo", "exclude_repos": ["octo.github.io"]}))
    monkeypatch.setattr(manage, "PROJECTS_PATH", projects)
    monkeypatch.setattr(manage, "DEFAULT_SETTINGS_PATH", settings)
    out = tmp_path / "out"

    def run(*argv, ok=True, answer="yes", client=None):
        return manage.main(["--out", str(out), *argv], validator=lambda: (ok, "" if ok else "bad data"), ask=lambda _: answer, client=client)

    def get(pid="demo"):
        return next(p for p in json.loads(projects.read_text())["projects"] if p["id"] == pid)
    return type("Env", (), dict(run=staticmethod(run), get=staticmethod(get), projects=projects, settings=settings, out=out))


def test_hide_and_unhide_keep_everything_including_the_timeline(mg):
    assert mg.run("hide", "demo") == 0
    assert mg.get()["status"] == "archived" and len(mg.get()["updates"]) == 1
    assert mg.run("unhide", "demo") == 0 and mg.get()["status"] == "active"


def test_undo_walks_back_one_change_at_a_time(mg):
    mg.run("hide", "demo"); mg.run("hide", "other")
    assert mg.run("undo") == 0 and mg.get("other")["status"] == "active" and mg.get()["status"] == "archived"
    assert mg.run("undo") == 0 and mg.get()["status"] == "active"
    assert mg.run("undo") == 1                                   # nothing left


def test_set_changes_the_field_and_locks_it(mg):
    assert mg.run("set", "demo", "category", "ml") == 0
    p = mg.get()
    assert p["primary_category"] == "ml" and p["locked"] == ["primary_category"]
    mg.run("set", "demo", "tags", "Web Scraping, Civic Tech, web scraping")
    assert mg.get()["tags"] == ["Web Scraping", "Civic Tech"]          # split, de-duplicated, case-insensitively
    assert mg.get()["locked"] == ["primary_category", "tags"]


def test_set_rejects_bad_values_and_leaves_the_file_alone(mg):
    before = mg.projects.read_text()
    assert mg.run("set", "demo", "category", "blockchain") == 1
    assert mg.run("set", "demo", "description", "short") == 1
    assert mg.run("set", "demo", "demo_url", "http://insecure.example") == 1
    assert mg.run("set", "demo", "colour", "red") == 1
    assert mg.projects.read_text() == before


def test_set_description_strips_markup_and_locks(mg):
    mg.run("set", "demo", "description", "A <b>great</b> tool, see [docs](http://x.io) for details.")
    assert mg.get()["description"] == "A great tool, see docs for details." and "description" in mg.get()["locked"]


def test_pin_all_and_unpin(mg):
    mg.run("pin", "demo", "all")
    assert len(mg.get()["locked"]) == 9
    mg.run("unpin", "demo", "all")
    assert "locked" not in mg.get()
    assert mg.run("pin", "demo", "image") == 1


def test_unknown_project_gets_a_helpful_hint(mg, capsys):
    assert mg.run("hide", "dmeo") == 1
    assert "Did you mean: demo" in capsys.readouterr().out


def test_remove_deletes_excludes_and_cleans_leftovers(mg):
    for folder, name in [("bundles", "bundle-7.json"), ("drafts", "draft-7.json"), ("updates", "update-demo-abc1234.json"),
                         ("refresh", "refresh-demo.json"), ("sync", "sync-demo-hide.json"), ("drafts", "draft-8.json")]:
        (mg.out / folder).mkdir(parents=True, exist_ok=True)
        (mg.out / folder / name).write_text("{}")
    assert mg.run("remove", "demo", "--yes") == 0
    assert [p["id"] for p in json.loads(mg.projects.read_text())["projects"]] == ["other"]
    assert "octo/demo" in json.loads(mg.settings.read_text())["exclude_repos"]
    left = [p.name for p in mg.out.rglob("*.json") if "backups" not in p.parts]
    assert left == ["draft-8.json"]                              # only the other project's file remains


def test_remove_needs_confirmation_and_is_atomic(mg):
    assert mg.run("remove", "demo", answer="no") == 1 and mg.get()["id"] == "demo"
    before_settings = mg.settings.read_text()
    assert mg.run("remove", "demo", "--yes", ok=False) == 1
    assert mg.get()["id"] == "demo" and mg.settings.read_text() == before_settings   # nothing half-done


def test_exclusion_is_not_duplicated(mg):
    manage.add_exclusion(mg.settings, "octo/demo"); manage.add_exclusion(mg.settings, "OCTO/demo")
    assert json.loads(mg.settings.read_text())["exclude_repos"].count("octo/demo") == 1


def test_list_shows_state_and_locks(mg, capsys):
    mg.run("pin", "demo", "category"); mg.run("hide", "other"); capsys.readouterr()
    mg.run("list")
    out = capsys.readouterr().out
    assert "locked: primary_category" in out and "hidden" in out


HEAD = "d" * 40


def gh():
    return FakeClient({"/repos/octo/demo": {"default_branch": "main"},
                       "/repos/octo/demo/commits/main": {"sha": HEAD, "commit": {"committer": {"date": "2026-03-05T10:00:00Z"}}}})


def test_log_adds_an_entry_for_the_latest_commit_and_moves_tracking_forward(mg):
    assert mg.run("log", "demo", "Added a print button to the landing page", client=gh()) == 0
    p = mg.get()
    assert p["updates"][0] == {"commit": HEAD, "date": "2026-03-05", "type": "feature", "summary": "Added a print button to the landing page"}
    assert p["last_analyzed_commit"] == HEAD and p["last_updated"] == "2026-03-05" and len(p["updates"]) == 2
    assert mg.run("log", "demo", "Added a print button to the landing page", client=gh()) == 1      # same commit again


def test_log_with_an_explicit_commit_does_not_move_tracking(mg):
    assert mg.run("log", "demo", "Fixed the footer layout on phones", "--type", "fix", "--commit", "ABC1234", "--date", "2026-02-15") == 0
    p = mg.get()
    assert p["updates"][0]["commit"] == "abc1234" and p["updates"][0]["type"] == "fix" and p["last_analyzed_commit"] == "a" * 40


def test_log_rejects_bad_input_and_changes_nothing(mg, capsys):
    before = mg.projects.read_text()
    assert mg.run("log", "demo", "short", client=gh()) == 1
    assert mg.run("log", "demo", "A perfectly good summary here", "--type", "miracle", client=gh()) == 1
    assert mg.run("log", "demo", "A perfectly good summary here", "--date", "2025-01-01", client=gh()) == 1
    assert mg.run("log", "demo", "A perfectly good summary here", "--date", "not-a-date", client=gh()) == 1
    assert mg.run("log", "demo", "A perfectly good summary here", "--commit", "xyz") == 1
    assert mg.projects.read_text() == before


def test_log_explains_what_to_do_when_github_cannot_be_reached(mg, capsys):
    broken = FakeClient({"/repos/octo/demo": GitHubError(403, "rate limited", "x")})
    assert mg.run("log", "demo", "A perfectly good summary here", client=broken) == 1
    assert "GH_TOKEN" in capsys.readouterr().out
