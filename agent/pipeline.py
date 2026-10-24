"""One command that runs the whole update, for GitHub Actions or for you.

  python -m agent.pipeline run [--dry-run]

Stages (each failure is recorded and the next stage still runs; nothing advances state unless it was validated):
  collect new repos -> analyze -> add projects -> track commits -> add timeline entries -> sync renames/removals
--dry-run runs the read-and-propose stages only, prints what would change, and writes nothing to projects.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .settings import OUT_DIR, PROJECTS_PATH


def _stages() -> list[dict]:
    from . import analyze, collect, sync, track      # imported late so tests can replace the stage list
    no_bundles = lambda out: None if list((out / "bundles").glob("bundle-*.json")) else "no new repositories to analyze"
    return [
        {"name": "collect new repositories", "main": collect.main, "args": ["run"], "writes": False},
        {"name": "analyze new repositories", "main": analyze.main, "args": ["run"], "writes": False, "skip_if": no_bundles},
        {"name": "add new projects", "main": analyze.main, "args": ["apply"], "writes": True},
        {"name": "check commits on existing projects", "main": track.main, "args": ["run"], "writes": False},
        {"name": "add timeline entries", "main": track.main, "args": ["apply"], "writes": True},
        {"name": "check renamed and removed repositories", "main": sync.main, "args": ["run"], "writes": False},
        {"name": "apply renames and hide removed repositories", "main": sync.main, "args": ["apply"], "writes": True},
    ]


def _preview_stages() -> list[dict]:
    from . import analyze, sync, track
    return [{"name": "preview: new projects", "main": analyze.main, "args": ["show"]},
            {"name": "preview: timeline entries", "main": track.main, "args": ["show"]},
            {"name": "preview: renames and removals", "main": sync.main, "args": ["show"]}]


def run_pipeline(out: Path, dry_run: bool = False, stages: list[dict] | None = None, preview: list[dict] | None = None) -> dict:
    out = Path(out)
    before = json.loads(Path(PROJECTS_PATH).read_text("utf-8"))
    errors: list[str] = []
    for stage in stages if stages is not None else _stages():
        if dry_run and stage["writes"]:
            continue
        reason = stage.get("skip_if", lambda o: None)(out)
        if reason:
            print(f"-- {stage['name']}: skipped ({reason})")
            continue
        print(f"\n== {stage['name']}")
        try:
            code = stage["main"](["--out", str(out), *stage["args"]])
        except SystemExit as exc:
            code = exc.code or 1
        except Exception as exc:                       # one broken stage must not stop the others
            code = 1
            print(f"Stage crashed: {type(exc).__name__}")
        if code:
            errors.append(stage["name"])
    if dry_run:
        for stage in preview if preview is not None else _preview_stages():
            print(f"\n== {stage['name']}")
            try:
                stage["main"](["--out", str(out), *stage["args"]])
            except (SystemExit, Exception):
                pass
    after = json.loads(Path(PROJECTS_PATH).read_text("utf-8"))
    body, counts = summarize(before, after, out, errors)
    (out / "pr-body.md").parent.mkdir(parents=True, exist_ok=True)
    (out / "pr-body.md").write_text(body, "utf-8")
    return {"errors": errors, "counts": counts, "body": body}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def summarize(before: dict, after: dict, out: Path, errors: list[str]) -> tuple[str, dict]:
    old = {p["id"]: p for p in before["projects"]}
    new_projects = [p for p in after["projects"] if p["id"] not in old]
    timeline, hidden, renamed = [], [], []
    for p in after["projects"]:
        o = old.get(p["id"])
        if not o:
            continue
        seen = {u["commit"] for u in o["updates"]}
        timeline += [(p, u) for u in p["updates"] if u["commit"] not in seen]
        if o["status"] == "active" and p["status"] == "archived":
            hidden.append(p)
        if o["repository_url"].lower() != p["repository_url"].lower():
            renamed.append((o, p))

    draft_notes = {}
    for f in (out / "drafts").glob("draft-*.json"):
        d = _read_json(f, {})
        if d:
            draft_notes[d["project"]["id"]] = d["notes"]["review_reasons"]
    flagged = [pr for f in (out / "updates").glob("update-*.json") if (pr := _read_json(f, {})).get("flags")
               and next((p for p in after["projects"] if p["id"] == pr["project_id"]), {}).get("last_analyzed_commit") == pr.get("base_commit")]
    stale = _read_json(out / "stale.json", {})
    counts = {"new_projects": len(new_projects), "timeline_entries": len(timeline), "hidden": len(hidden), "renamed": len(renamed)}

    lines = ["## Portfolio update", "",
             f"Prepared by the portfolio agent on {date.today().isoformat()}. Review the changes to `src/data/projects.json`, "
             "then merge to publish. Closing this pull request discards everything below.", ""]
    if new_projects:
        lines += [f"### New projects ({len(new_projects)})", ""]
        for p in new_projects:
            why = draft_notes.get(p["id"], [])
            lines.append(f"- **{p['name']}** (`{p['primary_category']}`, confidence {p['confidence']}): {p['description']}"
                         + (f" _Review: {', '.join(why)}._" if why else ""))
        lines.append("")
    if timeline:
        lines += [f"### Timeline entries ({len(timeline)})", ""]
        lines += [f"- **{p['name']}** ({u['type']}, {u['date']}): {u['summary']}" for p, u in timeline]
        lines.append("")
    if hidden:
        lines += [f"### Hidden because the repository is gone or private ({len(hidden)})", "",
                  *[f"- **{p['name']}** is kept in the data and can be restored with `python -m agent.manage unhide {p['id']}`." for p in hidden], ""]
    if renamed:
        lines += [f"### Repository links updated ({len(renamed)})", "", *[f"- {o['repository_url']} -> {p['repository_url']}" for o, p in renamed], ""]
    notes = []
    notes += [f"`{pr['project_id']}`: a change contained suspicious text and was not applied. Review it locally with `python -m agent.track show`." for pr in flagged]
    notes += [f"`{pid}`: the description may be out of date ({why}). Run `python -m agent.refresh run --project {pid}` locally." for pid, why in stale.items()]
    notes += [f"A step did not finish: {e}. It will be retried on the next run." for e in errors]
    if notes:
        lines += ["### Needs your attention", "", *[f"- {n}" for n in notes], ""]
    if not any(counts.values()) and not notes:
        lines += ["No changes.", ""]
    return "\n".join(lines), counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.pipeline")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = run_pipeline(args.out, args.dry_run)
    print("\n" + result["body"])
    # A run where something failed and nothing was achieved should show as failed, so GitHub emails you.
    return 1 if result["errors"] and not any(result["counts"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
