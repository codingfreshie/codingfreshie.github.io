import json

from agent import collect
from .conftest import FakeClient, repo
from .test_fetcher import FULL, routes


def test_run_end_to_end_writes_outputs_and_is_repeatable(tmp_path, monkeypatch, settings):
    projects = tmp_path / "projects.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": []}))

    r = routes([("README.md", 50), ("main.py", 30)])
    r["/users/octo/repos"] = [repo(7, "demo"), repo(8, "octo.github.io")]
    raw = {f"/repos/{FULL}/contents/README.md": "# Demo", f"/repos/{FULL}/contents/main.py": "print(1)"}
    client = FakeClient(r, raw)

    monkeypatch.setattr(collect, "_client", lambda: client)
    monkeypatch.setattr(collect, "load_settings", lambda: settings)
    monkeypatch.setattr(collect, "PROJECTS_PATH", projects)

    out = tmp_path / "out"
    assert collect.main(["--out", str(out), "run"]) == 0

    discovery = json.loads((out / "discovery.json").read_text())
    assert [x["full_name"] for x in discovery["new"]] == [FULL]
    assert discovery["skipped"][0]["reason"] == "excluded"          # portfolio repo ignored
    bundle = json.loads((out / "bundles" / "bundle-7.json").read_text())  # named by numeric id
    assert bundle["head_commit"]["sha"] == "abc1234def"
    assert "Portfolio agent" in (out / "summary.md").read_text()

    # Once the project is recorded, the same repo is no longer "new" (idempotent).
    projects.write_text(json.dumps({"schema_version": 1, "projects": [
        {"id": "demo", "repository_id": 7, "repository_url": f"https://github.com/{FULL}", "status": "active"}]}))
    assert collect.main(["--out", str(out), "discover"]) == 0
    assert json.loads((out / "discovery.json").read_text())["new"] == []


def test_one_failing_repo_does_not_stop_the_run(tmp_path, monkeypatch, settings):
    projects = tmp_path / "projects.json"
    projects.write_text(json.dumps({"schema_version": 1, "projects": []}))
    r = routes([("README.md", 50)])
    r["/users/octo/repos"] = [repo(1, "broken", pushed_at="2026-06-01T00:00:00Z"), repo(7, "demo")]
    client = FakeClient(r, {f"/repos/{FULL}/contents/README.md": "# Demo"})   # no routes for octo/broken -> KeyError

    monkeypatch.setattr(collect, "_client", lambda: client)
    monkeypatch.setattr(collect, "load_settings", lambda: settings)
    monkeypatch.setattr(collect, "PROJECTS_PATH", projects)

    assert collect.main(["--out", str(tmp_path / "o"), "run"]) == 0
    assert (tmp_path / "o" / "bundles" / "bundle-7.json").exists()
    assert collect.main(["--out", str(tmp_path / "o"), "--strict", "run"]) == 1
