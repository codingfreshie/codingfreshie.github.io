import base64
import hashlib
from pathlib import Path

import pytest

from agent.github_client import GitHubError, NotFound, EmptyRepository
from agent.settings import Settings


class FakeClient:
    """Stands in for GitHubClient. routes maps a path to a payload or an exception."""

    authenticated = True

    def __init__(self, routes=None, raw=None):
        self.routes = routes or {}
        self.raw = raw or {}
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append(path)
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return value

    def get_raw(self, path, params=None):
        self.calls.append(path)
        value = self.raw[path]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, bytes) else value.encode()

    def paginate(self, path, params=None, max_pages=20):
        return self.routes[path]


@pytest.fixture
def settings():
    return Settings(github_username="octo", exclude_repos=frozenset({"octo.github.io"}))


def repo(rid, name, **kw):
    base = {
        "id": rid, "name": name, "full_name": f"octo/{name}", "html_url": f"https://github.com/octo/{name}",
        "private": False, "fork": False, "archived": False, "disabled": False,
        "language": "Python", "created_at": "2026-01-01T00:00:00Z", "pushed_at": "2026-05-01T00:00:00Z",
    }
    base.update(kw)
    return base


def project(pid, rid, name=None, **kw):
    name = name or pid
    base = {"id": pid, "repository_id": rid, "repository_url": f"https://github.com/octo/{name}", "status": "active"}
    base.update(kw)
    return base


ROOT = Path(__file__).resolve().parents[2]
GUARDED = [ROOT / "src" / "data" / "projects.json", ROOT / "src" / "data" / "categories.json", ROOT / "agent" / "settings.json"]


@pytest.fixture(autouse=True)
def _ignore_the_real_environment(monkeypatch):
    """Tests must behave the same on your laptop and inside GitHub Actions, and must never write to the real run."""
    for name in ("GITHUB_STEP_SUMMARY", "GITHUB_OUTPUT", "GITHUB_REPOSITORY", "GH_TOKEN", "GITHUB_TOKEN",
                 "GEMINI_API_KEY", "PORTFOLIO_GITHUB_USER"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session", autouse=True)
def _real_data_is_never_modified():
    """Fail the whole run if any test changes a real data file instead of a temporary copy."""
    def digest():
        return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None) for p in GUARDED}
    before = digest()
    yield
    assert digest() == before, "a test modified a real data file (projects.json, categories.json or settings.json)"
