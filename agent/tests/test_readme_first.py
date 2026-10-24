import dataclasses

from agent.fetcher import collect_repo
from agent.readme import assess_readme
from .conftest import FakeClient
from .test_fetcher import FULL, routes

CLEAR = "# Trip Planner\n\n" + "This project helps people plan multi-city trips by comparing routes and prices. " * 8 + \
        "\n\n```bash\npip install -r requirements.txt\n```\n"
TREE = [("README.md", 900), ("requirements.txt", 40), ("main.py", 600), ("planner.py", 5000), ("routes.py", 4000)]


def raw(readme):
    return {f"/repos/{FULL}/contents/README.md": readme,
            f"/repos/{FULL}/contents/requirements.txt": "flask\n",
            f"/repos/{FULL}/contents/main.py": "print('hi')\n" * 60,
            f"/repos/{FULL}/contents/planner.py": "def plan(): pass\n" * 300,
            f"/repos/{FULL}/contents/routes.py": "def route(): pass\n" * 250}


def paths(bundle):
    return [f["path"] for f in bundle["files"]]


def test_assessment_clear_short_boilerplate_and_unfinished():
    assert assess_readme(CLEAR)["trustworthy"]
    assert not assess_readme("# Demo\nA demo app.")["clear"]
    cra = "# Getting Started with Create React App\n\nThis project was bootstrapped with Create React App. " * 10
    assert assess_readme(cra)["boilerplate"] and not assess_readme(cra)["clear"]
    wip = assess_readme(CLEAR + "\n## Roadmap\n- more things\n")
    assert wip["clear"] and wip["unfinished"] and not wip["trustworthy"]


def test_todo_app_is_not_mistaken_for_unfinished():
    assert assess_readme(CLEAR.replace("trips", "to-do lists"))["unfinished"] == []


def test_clear_readme_skips_broad_code_reading(settings):
    b = collect_repo(FakeClient(routes(TREE), raw(CLEAR)), FULL, settings)
    assert b["evidence"]["mode"] == "readme_first"
    assert paths(b) == ["README.md", "requirements.txt", "main.py"]
    assert b["review_reasons"] == []


def test_unfinished_readme_still_reads_code_and_flags_it(settings):
    b = collect_repo(FakeClient(routes(TREE), raw(CLEAR + "\n## Planned features\n- booking\n")), FULL, settings)
    assert b["evidence"]["mode"] == "code_first"
    assert {"planner.py", "routes.py"} <= set(paths(b))
    assert "unfinished_markers" in b["review_reasons"]


def test_short_readme_falls_back_to_code(settings):
    b = collect_repo(FakeClient(routes(TREE), raw("# Trip planner\nPlans trips.")), FULL, settings)
    assert b["evidence"]["mode"] == "code_first" and "planner.py" in paths(b)
    assert "readme_unclear" in b["review_reasons"]


def test_readme_first_can_be_switched_off(settings):
    off = dataclasses.replace(settings, readme_first=False)
    b = collect_repo(FakeClient(routes(TREE), raw(CLEAR)), FULL, off)
    assert b["evidence"]["mode"] == "code_first" and "planner.py" in paths(b)


def test_no_readme_reads_code(settings):
    tree = [t for t in TREE if t[0] != "README.md"]
    b = collect_repo(FakeClient(routes(tree), raw("")), FULL, settings)
    assert b["evidence"] == {"mode": "code_first", "readme": None} and "no_readme" in b["review_reasons"]
