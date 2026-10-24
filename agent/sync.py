"""Keeps projects.json in step with GitHub: renamed repositories, and ones that were deleted or made private.

  python -m agent.sync run     look for differences and write proposals
  python -m agent.sync show
  python -m agent.sync apply   rename links; hide (never delete) projects whose repository is gone

Hiding keeps the entry and its timeline, and is reversible with `python -m agent.manage unhide ID`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import store
from .apply import node_validator
from .discovery import classify, list_user_repos
from .github_client import GitHubClient, GitHubError, NotFound
from .log import setup_logging
from .settings import OUT_DIR, PROJECTS_PATH, Settings, load_settings


def find_changes(client, settings: Settings, projects: list[dict]) -> tuple[list[dict], list[str]]:
    report = classify(list_user_repos(client, settings.github_username), projects, settings)
    proposals, notes = [], []
    for r in report["renamed"]:
        proposals.append({"type": "rename", "project_id": r["project_id"], "old_url": r["old_url"], "new_url": r["new_url"]})
    for m in report["missing"]:
        try:
            info = client.get_json(f"/repositories/{m['repository_id']}")   # by numeric id, so renames cannot fool it
        except NotFound:
            reason = "the repository was deleted, or made private"
        except GitHubError as exc:
            notes.append(f"{m['project_id']}: could not confirm (GitHub API {exc.status}); left alone")
            continue
        else:
            if info.get("private"):
                reason = "the repository is now private"
            else:
                notes.append(f"{m['project_id']}: no longer in your public list but still public as {info.get('full_name')} "
                             "(transferred?). Left alone.")
                continue
        proposals.append({"type": "hide", "project_id": m["project_id"], "reason": reason})
    return proposals, notes


def apply_sync(proposals: list[dict], projects_path: Path, validator=node_validator) -> dict:
    data = store.load(projects_path)
    by_id = {p["id"]: p for p in data["projects"]}
    done, skipped = [], []
    for p in proposals:
        project = by_id.get(p["project_id"])
        if project is None:
            skipped.append((p["project_id"], "project is no longer in projects.json"))
        elif p["type"] == "rename":
            if project["repository_url"].lower() != p["old_url"].lower():
                skipped.append((p["project_id"], "link already changed since this proposal"))
            else:
                project["repository_url"] = p["new_url"]
                done.append(f"{p['project_id']}: link updated")
        elif p["type"] == "hide":
            if project["status"] != "active":
                skipped.append((p["project_id"], "already hidden"))
            else:
                project["status"] = "archived"
                done.append(f"{p['project_id']}: hidden ({p['reason']})")
    if not done:
        return {"done": [], "skipped": skipped, "ok": True, "output": ""}
    ok, output = store.write_validated(projects_path, data, validator)
    return {"done": done if ok else [], "skipped": skipped, "ok": ok, "output": output}


def render(p: dict) -> str:
    if p["type"] == "rename":
        return f"  rename  {p['project_id']}: {p['old_url']} -> {p['new_url']}"
    return f"  hide    {p['project_id']}: {p['reason']} (kept in projects.json, reversible)"


def _load(out: Path) -> list[dict]:
    return [json.loads(f.read_text("utf-8")) for f in sorted((out / "sync").glob("sync-*.json"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.sync")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "show", "apply"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    setup_logging()

    if args.command == "show":
        props = _load(args.out)
        print("\n".join(render(p) for p in props) if props else "No sync proposals.")
        return 0
    if args.command == "apply":
        store.backup(PROJECTS_PATH, args.out)
        result = apply_sync(_load(args.out), PROJECTS_PATH)
        if not result["ok"]:
            print("Validation failed, so projects.json was left unchanged:\n" + result["output"])
            return 1
        print("\n".join(result["done"]) or "Nothing to apply.")
        for pid, why in result["skipped"]:
            print(f"  skipped {pid}: {why}")
        if result["done"]:
            for f in (args.out / "sync").glob("sync-*.json"):
                f.unlink()
        return 0
    try:
        settings = load_settings()
        client = GitHubClient(token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        proposals, notes = find_changes(client, settings, store.load(PROJECTS_PATH)["projects"])
    except GitHubError as exc:
        print(f"Error: {exc}")
        return 1
    folder = args.out / "sync"
    folder.mkdir(parents=True, exist_ok=True)
    for f in folder.glob("sync-*.json"):
        f.unlink()
    for p in proposals:
        (folder / f"sync-{p['project_id']}-{p['type']}.json").write_text(json.dumps(p, indent=2) + "\n", "utf-8")
    print("\n".join(render(p) for p in proposals) if proposals else "Everything matches GitHub. Nothing to do.")
    for n in notes:
        print(f"  note: {n}")
    if proposals:
        print("\nNext: `python -m agent.sync apply`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
