import json
from pathlib import Path

import pytest

from agent import pipeline
from agent.pipeline import run_pipeline, summarize
from .test_manage import full

ROOT = Path(__file__).resolve().parents[2]


# ---------- the summary that becomes the pull request description ----------
def test_summary_describes_each_kind_of_change(tmp_path):
    before = {"projects": [full("kept", 1), full("renamed", 2), full("gone", 3)]}
    after = json.loads(json.dumps(before))
    after["projects"].append(full("fresh", 4, name="Fresh", description="A brand new project description."))
    after["projects"][0]["updates"].insert(0, {"commit": "c" * 40, "date": "2026-03-01", "type": "fix", "summary": "Fixed a crash on empty input."})
    after["projects"][1]["repository_url"] = "https://github.com/octo/renamed-2"
    after["projects"][2]["status"] = "archived"
    body, counts = summarize(before, after, tmp_path, ["add timeline entries"])
    assert counts == {"new_projects": 1, "timeline_entries": 1, "hidden": 1, "renamed": 1}
    for needle in ("**Fresh**", "Fixed a crash on empty input.", "unhide gone", "renamed-2", "add timeline entries"):
        assert needle in body


def test_summary_says_so_when_nothing_changed(tmp_path):
    data = {"projects": [full("a", 1)]}
    body, counts = summarize(data, data, tmp_path, [])
    assert "No changes." in body and not any(counts.values())


def test_summary_surfaces_stale_descriptions_and_unapplied_flagged_changes(tmp_path):
    data = {"projects": [full("a", 1)]}
    (tmp_path / "updates").mkdir()
    (tmp_path / "updates" / "update-a-x.json").write_text(json.dumps({"project_id": "a", "base_commit": "a" * 40, "flags": ["ignore_instructions"]}))
    (tmp_path / "stale.json").write_text(json.dumps({"a": "it is now a scraper"}))
    body, _ = summarize(data, data, tmp_path, [])
    assert "suspicious text" in body and "refresh run --project a" in body and "No changes." not in body


# ---------- running the stages ----------
@pytest.fixture
def projects_file(tmp_path, monkeypatch):
    p = tmp_path / "projects.json"
    p.write_text(json.dumps({"schema_version": 1, "projects": [full("a", 1)]}))
    monkeypatch.setattr(pipeline, "PROJECTS_PATH", p)
    return p


def stage(calls, name, writes, code=0, **kw):
    def main(argv):
        calls.append(name)
        if code == "boom":
            raise RuntimeError("secret detail that must not be printed")
        return code
    return {"name": name, "main": main, "args": ["x"], "writes": writes, **kw}


def test_stages_run_in_order_and_dry_run_skips_the_writing_ones(tmp_path, projects_file):
    calls = []
    stages = [stage(calls, "collect", False), stage(calls, "apply", True), stage(calls, "track", False)]
    run_pipeline(tmp_path, dry_run=False, stages=stages, preview=[])
    assert calls == ["collect", "apply", "track"]
    calls.clear()
    run_pipeline(tmp_path, dry_run=True, stages=stages, preview=[stage(calls, "preview", False)])
    assert calls == ["collect", "track", "preview"]


def test_a_failing_or_crashing_stage_does_not_stop_the_rest(tmp_path, projects_file, capsys):
    calls = []
    stages = [stage(calls, "one", False, code=1), stage(calls, "two", False, code="boom"), stage(calls, "three", False)]
    result = run_pipeline(tmp_path, stages=stages, preview=[])
    assert calls == ["one", "two", "three"] and result["errors"] == ["one", "two"]
    assert "secret detail" not in capsys.readouterr().out                  # error text from a crash is never echoed
    assert "will be retried" in result["body"]


def test_stage_with_nothing_to_do_is_skipped_quietly(tmp_path, projects_file):
    calls = []
    result = run_pipeline(tmp_path, stages=[stage(calls, "analyze", False, skip_if=lambda out: "no new repositories")], preview=[])
    assert calls == [] and result["errors"] == []


def test_exit_code_is_failure_only_when_something_failed_and_nothing_was_achieved(tmp_path, projects_file, monkeypatch):
    monkeypatch.setattr(pipeline, "run_pipeline", lambda out, dry: {"errors": ["x"], "counts": {"a": 0}, "body": ""})
    assert pipeline.main(["--out", str(tmp_path), "run"]) == 1
    monkeypatch.setattr(pipeline, "run_pipeline", lambda out, dry: {"errors": ["x"], "counts": {"a": 2}, "body": ""})
    assert pipeline.main(["--out", str(tmp_path), "run"]) == 0


def test_default_stage_list_is_the_expected_chain():
    names = [s["name"] for s in pipeline._stages()]
    assert names == ["collect new repositories", "analyze new repositories", "add new projects", "check commits on existing projects",
                     "add timeline entries", "check renamed and removed repositories", "apply renames and hide removed repositories"]


# ---------- the workflow file must keep its safety properties ----------
@pytest.fixture(scope="module")
def workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / ".github" / "workflows" / "agent.yml").read_text("utf-8"))


def test_workflow_has_least_privilege_and_an_off_switch(workflow):
    assert workflow["permissions"] == {"contents": "write", "pull-requests": "write"}
    job = workflow["jobs"]["update"]
    assert "AUTOMATION_ENABLED" in job["if"] and "workflow_dispatch" in job["if"]
    assert "timeout-minutes" in job and workflow["concurrency"]["cancel-in-progress"] is False


def test_workflow_only_uses_github_own_actions_and_defaults_to_dry_run(workflow):
    uses = [s["uses"] for s in workflow["jobs"]["update"]["steps"] if "uses" in s]
    assert uses and all(u.startswith("actions/") for u in uses)           # no third-party code with write access
    trigger = workflow.get("on") or workflow[True]                        # PyYAML reads `on:` as the boolean True
    assert trigger["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True
    assert "schedule" in trigger and "pull_request" not in trigger        # never runs on pull requests from forks


def test_workflow_cannot_publish_without_review_and_never_echoes_secrets(workflow):
    steps = workflow["jobs"]["update"]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)
    assert 'git push --force origin "$BRANCH"' in runs and "git push origin main" not in runs
    assert "--base main" in runs and "gh pr merge" not in runs            # a human merges
    pr_step = next(step for step in steps if step.get("name") == "Open or update the pull request")
    assert "DRY_RUN" in pr_step["if"]                                       # dry runs never open one
    assert "echo" not in "".join(l for l in runs.splitlines() if "secrets" in l or "GEMINI_API_KEY" in l or "GH_TOKEN" in l)
    agent_step = next(step for step in steps if step.get("name") == "Run the agent")
    assert agent_step["env"]["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"
    others = [step for step in steps if step is not agent_step]
    assert not any("GEMINI_API_KEY" in json.dumps(step) for step in others)  # the key reaches only the one step that needs it
