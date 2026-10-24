import json
from types import SimpleNamespace

import pytest

from agent import refresh
from agent.refresh import apply_refresh, compute_changes, render_proposal
from .conftest import FakeClient, repo
from .test_analysis import answer, gemini
from .test_fetcher import FULL, routes
from .test_manage import full

OK = lambda: (True, "")
README = "# Doc QA\n" + "Answers questions over PDF documents using FAISS retrieval and an LLM. " * 8


def proposal(project, **new):
    n = {**project, **new}
    return {"project_id": project["id"], "full_name": "octo/demo", "head_commit": "c" * 40,
            "changes": compute_changes(project, n, set(project.get("locked", []))), "new_confidence": 0.8,
            "review_reasons": [], "flags": [], "category_reasoning": "x", "model": "m"}


def test_changes_cover_only_generated_fields_and_never_erase_known_values():
    old = full("demo", 7, overview="Old overview", development_status="in_progress")
    new = {**old, "description": "A brand new description here.", "overview": None, "development_status": None,
           "updates": [], "last_analyzed_commit": "z" * 40, "repository_url": "https://github.com/x/y"}
    assert [c["field"] for c in compute_changes(old, new, set())] == ["description"]


def test_locked_fields_are_listed_but_never_applied(tmp_path):
    p = full("demo", 7, locked=["primary_category"])
    projects = tmp_path / "p.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [p]}))
    prop = proposal(p, primary_category="ml", description="A brand new description here.")
    assert any(c["field"] == "primary_category" and c["locked"] for c in prop["changes"])
    res = apply_refresh([prop], projects, OK)
    saved = json.loads(projects.read_text())["projects"][0]
    assert saved["primary_category"] == "ai-llm" and saved["description"] == "A brand new description here."
    assert ("demo", "primary_category", "locked") in res["skipped"]


def test_timeline_baseline_and_identity_are_never_touched(tmp_path):
    p = full("demo", 7)
    projects = tmp_path / "p.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [p]}))
    prop = proposal(p, description="A brand new description here.", features=["Better feature"], tags=["New"])
    apply_refresh([prop], projects, OK)
    saved = json.loads(projects.read_text())["projects"][0]
    for key in ("updates", "last_analyzed_commit", "id", "repository_id", "repository_url", "created_at", "last_updated", "status"):
        assert saved[key] == p[key], key
    assert saved["features"] == ["Better feature"] and saved["needs_review"] is False and saved["confidence"] == 0.8


def test_a_hand_edit_made_after_the_proposal_is_not_overwritten(tmp_path):
    p = full("demo", 7)
    projects = tmp_path / "p.json"
    prop = proposal(p, description="Model wording that is long enough.", tags=["Model Tag"])
    edited = {**p, "description": "My own careful wording, kept safe."}
    projects.write_text(json.dumps({"schema_version": 1, "projects": [edited]}))
    res = apply_refresh([prop], projects, OK)
    saved = json.loads(projects.read_text())["projects"][0]
    assert saved["description"] == "My own careful wording, kept safe." and saved["tags"] == ["Model Tag"]
    assert any(f == "description" and "edited" in why for _, f, why in res["skipped"])


def test_only_applies_just_those_fields_and_keeps_the_rest_available(tmp_path):
    p = full("demo", 7)
    projects = tmp_path / "p.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [p]}))
    prop = proposal(p, description="A brand new description here.", tags=["New"])
    apply_refresh([prop], projects, OK, only={"tags"})
    saved = json.loads(projects.read_text())["projects"][0]
    assert saved["tags"] == ["New"] and saved["description"] == p["description"] and saved["confidence"] == 0.9
    apply_refresh([prop], projects, OK, only={"description"})            # same proposal still usable for the rest
    assert json.loads(projects.read_text())["projects"][0]["description"] == "A brand new description here."


def test_flagged_proposal_needs_explicit_approval(tmp_path):
    p = full("demo", 7)
    projects = tmp_path / "p.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [p]}))
    prop = {**proposal(p, description="A brand new description here."), "flags": ["injection_suspected"]}
    assert apply_refresh([prop], projects, OK)["applied"] == {}
    assert apply_refresh([prop], projects, OK, include_flagged=True)["applied"] == {"demo": ["description"]}


def test_validation_failure_restores_the_file(tmp_path):
    p = full("demo", 7)
    projects = tmp_path / "p.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": [p]}))
    before = projects.read_text()
    res = apply_refresh([proposal(p, description="A brand new description here.")], projects, lambda: (False, "bad"))
    assert not res["ok"] and res["applied"] == {} and projects.read_text() == before


def test_render_marks_locked_fields_and_shows_list_differences():
    p = full("demo", 7, locked=["tags"])
    text = render_proposal(proposal(p, tags=["New"], features=["One feature", "Added feature"]))
    assert "LOCKED" in text and "+ Added feature" in text


# ---------- full run: GitHub + model -> proposal -> apply ----------
@pytest.fixture
def env(tmp_path, monkeypatch, settings):
    projects = tmp_path / "projects.json"
    mine = full("demo", 7, description="Hand-tuned wording that I want to keep.", locked=["description"])
    projects.write_text(json.dumps({"schema_version": 1, "projects": [mine]}))
    monkeypatch.setattr(refresh, "PROJECTS_PATH", projects)
    monkeypatch.setattr(refresh, "load_settings", lambda: settings)
    tree = [("README.md", 800), ("requirements.txt", 30), ("app.py", 700)]
    r = routes(tree)
    r["/users/octo/repos"] = [repo(7, "demo", default_branch="main")]
    raw = {f"/repos/{FULL}/contents/README.md": README, f"/repos/{FULL}/contents/requirements.txt": "faiss-cpu\nlangchain\n",
           f"/repos/{FULL}/contents/app.py": "import faiss\n" + "def answer(): pass\n" * 40}

    def run(*argv, responses=(answer(tags=["Doc QA"]),)):
        g, models, _ = gemini(*responses)
        monkeypatch.setattr(refresh, "GitHubClient", lambda token=None: FakeClient(r, raw))
        monkeypatch.setattr(refresh, "GeminiClient", lambda *a, **k: g)
        return refresh.main(["--out", str(tmp_path / "out"), *argv], validator=OK)   # never shell out to Node in tests
    return SimpleNamespace(run=run, projects=projects, out=tmp_path / "out")


def test_refresh_end_to_end_keeps_locked_text_and_timeline(env, capsys):
    (env.out).mkdir(parents=True)
    (env.out / "stale.json").write_text(json.dumps({"demo": "purpose changed", "other": "x"}))
    assert env.run("run", "--project", "demo") == 0
    assert (env.out / "refresh" / "refresh-demo.json").exists()
    assert env.run("show") == 0 and "tags" in capsys.readouterr().out
    assert env.run("apply") == 0
    saved = json.loads(env.projects.read_text())["projects"][0]
    assert saved["description"] == "Hand-tuned wording that I want to keep."      # locked
    assert saved["tags"] == ["Doc QA"]                                            # refreshed
    assert len(saved["updates"]) == 1 and saved["last_analyzed_commit"] == "a" * 40
    assert json.loads((env.out / "stale.json").read_text()) == {"other": "x"}     # demo no longer stale


def test_run_needs_to_be_told_what_to_refresh(env, capsys):
    assert env.run("run") == 1 and "--project" in capsys.readouterr().out
    assert env.run("run", "--project", "nope") == 1
