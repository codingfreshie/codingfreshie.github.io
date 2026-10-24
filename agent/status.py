"""Accounts for every public repository: where is it in the pipeline, and why?"""
from __future__ import annotations

import json
from pathlib import Path

from .settings import Settings


def _ids(folder: Path, prefix: str) -> set[int]:
    return {int(p.stem.removeprefix(prefix)) for p in folder.glob(f"{prefix}*.json") if p.stem.removeprefix(prefix).isdigit()}


def _log(path: Path) -> dict:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def build_status(api_repos: list[dict], projects: list[dict], out_dir: Path, settings: Settings) -> list[dict]:
    in_portfolio = {p["repository_id"] for p in projects}
    bundles = _ids(out_dir / "bundles", "bundle-")
    drafts = _ids(out_dir / "drafts", "draft-")
    collect_log, analysis_log = _log(out_dir / "collect_log.json"), _log(out_dir / "analysis_log.json")

    rows = []
    for r in api_repos:
        rid, name = r["id"], r["full_name"]
        flags = ", ".join(x for x, on in (("fork", r.get("fork")), ("archived", r.get("archived"))) if on)
        if r.get("private"):
            state, detail = "skipped", "private"
        elif name.lower() in settings.exclude_repos or r["name"].lower() in settings.exclude_repos:
            state, detail = "excluded", "listed in exclude_repos (your portfolio repo)"
        elif rid in in_portfolio:
            state, detail = "in portfolio", ""
        elif rid in drafts:
            state, detail = "draft ready", "run: python -m agent.analyze apply"
        elif rid in bundles:
            err = analysis_log.get(name)
            state = "analysis failed" if err else "collected"
            detail = err or "run: python -m agent.analyze run"
        elif r.get("fork") and not settings.include_forks:
            state, detail = "skipped", "fork (include_forks is false)"
        elif r.get("archived") and not settings.include_archived_new:
            state, detail = "skipped", 'archived (set "include_archived_new": true to include)'
        elif name in collect_log and collect_log[name]["status"] != "collected":
            entry = collect_log[name]
            state, detail = f"collect {entry['status']}", entry.get("detail", "")
        else:
            state, detail = "not collected", "run: python -m agent.collect run (raise max_new_repos_per_run if needed)"
        rows.append({"repo": name, "state": state, "detail": detail, "flags": flags})
    return rows


def render_status(rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    lines = [f"Public repositories found: {len(rows)}", ""]
    lines += [f"  {n:>3}  {state}" for state, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    lines += ["", "Private repositories are never scanned, so GitHub's own total will be higher.", ""]
    todo = [r for r in rows if r["state"] not in ("in portfolio", "excluded")]
    if todo:
        lines.append("Not yet in your portfolio:")
        for r in sorted(todo, key=lambda r: (r["state"], r["repo"])):
            tag = f" [{r['flags']}]" if r["flags"] else ""
            lines.append(f"  - {r['repo']}{tag}: {r['state']}" + (f" ({r['detail']})" if r["detail"] else ""))
    else:
        lines.append("Every public repository is accounted for.")
    return "\n".join(lines) + "\n"
