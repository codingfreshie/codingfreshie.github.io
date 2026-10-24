import base64
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
