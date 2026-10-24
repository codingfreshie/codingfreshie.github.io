import pytest

from agent.github_client import GitHubClient, GitHubError, NotFound, RateLimited


class Resp:
    def __init__(self, status=200, body=None, headers=None, links=None):
        self.status_code, self._body = status, body if body is not None else {}
        self.headers, self.links, self.content = headers or {}, links or {}, b"raw"

    def json(self):
        return self._body


class Session:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def get(self, url, headers=None, params=None, timeout=None):
        self.requests.append((url, headers))
        return self.responses.pop(0)


def client(*responses, **kw):
    s = Session(*responses)
    return GitHubClient(token="tok", session=s, sleep=lambda _s: None, **kw), s


def test_retries_server_errors_then_succeeds():
    c, s = client(Resp(502), Resp(503), Resp(200, {"ok": 1}))
    assert c.get_json("/x") == {"ok": 1} and len(s.requests) == 3


def test_gives_up_after_max_retries():
    c, _ = client(*[Resp(500)] * 6, max_retries=2)
    with pytest.raises(GitHubError):
        c.get_json("/x")


def test_short_rate_limit_waits_and_retries():
    c, _ = client(Resp(403, headers={"X-RateLimit-Remaining": "0", "Retry-After": "2"}), Resp(200, {"ok": 1}))
    assert c.get_json("/x") == {"ok": 1}


def test_long_rate_limit_raises_instead_of_hanging():
    c, _ = client(Resp(429, headers={"Retry-After": "3600"}))
    with pytest.raises(RateLimited):
        c.get_json("/x")


def test_not_found_raises():
    c, _ = client(Resp(404, {"message": "Not Found"}))
    with pytest.raises(NotFound):
        c.get_json("/x")


def test_pagination_follows_next_links():
    c, s = client(Resp(200, [1, 2], links={"next": {"url": "https://api.github.com/p2"}}), Resp(200, [3]))
    assert c.paginate("/p1") == [1, 2, 3] and s.requests[1][0] == "https://api.github.com/p2"


def test_token_only_in_authorization_header():
    c, s = client(Resp(200, {}))
    c.get_json("/x", {"a": "b"})
    url, headers = s.requests[0]
    assert "tok" not in url and headers["Authorization"] == "Bearer tok"
