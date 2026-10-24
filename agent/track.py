"""Timeline tracking.

  python -m agent.track run [--limit N] [--project ID]   find new commits for each project and propose timeline entries
  python -m agent.track show                             readable view of the proposals
  python -m agent.track apply [--include-flagged]        merge proposals into projects.json (validated; restored on failure)

A project's baseline is the commit it was last analyzed at. Only later commits are ever considered.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import store
from .analyze import load_categories
from .changes import SYSTEM, Changes, build_prompt, fetch_changes, response_schema, triage, validate_change
from .apply import node_validator
from .discovery import list_user_repos, load_projects
from .gemini import AnalysisError, GeminiClient, ValidationFailed
from .github_client import GitHubClient, GitHubError, NotFound, q
from .log import setup_logging
from .settings import OUT_DIR, PROJECTS_PATH, Settings, load_settings

log = logging.getLogger("agent.track")


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def analyze_change(gemini: GeminiClient, project: dict, category_name: str, changes: Changes, relevant: list[dict],
                   ignored: dict, settings: Settings, attempts: int = 2) -> tuple[dict, list[str]]:
    feedback, last = None, None
    for _ in range(attempts):
        prompt, flags = build_prompt(project, category_name, changes, relevant, ignored, settings, feedback)
        raw = gemini.generate_json(SYSTEM, prompt, response_schema())
        try:
            return validate_change(raw, relevant), flags
        except ValidationFailed as exc:
            feedback, last = str(exc), exc
    raise last


def make_proposal(project: dict, repo: dict, changes: Changes, action: str, reason: str, result: dict | None,
                  flags: list[str], model: str | None) -> dict:
    base = {
        "project_id": project["id"], "repository_id": project["repository_id"], "full_name": repo["full_name"],
        "base_commit": project["last_analyzed_commit"], "head_commit": changes.head,
        "head_date": changes.head_date, "commits": changes.total_commits,
        "action": action, "reason": reason, "update": None, "description_stale": None,
        "flags": flags, "model": model,
    }
    if result and result["meaningful"]:
        base["action"] = "entry"
        base["update"] = {"commit": changes.head, "date": (changes.head_date or "")[:10], "type": result["type"],
                          "summary": result["summary"], "files": result["files"]}
        if result["purpose_changed"]:
            base["description_stale"] = result["purpose_change_reason"] or "the project's purpose may have changed"
    elif result:
        base["action"], base["reason"] = "baseline_only", "not a meaningful change"
    return base


def head_of(client, full_name: str, branch: str) -> dict:
    c = client.get_json(f"/repos/{full_name}/commits/{q(branch, '/')}")
    return {"sha": c["sha"], "date": (c.get("commit", {}).get("committer") or {}).get("date")}


def cmd_run(args, settings: Settings, client) -> int:
    projects = [p for p in load_projects(PROJECTS_PATH) if p.get("status") != "archived"]
    if args.project:
        projects = [p for p in projects if p["id"] == args.project]
    repos = {r["id"]: r for r in list_user_repos(client, settings.github_username)}
    categories = {c["id"]: c["name"] for c in load_categories()}
    gemini: GeminiClient | None = None
    rows, stale, handled = [], [], 0

    for project in projects:
        repo = repos.get(project["repository_id"])
        name = project["id"]
        if repo is None or repo.get("archived") or settings.is_excluded(repo["full_name"]):
            rows.append((name, "-", "skipped (not visible, archived or excluded)"))
            continue
        if args.limit and handled >= args.limit:
            break
        try:
            changes = fetch_changes(client, repo["full_name"], project["last_analyzed_commit"], repo["default_branch"])
        except NotFound:
            # The baseline commit is gone (force-push or rewritten history). Re-anchor without inventing history.
            try:
                h = head_of(client, repo["full_name"], repo["default_branch"])
            except GitHubError as exc:
                rows.append((name, "-", f"error: GitHub API {exc.status}"))
                continue
            changes = Changes("behind", project["last_analyzed_commit"], h["sha"], h["date"], 1)
        except GitHubError as exc:
            log.error("event=compare_failed project=%s status=%s", name, exc.status)
            rows.append((name, "-", f"error: GitHub API {exc.status}"))
            continue

        action, reason, relevant, ignored = triage(changes, settings.include_docs_updates)
        if action == "none":
            rows.append((name, "-", "no new commits"))
            continue
        handled += 1
        rng = f"{changes.base[:7]}..{(changes.head or '')[:7]} ({changes.total_commits} commits)"
        result, flags = None, []
        if action == "analyze":
            try:
                gemini = gemini or GeminiClient(settings.gemini_model, min_interval=settings.min_seconds_between_calls)
                result, flags = analyze_change(gemini, project, categories.get(project["primary_category"], ""),
                                               changes, relevant, ignored, settings)
            except AnalysisError as exc:
                log.error("event=change_analysis_failed project=%s error=%s", name, exc)
                rows.append((name, rng, f"analysis failed: {exc}"))
                if any(k in str(exc) for k in ("rate limit", "not found for this key", "GEMINI_API_KEY")):
                    break
                continue
        if action == "rebase" and not changes.head:      # branch moved to an older commit: find where it is now
            try:
                h = head_of(client, repo["full_name"], repo["default_branch"])
            except GitHubError as exc:
                rows.append((name, rng, f"error: GitHub API {exc.status}"))
                continue
            changes.head, changes.head_date = h["sha"], h["date"]
        proposal = make_proposal(project, repo, changes, "baseline_only" if action in ("baseline_only", "rebase") else action,
                                 reason, result, flags, gemini.model if gemini and result else None)
        folder = args.out / "updates"
        for old in folder.glob(f"update-{name}-*.json"):
            old.unlink()                      # the newest proposal for a project replaces earlier ones
        _write(folder / f"update-{name}-{(changes.head or 'x')[:7]}.json", proposal)
        rows.append((name, rng, proposal["action"] + (f": {proposal['update']['type']}" if proposal["update"] else f" ({proposal['reason']})")
                     + ("  [FLAGGED]" if flags else "")))
        if proposal["description_stale"]:
            stale.append((name, proposal["description_stale"]))

    if stale:
        try:
            marked = json.loads((args.out / "stale.json").read_text("utf-8"))
        except (OSError, ValueError):
            marked = {}
        marked.update(dict(stale))
        _write(args.out / "stale.json", marked)

    print(f"\n{'project':<36} {'commits':<34} result")
    for name, rng, outcome in rows:
        print(f"{name:<36} {rng:<34} {outcome}")
    for name, why in stale:
        print(f"\nDescription may be out of date for {name}: {why}")
    if stale:
        print("To update those descriptions: `python -m agent.refresh run --stale`.")
    print("\nNext: `python -m agent.track show`, then `python -m agent.track apply`.")
    return 0


def _proposals(out: Path) -> list[dict]:
    return [json.loads(p.read_text("utf-8")) for p in sorted((out / "updates").glob("update-*.json"))]


def render_proposal(p: dict) -> str:
    u = p["update"]
    lines = ["=" * 72, f"{p['project_id']}   {p['base_commit'][:7]} -> {(p['head_commit'] or '')[:7]}   ({p['commits']} commits)",
             f"  action: {p['action']}" + (f"  ({p['reason']})" if p["action"] == "baseline_only" else "")]
    if u:
        lines += [f"  type   : {u['type']}   date: {u['date']}", f"  summary: {u['summary']}", f"  files  : {', '.join(u['files']) or '-'}"]
    if p["flags"]:
        lines.append(f"  FLAGGED: suspicious text in the changes ({', '.join(p['flags'])}). Skipped by `apply` unless --include-flagged.")
    if p["description_stale"]:
        lines.append(f"  note   : project description may be out of date: {p['description_stale']}")
    return "\n".join(lines) + "\n"


def apply_updates(proposals: list[dict], projects_path: Path, validator=node_validator, include_flagged: bool = False) -> dict:
    original = Path(projects_path).read_text("utf-8")
    data = json.loads(original)
    by_id = {p["id"]: p for p in data["projects"]}
    added, advanced, skipped = [], [], []

    for p in proposals:
        project = by_id.get(p["project_id"])
        if project is None:
            skipped.append((p["project_id"], "project no longer in projects.json"))
        elif project["last_analyzed_commit"] != p["base_commit"]:
            skipped.append((p["project_id"], "out of date: the project has moved on since this proposal"))
        elif p["flags"] and not include_flagged:
            skipped.append((p["project_id"], "flagged for suspicious text; review it, then use --include-flagged"))
        elif not p["head_commit"]:
            skipped.append((p["project_id"], "no head commit"))
        else:
            u = p["update"]
            if u and not any(x["commit"] == u["commit"] for x in project["updates"]):
                project["updates"].insert(0, u)           # newest first
                added.append(p["project_id"])
            else:
                advanced.append(p["project_id"])
            project["last_analyzed_commit"] = p["head_commit"]
            if p["head_date"]:
                project["last_updated"] = max(project["last_updated"], p["head_date"][:10])

    if not added and not advanced:
        return {"added": [], "advanced": [], "skipped": skipped, "ok": True, "output": ""}
    Path(projects_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    ok, output = validator()
    if not ok:
        Path(projects_path).write_text(original, "utf-8")   # baselines only move when validation passes
        return {"added": [], "advanced": [], "skipped": skipped, "ok": False, "output": output}
    return {"added": added, "advanced": advanced, "skipped": skipped, "ok": True, "output": output}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.track")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--project", default="")
    sub.add_parser("show")
    ap = sub.add_parser("apply")
    ap.add_argument("--include-flagged", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()

    if args.command == "show":
        props = _proposals(args.out)
        print("\n".join(render_proposal(p) for p in props) if props else "No proposals. Run `python -m agent.track run`.")
        return 0
    if args.command == "apply":
        store.backup(PROJECTS_PATH, args.out)
        result = apply_updates(_proposals(args.out), PROJECTS_PATH, include_flagged=args.include_flagged)
        if not result["ok"]:
            print("Validation failed, so projects.json was left unchanged:\n" + result["output"])
            return 1
        print(f"Timeline entries added: {len(result['added'])}   baselines advanced without an entry: {len(result['advanced'])}")
        for pid, why in result["skipped"]:
            print(f"  skipped {pid}: {why}")
        return 0

    try:
        settings = load_settings()
        client = GitHubClient(token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        return cmd_run(args, settings, client)
    except (GitHubError, AnalysisError) as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
