"""Minimal GitHub REST client: pagination, retries with backoff, rate-limit handling.

Read-only. The token (if any) is only ever placed in the Authorization header.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any
from urllib.parse import quote

import requests

API = "https://api.github.com"
log = logging.getLogger("agent.github")


class GitHubError(Exception):
    def __init__(self, status: int, message: str, path: str = ""):
        super().__init__(f"GitHub API {status} for {path}: {message}")
        self.status = status
        self.path = path


class NotFound(GitHubError):
    pass


class EmptyRepository(GitHubError):
    pass


class RateLimited(GitHubError):
    pass


def q(value: str, safe: str = "") -> str:
    return quote(value, safe=safe)


class GitHubClient:
    def __init__(self, token: str | None = None, base_url: str = API, session=None,
                 max_retries: int = 4, max_rate_wait: int = 90, sleep=time.sleep):
        self._token = token or None
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.max_rate_wait = max_rate_wait
        self._sleep = sleep

    @property
    def authenticated(self) -> bool:
        return self._token is not None

    def _headers(self, accept: str | None) -> dict[str, str]:
        headers = {
            "Accept": accept or "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "autoportfolio-agent",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(30.0, 2 ** attempt + random.random()))

    def request(self, path: str, params: dict | None = None, accept: str | None = None):
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        attempt = 0
        while True:
            try:
                resp = self.session.get(url, headers=self._headers(accept), params=params, timeout=30)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.max_retries:
                    raise GitHubError(0, f"network error ({type(exc).__name__})", path) from exc
                log.warning("event=retry reason=network path=%s attempt=%d", path, attempt + 1)
                self._backoff(attempt)
                attempt += 1
                continue

            status = resp.status_code
            if status == 200:
                return resp

            message = ""
            try:
                message = str(resp.json().get("message", ""))[:200]
            except Exception:
                pass

            if status == 404:
                raise NotFound(status, message or "not found", path)
            if status == 409:
                raise EmptyRepository(status, message or "conflict (repository may be empty)", path)

            if status in (403, 429):
                retry_after = resp.headers.get("Retry-After")
                remaining = resp.headers.get("X-RateLimit-Remaining")
                if retry_after or remaining == "0":
                    if retry_after:
                        wait = int(retry_after)
                    else:
                        wait = max(0, int(resp.headers.get("X-RateLimit-Reset", "0")) - int(time.time())) + 1
                    if wait > self.max_rate_wait or attempt >= self.max_retries:
                        raise RateLimited(status, f"rate limit reached; resets in about {wait}s", path)
                    log.warning("event=retry reason=rate_limit path=%s wait=%ds", path, wait)
                    self._sleep(wait)
                    attempt += 1
                    continue
                raise GitHubError(status, message or "forbidden", path)

            if status >= 500:
                if attempt >= self.max_retries:
                    raise GitHubError(status, message or "server error", path)
                log.warning("event=retry reason=server_error path=%s status=%d attempt=%d", path, status, attempt + 1)
                self._backoff(attempt)
                attempt += 1
                continue

            raise GitHubError(status, message or "unexpected response", path)

    def get_json(self, path: str, params: dict | None = None) -> Any:
        return self.request(path, params).json()

    def paginate(self, path: str, params: dict | None = None, max_pages: int = 20) -> list[Any]:
        items: list[Any] = []
        url: str | None = path
        page_params = dict(params or {})
        for _ in range(max_pages):
            resp = self.request(url, page_params)
            data = resp.json()
            items.extend(data if isinstance(data, list) else [data])
            nxt = resp.links.get("next", {}).get("url") if hasattr(resp, "links") else None
            if not nxt:
                break
            url, page_params = nxt, None
        return items

    def get_raw(self, path: str, params: dict | None = None) -> bytes:
        return self.request(path, params, accept="application/vnd.github.raw+json").content
