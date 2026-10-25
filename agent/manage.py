"""Everyday project management without hand-editing JSON.

  python -m agent.manage list
  python -m agent.manage hide ID           hide from the site, keep everything (reversible)
  python -m agent.manage unhide ID
  python -m agent.manage remove ID         delete the entry and never add that repository again
  python -m agent.manage set ID FIELD VALUE   change a field; it is locked so refresh will not overwrite it
  python -m agent.manage pin ID FIELD...   protect fields from refresh      (unpin to undo)
  python -m agent.manage log ID "What changed"   add a timeline entry yourself (--type, --date, --commit)
  python -m agent.manage undo              restore the previous projects.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

from . import store
from .analysis import clean_text
from .apply import node_validator
from .settings import DEFAULT_SETTINGS_PATH, OUT_DIR, PROJECTS_PATH

LOCKABLE = ["name", "description", "overview", "features", "planned", "development_status", "primary_category", "tags", "tech_stack"]
ALIASES = {"category": "primary_category", "tech": "tech_stack", "status": "development_status", "stack": "tech_stack"}
SETTABLE = ["name", "description", "overview", "primary_category", "tags", "tech_stack", "demo_url", "development_status"]


class ManageError(Exception):
    pass


def find(data: dict, pid: str) -> dict:
    for p in data["projects"]:
        if p["id"] == pid:
            return p
    close = difflib.get_close_matches(pid, [p["id"] for p in data["projects"]], n=3)
    raise ManageError(f"No project with id '{pid}'." + (f" Did you mean: {', '.join(close)}?" if close else " Run `list` to see ids."))


def _lock(project: dict, fields: list[str]) -> None:
    project["locked"] = sorted(set(project.get("locked", [])) | set(fields), key=LOCKABLE.index)


def _field(name: str) -> str:
    name = ALIASES.get(name, name)
    return name


def set_field(project: dict, field: str, value: str, category_ids: list[str]) -> str:
    field = _field(field)
    if field not in SETTABLE:
        raise ManageError(f"Cannot set '{field}'. Settable fields: {', '.join(SETTABLE)} (aliases: category, tech, status).")
    none = value.strip().lower() in ("none", "null", "")
    if field == "name":
        v = clean_text(value, 80)
        if not v:
            raise ManageError("name cannot be empty")
        project["name"] = v
    elif field == "description":
        v = clean_text(value, 300)
        if len(v) < 10:
            raise ManageError("description must be at least 10 characters")
        project["description"] = v
    elif field == "overview":
        project["overview"] = None if none else clean_text(value, 2000)
    elif field == "primary_category":
        if value not in category_ids:
            raise ManageError(f"category must be one of: {', '.join(category_ids)}")
        project["primary_category"] = value
    elif field in ("tags", "tech_stack"):
        limit = 8 if field == "tags" else 16
        items: list[str] = []
        for t in (clean_text(x, 40) for x in value.split(",")):
            if t and t.lower() not in {i.lower() for i in items}:
                items.append(t)
        if len(items) > limit:
            raise ManageError(f"at most {limit} items for {field}")
        project[field] = items
    elif field == "demo_url":
        if not none and not (value.startswith("https://") and len(value) <= 300):
            raise ManageError("demo_url must start with https:// (or use 'none')")
        project["demo_url"] = None if none else value
    elif field == "development_status":
        if none:
            project.pop("development_status", None)
        elif value in ("complete", "in_progress"):
            project["development_status"] = value
        else:
            raise ManageError("status must be complete, in_progress or none")
    if field in LOCKABLE:
        _lock(project, [field])
    return field


def pin(project: dict, fields: list[str], lock: bool) -> list[str]:
    names = LOCKABLE if fields == ["all"] else [_field(f) for f in fields]
    bad = [f for f in names if f not in LOCKABLE]
    if bad:
        raise ManageError(f"Cannot pin {', '.join(bad)}. Pinnable: {', '.join(LOCKABLE)} (or 'all').")
    if lock:
        _lock(project, names)
    else:
        project["locked"] = [f for f in project.get("locked", []) if f not in names]
        if not project["locked"]:
            project.pop("locked")
    return names


def fetch_head(client, project: dict) -> tuple[str, str]:
    """The repository's current default-branch commit and its date."""
    full = project["repository_url"].removeprefix("https://github.com/")
    branch = client.get_json(f"/repos/{full}")["default_branch"]
    head = client.get_json(f"/repos/{full}/commits/{branch}")
    return head["sha"], ((head.get("commit", {}).get("committer") or {}).get("date") or "")[:10]


def add_log_entry(project: dict, summary: str, type_: str, commit: str, date_: str, advance: bool) -> None:
    from datetime import date as _date
    from .changes import TYPES
    import re
    if type_ not in TYPES:
        raise ManageError(f"type must be one of: {', '.join(TYPES)}")
    text = clean_text(summary, 400)
    if len(text) < 10:
        raise ManageError("the summary needs to be at least a short sentence")
    commit = commit.lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise ManageError("commit must be a hex SHA (7 to 40 characters)")
    try:
        _date.fromisoformat(date_)
    except ValueError:
        raise ManageError("date must look like 2026-10-25")
    if date_ < project["created_at"]:
        raise ManageError(f"date cannot be before the project was added ({project['created_at']})")
    if any(u["commit"].startswith(commit) or commit.startswith(u["commit"]) for u in project["updates"]):
        raise ManageError("the timeline already has an entry for that commit")
    project["updates"].insert(0, {"commit": commit, "date": date_, "type": type_, "summary": text})
    project["last_updated"] = max(project["last_updated"], date_)
    if advance:
        project["last_analyzed_commit"] = commit      # so the tracker does not propose the same commits again


