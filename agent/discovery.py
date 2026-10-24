"""Compares the user's GitHub repositories with projects.json. Read-only: it only reports."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .github_client import GitHubClient, q
from .settings import Settings


def list_user_repos(client: GitHubClient, username: str) -> list[dict]:
    """Public repositories owned by the user (forks included; the API omits private ones)."""
    return client.paginate(
        f"/users/{q(username)}/repos",
        {"type": "owner", "sort": "pushed", "direction": "desc", "per_page": 100},
    )


def load_projects(path: Path) -> list[dict]:
    return json.loads(Path(path).read_text("utf-8")).get("projects", [])


def _brief(r: dict) -> dict:
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "html_url": r["html_url"],
        "fork": bool(r.get("fork")),
        "archived": bool(r.get("archived")),
        "language": r.get("language"),
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
    }


def classify(api_repos: list[dict], projects: list[dict], settings: Settings) -> dict:
    """Match repos to projects by GitHub's numeric repository id (stable across renames)."""
    by_id = {p["repository_id"]: p for p in projects}
    seen: set[int] = set()
    report = {
        "new": [], "renamed": [], "newly_archived": [], "unarchived": [],
        "missing": [], "skipped": [], "unchanged": 0,
    }

    for r in api_repos:
        rid = r["id"]
        seen.add(rid)

        if r.get("private"):
            report["skipped"].append({"full_name": r["full_name"], "reason": "private"})
            continue
        if r["full_name"].lower() in settings.exclude_repos or r["name"].lower() in settings.exclude_repos:
            report["skipped"].append({"full_name": r["full_name"], "reason": "excluded"})
            continue
        if r.get("disabled"):
            report["skipped"].append({"full_name": r["full_name"], "reason": "disabled"})
            continue

        project = by_id.get(rid)
        if project:
            if project["repository_url"].lower() != r["html_url"].lower():
                report["renamed"].append({
                    "repository_id": rid, "project_id": project["id"],
                    "old_url": project["repository_url"], "new_url": r["html_url"],
                })
            if r.get("archived") and project.get("status") != "archived":
                report["newly_archived"].append({"repository_id": rid, "project_id": project["id"]})
            elif not r.get("archived") and project.get("status") == "archived":
                report["unarchived"].append({"repository_id": rid, "project_id": project["id"]})
            else:
                report["unchanged"] += 1
            continue

        if r.get("fork") and not settings.include_forks:
            report["skipped"].append({"full_name": r["full_name"], "reason": "fork"})
        elif r.get("archived") and not settings.include_archived_new:
            report["skipped"].append({"full_name": r["full_name"], "reason": "archived"})
        else:
            report["new"].append(_brief(r))

    # Present in the portfolio but no longer visible: deleted, or made private.
    # Never auto-deleted; surfaced so the change can be reviewed in a PR.
    report["missing"] = [
        {"project_id": p["id"], "repository_id": p["repository_id"], "repository_url": p["repository_url"]}
        for p in projects
        if p["repository_id"] not in seen and p.get("status") != "archived"
    ]
    return report


def discover(client: GitHubClient, settings: Settings, projects_path: Path) -> dict:
    api_repos = list_user_repos(client, settings.github_username)
    projects = load_projects(projects_path)
    report = classify(api_repos, projects, settings)

    # Process the most recently active repos first; defer the rest to later runs.
    report["new"].sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    cap = settings.max_new_repos_per_run
    report["to_collect"] = report["new"][:cap]
    report["deferred"] = report["new"][cap:]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "username": settings.github_username,
        "repos_seen": len(api_repos),
        "authenticated": client.authenticated,
        **report,
    }
