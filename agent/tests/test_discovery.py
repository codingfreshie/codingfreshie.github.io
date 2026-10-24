from agent.discovery import classify
from .conftest import project, repo


def test_new_repo_detected(settings):
    r = classify([repo(1, "alpha")], [], settings)
    assert [x["full_name"] for x in r["new"]] == ["octo/alpha"]


def test_existing_repo_is_not_new_even_if_run_twice(settings):
    projects = [project("alpha", 1)]
    first = classify([repo(1, "alpha")], projects, settings)
    second = classify([repo(1, "alpha")], projects, settings)
    assert first["new"] == second["new"] == []
    assert first["unchanged"] == 1


def test_rename_is_detected_by_id_not_duplicated(settings):
    r = classify([repo(1, "alpha-renamed")], [project("alpha", 1, name="alpha")], settings)
    assert r["new"] == []
    assert r["renamed"][0]["new_url"].endswith("alpha-renamed")


def test_archived_and_unarchived_transitions(settings):
    r = classify([repo(1, "a", archived=True), repo(2, "b")],
                 [project("a", 1), project("b", 2, status="archived")], settings)
    assert [x["project_id"] for x in r["newly_archived"]] == ["a"]
    assert [x["project_id"] for x in r["unarchived"]] == ["b"]


def test_deleted_or_private_repo_is_reported_missing_not_removed(settings):
    r = classify([], [project("gone", 9)], settings)
    assert r["missing"][0]["project_id"] == "gone"


def test_forks_included_by_default(settings):
    r = classify([repo(3, "forked", fork=True)], [], settings)
    assert len(r["new"]) == 1 and r["new"][0]["fork"] is True


def test_archived_new_repo_skipped_by_default(settings):
    r = classify([repo(4, "old", archived=True)], [], settings)
    assert r["new"] == [] and r["skipped"][0]["reason"] == "archived"


def test_portfolio_repo_never_added_to_itself(settings):
    r = classify([repo(5, "octo.github.io")], [], settings)
    assert r["new"] == [] and r["skipped"][0]["reason"] == "excluded"


def test_private_repos_never_collected(settings):
    r = classify([repo(6, "secret", private=True)], [], settings)
    assert r["new"] == [] and r["skipped"][0]["reason"] == "private"