def add_exclusion(settings_path: Path, full_name: str) -> bool:
    raw = json.loads(Path(settings_path).read_text("utf-8"))
    current = raw.setdefault("exclude_repos", [])
    if full_name.lower() in {x.lower() for x in current}:
        return False
    current.append(full_name)
    Path(settings_path).write_text(json.dumps(raw, indent=2) + "\n", "utf-8")
    return True


def clean_artifacts(out_dir: Path, project: dict) -> list[str]:
    """Delete leftover bundles, drafts and proposals so nothing can bring the project back."""
    removed = []
    patterns = [("bundles", f"bundle-{project['repository_id']}.json"), ("drafts", f"draft-{project['repository_id']}.json"),
                ("updates", f"update-{project['id']}-*.json"), ("refresh", f"refresh-{project['id']}.json"),
                ("sync", f"sync-{project['id']}-*.json")]
    for folder, pattern in patterns:
        for path in (Path(out_dir) / folder).glob(pattern):
            path.unlink()
            removed.append(f"{folder}/{path.name}")
    return removed


def render_list(data: dict) -> str:
    rows = [f"{'id':<34} {'category':<22} {'state':<14} {'updated':<11} notes"]
    for p in data["projects"]:
        notes = []
        if p.get("locked"):
            notes.append("locked: " + ",".join(p["locked"]))
        if p.get("needs_review"):
            notes.append("needs review")
        state = "hidden" if p["status"] == "archived" else p.get("development_status", "shown")
        rows.append(f"{p['id']:<34} {p['primary_category']:<22} {state:<14} {p['last_updated']:<11} {'; '.join(notes)}")
    return "\n".join(rows)


def main(argv: list[str] | None = None, validator=node_validator, ask=input, client=None) -> int:
    parser = argparse.ArgumentParser(prog="agent.manage")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("undo")
    for name in ("hide", "unhide"):
        sub.add_parser(name).add_argument("id")
    rm = sub.add_parser("remove")
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true")
    st = sub.add_parser("set")
    st.add_argument("id"); st.add_argument("field"); st.add_argument("value")
    lg = sub.add_parser("log")
    lg.add_argument("id"); lg.add_argument("summary")
    lg.add_argument("--type", default="feature"); lg.add_argument("--date", default="")
    lg.add_argument("--commit", default="", help="default: the repository's latest commit")
    for name in ("pin", "unpin"):
        p = sub.add_parser(name)
        p.add_argument("id"); p.add_argument("fields", nargs="+")
    args = parser.parse_args(argv)

    try:
        if args.command == "undo":
            restored = store.undo(PROJECTS_PATH, args.out)
            print("Restored the previous projects.json." if restored else "Nothing to undo: no backups yet.")
            return 0 if restored else 1
        data = store.load(PROJECTS_PATH)
        if args.command == "list":
            print(render_list(data))
            return 0

        from .analyze import load_categories
        project = find(data, args.id)
        if args.command == "hide":
            project["status"] = "archived"
            message = f"Hid '{project['id']}'. It is kept in projects.json and can be restored with `unhide`."
        elif args.command == "unhide":
            project["status"] = "active"
            message = f"'{project['id']}' is visible again."
        elif args.command == "set":
            field = set_field(project, args.field, args.value, [c["id"] for c in load_categories()])
            message = f"Set {field} on '{project['id']}'." + (" It is now locked, so refresh will not overwrite it." if field in LOCKABLE else "")
        elif args.command == "log":
            commit, date_ = args.commit, args.date
            if not commit:
                import os
                from .github_client import GitHubClient, GitHubError
                try:
                    commit, head_date = fetch_head(client or GitHubClient(token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")), project)
                except GitHubError as exc:
                    raise ManageError(f"Could not read the repository's latest commit (GitHub API {exc.status}). "
                                      "Set GH_TOKEN, or pass --commit SHA.") from exc
                date_ = date_ or head_date
            add_log_entry(project, args.summary, args.type, commit, date_ or project["last_updated"], advance=not args.commit)
            message = f"Added a {args.type} entry to '{project['id']}'." + ("" if args.commit else " Tracking now continues from that commit.")
        elif args.command in ("pin", "unpin"):
            names = pin(project, args.fields, args.command == "pin")
            message = f"{'Locked' if args.command == 'pin' else 'Unlocked'}: {', '.join(names)}."
        else:  # remove
            full_name = project["repository_url"].removeprefix("https://github.com/")
            if not args.yes and ask(f"Remove '{project['id']}' and never add {full_name} again? Type yes to confirm: ").strip().lower() != "yes":
                print("Cancelled.")
                return 1
            store.backup(PROJECTS_PATH, args.out)
            data["projects"] = [p for p in data["projects"] if p["id"] != project["id"]]
            ok, output = store.write_validated(PROJECTS_PATH, data, validator)
            if not ok:
                print("Validation failed, so nothing was changed:\n" + output)
                return 1
            add_exclusion(DEFAULT_SETTINGS_PATH, full_name)
            cleaned = clean_artifacts(args.out, project)
            print(f"Removed '{project['id']}'. {full_name} was added to exclude_repos in agent/settings.json "
                  f"(commit that file too). Cleaned {len(cleaned)} leftover file(s). Undo with `undo` "
                  f"(then remove the line from exclude_repos).")
            return 0

        store.backup(PROJECTS_PATH, args.out)
        ok, output = store.write_validated(PROJECTS_PATH, data, validator)
        if not ok:
            print("Validation failed, so nothing was changed:\n" + output)
            return 1
        print(message)
        return 0
    except ManageError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
