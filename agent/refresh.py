"""Re-analyze existing projects and update only their generated fields, in place.

  python -m agent.refresh run --project ID | --stale | --all [--limit N]
  python -m agent.refresh show
  python -m agent.refresh apply [--only description,tags] [--include-flagged]

Never touched: the timeline, the tracking baseline, the id, the repository link, dates, and any field you locked.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import store
from .analyze import analyze_bundle, load_categories
from .apply import node_validator
from .discovery import list_user_repos
from .fetcher import SkipRepo, collect_repo
from .gemini import AnalysisError, GeminiClient
from .github_client import GitHubClient, GitHubError
from .log import setup_logging
from .settings import OUT_DIR, PROJECTS_PATH, Settings, load_settings

log = logging.getLogger("agent.refresh")
REFRESHABLE = ["name", "description", "overview", "features", "planned", "development_status", "primary_category", "tags", "tech_stack", "evidence"]


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _is_locked(field: str, locked: set[str]) -> bool:
    return field in locked or (field == "evidence" and "features" in locked)


def compute_changes(old: dict, new: dict, locked: set[str]) -> list[dict]:
    changes = []
    for f in REFRESHABLE:
        o, n = old.get(f), new.get(f)
        if n is None and o not in (None, [], ""):
            continue                      # "unclear" or an empty answer never erases something known
        if _same(o, n):
            continue
        changes.append({"field": f, "old": o, "new": n, "locked": _is_locked(f, locked)})
    return changes


def make_proposal(project: dict, draft: dict, bundle: dict) -> dict | None:
    changes = compute_changes(project, draft["project"], set(project.get("locked", [])))
    if not any(not c["locked"] for c in changes):
        return None
    notes = draft["notes"]
    return {
        "project_id": project["id"], "full_name": bundle["repo"]["full_name"], "head_commit": bundle["head_commit"]["sha"],
        "changes": changes, "new_confidence": draft["project"]["confidence"], "review_reasons": notes["review_reasons"],
        "flags": [r for r in notes["review_reasons"] if r == "injection_suspected"],
        "category_reasoning": notes["category_reasoning"], "model": notes["model"],
    }


def apply_refresh(proposals: list[dict], projects_path: Path, validator=node_validator,
                  only: set[str] | None = None, include_flagged: bool = False) -> dict:
    original = Path(projects_path).read_text("utf-8")
    data = json.loads(original)
    by_id = {p["id"]: p for p in data["projects"]}
    if only and "features" in only:
        only = only | {"evidence"}
    applied: dict[str, list[str]] = {}
    skipped: list[tuple[str, str, str]] = []

    for p in proposals:
        project = by_id.get(p["project_id"])
        if project is None:
            skipped.append((p["project_id"], "-", "project is no longer in projects.json"))
            continue
        if p["flags"] and not include_flagged:
            skipped.append((p["project_id"], "-", "flagged for suspicious text; review it, then use --include-flagged"))
            continue
        locked, done = set(project.get("locked", [])), []
        for c in p["changes"]:
            f = c["field"]
            if only is not None and f not in only:
                continue
            if _is_locked(f, locked):
                skipped.append((p["project_id"], f, "locked"))
            elif not _same(project.get(f), c["old"]):
                skipped.append((p["project_id"], f, "you edited it after this proposal was made"))
            else:
                if c["new"] is None and f in ("development_status",):
                    project.pop(f, None)
                else:
                    project[f] = c["new"]
                done.append(f)
        if done:
            applied[p["project_id"]] = done
            if only is None:                      # a full approved refresh clears the review badge
                project["confidence"], project["needs_review"] = p["new_confidence"], False

    if not applied:
        return {"applied": {}, "skipped": skipped, "ok": True, "output": ""}
    ok, output = store.write_validated(projects_path, data, validator)
    return {"applied": applied if ok else {}, "skipped": skipped, "ok": ok, "output": output}


def _item(x) -> str:
    return f"{x['claim']}  <{x['source']}>" if isinstance(x, dict) else str(x)


def render_proposal(p: dict) -> str:
    lines = ["=" * 72, f"{p['project_id']}   (re-analyzed at {p['head_commit'][:7]}, model {p['model']})"]
    for c in p["changes"]:
        tag = "   [LOCKED: will not be applied]" if c["locked"] else ""
        lines.append(f"  {c['field']}{tag}")
        if isinstance(c["old"], list) or isinstance(c["new"], list):
            old, new = [_item(x) for x in c["old"] or []], [_item(x) for x in c["new"] or []]
            lines += [f"    - {x}" for x in old if x not in new] + [f"    + {x}" for x in new if x not in old]
        else:
            lines += [f"    was: {c['old']}", f"    now: {c['new']}"]
    if p["flags"]:
        lines.append("  FLAGGED: suspicious text in the repository. Skipped by `apply` unless --include-flagged.")
    return "\n".join(lines) + "\n"


def _proposals(out: Path) -> list[dict]:
    return [json.loads(f.read_text("utf-8")) for f in sorted((out / "refresh").glob("refresh-*.json"))]


def _stale(out: Path) -> dict:
    try:
        return json.loads((out / "stale.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def cmd_run(args, settings: Settings, client) -> int:
    data = store.load(PROJECTS_PATH)
    if args.project:
        chosen = [p for p in data["projects"] if p["id"] == args.project]
        if not chosen:
            print(f"No project with id '{args.project}'. Run `python -m agent.manage list`.")
            return 1
    elif args.stale:
        stale = _stale(args.out)
        chosen = [p for p in data["projects"] if p["id"] in stale]
        if not chosen:
            print("No projects are marked as out of date. (`python -m agent.track run` marks them.)")
            return 0
    elif args.all:
        chosen = [p for p in data["projects"] if p["status"] != "archived"]
    else:
        print("Choose what to refresh: --project ID, --stale, or --all.")
        return 1
    if args.limit:
        chosen = chosen[: args.limit]

    repos = {r["id"]: r for r in list_user_repos(client, settings.github_username)}
    categories, taken, gemini, rows = load_categories(), {p["id"] for p in data["projects"]}, None, []
    (args.out / "refresh").mkdir(parents=True, exist_ok=True)

    for project in chosen:
        name, repo = project["id"], repos.get(project["repository_id"])
        target = args.out / "refresh" / f"refresh-{name}.json"
        if target.exists():
            target.unlink()
        if repo is None or repo.get("archived") or settings.is_excluded(repo["full_name"]):
            rows.append((name, "skipped (repository not visible, archived or excluded)"))
            continue
        try:
            bundle = collect_repo(client, repo["full_name"], settings)
            gemini = gemini or GeminiClient(settings.gemini_model, min_interval=settings.min_seconds_between_calls)
            draft = analyze_bundle(gemini, bundle, categories, taken, settings)
        except SkipRepo as skip:
            rows.append((name, f"skipped ({skip.reason})"))
            continue
        except GitHubError as exc:
            rows.append((name, f"error: GitHub API {exc.status}"))
            continue
        except AnalysisError as exc:
            rows.append((name, f"analysis failed: {exc}"))
            if any(k in str(exc) for k in ("rate limit", "not found for this key", "GEMINI_API_KEY")):
                break
            continue
        proposal = make_proposal(project, draft, bundle)
        if proposal is None:
            rows.append((name, "no changes (or only locked fields differ)"))
            continue
        target.write_text(json.dumps(proposal, indent=2, ensure_ascii=False) + "\n", "utf-8")
        n = sum(1 for c in proposal["changes"] if not c["locked"])
        rows.append((name, f"{n} field(s) would change: {', '.join(c['field'] for c in proposal['changes'] if not c['locked'])}"))

    print(f"\n{'project':<36} result")
    for name, outcome in rows:
        print(f"{name:<36} {outcome}")
    print("\nNext: `python -m agent.refresh show`, then `python -m agent.refresh apply`.")
    return 0


def main(argv: list[str] | None = None, validator=node_validator) -> int:
    parser = argparse.ArgumentParser(prog="agent.refresh")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--project", default="")
    run.add_argument("--stale", action="store_true")
    run.add_argument("--all", action="store_true")
    run.add_argument("--limit", type=int, default=0)
    sub.add_parser("show")
    ap = sub.add_parser("apply")
    ap.add_argument("--only", default="", help="comma-separated fields, e.g. description,tags")
    ap.add_argument("--include-flagged", action="store_true")
    args = parser.parse_args(argv)
    setup_logging()

    if args.command == "show":
        props = _proposals(args.out)
        print("\n".join(render_proposal(p) for p in props) if props else "No refresh proposals. Run `python -m agent.refresh run`.")
        return 0
    if args.command == "apply":
        only = {ALIAS.get(x.strip(), x.strip()) for x in args.only.split(",") if x.strip()} or None
        store.backup(PROJECTS_PATH, args.out)
        result = apply_refresh(_proposals(args.out), PROJECTS_PATH, validator, only=only, include_flagged=args.include_flagged)
        if not result["ok"]:
            print("Validation failed, so projects.json was left unchanged:\n" + result["output"])
            return 1
        for pid, fields in result["applied"].items():
            print(f"Updated {pid}: {', '.join(fields)}")
        for pid, field, why in result["skipped"]:
            print(f"  skipped {pid} {field if field != '-' else ''}: {why}")
        if not result["applied"]:
            print("Nothing was applied.")
        stale = _stale(args.out)
        if result["applied"] and stale:
            for pid in result["applied"]:
                stale.pop(pid, None)
            (args.out / "stale.json").write_text(json.dumps(stale, indent=2) + "\n", "utf-8")
        return 0

    try:
        settings = load_settings()
        client = GitHubClient(token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        return cmd_run(args, settings, client)
    except (GitHubError, AnalysisError) as exc:
        print(f"Error: {exc}")
        return 1


ALIAS = {"category": "primary_category", "tech": "tech_stack", "status": "development_status"}

if __name__ == "__main__":
    sys.exit(main())
