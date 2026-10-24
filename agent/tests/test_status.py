import json

from agent.status import build_status, render_status
from .conftest import project, repo


def test_every_state_is_explained(tmp_path, settings):
    (tmp_path / "bundles").mkdir(); (tmp_path / "drafts").mkdir()
    (tmp_path / "bundles" / "bundle-3.json").write_text("{}")
    (tmp_path / "bundles" / "bundle-4.json").write_text("{}")
    (tmp_path / "drafts" / "draft-2.json").write_text("{}")
    (tmp_path / "collect_log.json").write_text(json.dumps({"octo/emptyrepo": {"status": "skipped", "detail": "empty"}}))
    (tmp_path / "analysis_log.json").write_text(json.dumps({"octo/broken": "Gemini rate limit"}))
    api = [repo(1, "live"), repo(2, "drafted"), repo(3, "collected"), repo(4, "broken"),
           repo(5, "old", archived=True), repo(6, "emptyrepo"), repo(7, "fresh"),
           repo(8, "octo.github.io"), repo(9, "private", private=True)]
    rows = {r["repo"].split("/")[1]: r for r in build_status(api, [project("live", 1)], tmp_path, settings)}
    assert rows["live"]["state"] == "in portfolio"
    assert rows["drafted"]["state"] == "draft ready"
    assert rows["collected"]["state"] == "collected"
    assert rows["broken"]["state"] == "analysis failed" and "rate limit" in rows["broken"]["detail"]
    assert rows["old"]["state"] == "skipped" and "archived" in rows["old"]["detail"]
    assert rows["emptyrepo"]["state"] == "collect skipped" and rows["emptyrepo"]["detail"] == "empty"
    assert rows["fresh"]["state"] == "not collected"
    assert rows["octo.github.io"]["state"] == "excluded"
    assert rows["private"]["detail"] == "private"


def test_render_lists_only_what_is_missing(tmp_path, settings):
    rows = build_status([repo(1, "live"), repo(2, "fresh")], [project("live", 1)], tmp_path, settings)
    text = render_status(rows)
    assert "Public repositories found: 2" in text and "octo/fresh" in text and "octo/live" not in text
    assert "Private repositories are never scanned" in text
