from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, fields
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
ROOT = AGENT_DIR.parent
DEFAULT_SETTINGS_PATH = AGENT_DIR / "settings.json"
PROJECTS_PATH = ROOT / "src" / "data" / "projects.json"
OUT_DIR = AGENT_DIR / "out"

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


@dataclass(frozen=True)
class Limits:
    max_tree_entries: int = 8000
    max_listed_paths: int = 400
    max_files_read: int = 14
    max_file_bytes: int = 120_000
    max_chars_per_file: int = 24_000
    max_readme_chars: int = 16_000
    max_total_chars: int = 80_000


@dataclass(frozen=True)
class Settings:
    github_username: str
    include_forks: bool = True
    include_archived_new: bool = False
    readme_first: bool = True
    gemini_model: str = "gemini-3.1-flash-lite"
    min_seconds_between_calls: float = 7.0
    min_confidence: float = 0.6
    exclude_repos: frozenset = frozenset()
    max_new_repos_per_run: int = 5
    limits: Limits = Limits()


def load_settings(path: Path | str | None = None) -> Settings:
    raw = json.loads(Path(path or DEFAULT_SETTINGS_PATH).read_text("utf-8"))
    username = os.environ.get("PORTFOLIO_GITHUB_USER") or raw.get("github_username")
    if not username or not USERNAME_RE.match(username):
        raise ValueError("settings: github_username is missing or not a valid GitHub username")

    excludes = {str(x).lower() for x in raw.get("exclude_repos", [])}
    # Never let the portfolio repo list itself as a project.
    own_repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in own_repo:
        excludes.add(own_repo.split("/", 1)[1].lower())

    known = {f.name for f in fields(Limits)}
    limits = Limits(**{k: int(v) for k, v in raw.get("limits", {}).items() if k in known})
    return Settings(
        github_username=username,
        include_forks=bool(raw.get("include_forks", True)),
        include_archived_new=bool(raw.get("include_archived_new", False)),
        readme_first=bool(raw.get("readme_first", True)),
        gemini_model=str(raw.get("gemini_model", "gemini-3.1-flash-lite")),
        min_seconds_between_calls=float(raw.get("min_seconds_between_calls", 7.0)),
        min_confidence=float(raw.get("min_confidence", 0.6)),
        exclude_repos=frozenset(excludes),
        max_new_repos_per_run=int(raw.get("max_new_repos_per_run", 5)),
        limits=limits,
    )
