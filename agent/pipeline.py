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
    marker = out / "open-pr"                       # the workflow opens a pull request only if this file exists
    if any(counts.values()) and not dry_run:
        marker.write_text("yes\n", "utf-8")
    else:
        marker.unlink(missing_ok=True)
    return {"errors": errors, "counts": counts, "body": body}


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


_WHY = {"history_rewritten": "the repository's history was rewritten, so tracking restarted from its current state"}


def checked_commits(old: dict, after: dict, out: Path) -> list[tuple[str, int, str]]:
    """Projects whose new commits were looked at but produced no timeline entry, with the reason."""
    now = {p["id"]: p for p in after["projects"]}
    result = []
    for f in sorted((out / "updates").glob("update-*.json")):
        pr = _read_json(f, {})
        p = now.get(pr.get("project_id"))
        if not p or pr.get("update") or pr.get("flags"):
            continue
        moved = p["last_analyzed_commit"] == pr.get("head_commit") and old.get(p["id"], {}).get("last_analyzed_commit") == pr.get("base_commit")
        if moved:
            result.append((p["name"], pr.get("commits", 0), _WHY.get(pr.get("reason"), pr.get("reason") or "not a meaningful change")))
    return result


def unadded_repos(after: dict, out: Path, errors: list[str]) -> list[tuple[str, str]]:
    """Every new repository the run found but did not add, each with the reason."""
    discovery = _read_json(out / "discovery.json", {})
    if not discovery:
        return []
    have = {p["repository_id"] for p in after["projects"]}
    deferred = {r["id"] for r in discovery.get("deferred", [])}
    collect_log, analysis_log = _read_json(out / "collect_log.json", {}), _read_json(out / "analysis_log.json", {})
    result = []
    for repo in discovery.get("new", []):
        rid, name = repo["id"], repo["full_name"]
        if rid in have:
            continue
        if rid in deferred:
            why = "waiting its turn: only a few new repositories are analyzed per run (max_new_repos_per_run), so it will be picked up next time"
        elif collect_log.get(name, {}).get("status") in ("skipped", "error"):
            entry = collect_log[name]
            why = f"could not be collected ({entry['status']}: {entry.get('detail') or 'no detail'})"
        elif name in analysis_log:
            why = f"the analysis failed ({analysis_log[name]})"
        elif (out / "drafts" / f"draft-{rid}.json").exists():
            why = "its entry was written but not applied (is it listed in exclude_repos?)"
        elif (out / "bundles" / f"bundle-{rid}.json").exists():
            why = "collected, but the analysis did not finish" + (" (the analysis step failed; see the run log)" if "analyze new repositories" in errors else "")
        else:
            why = "it was found but not collected (see the run log)"
        result.append((name, why))
    return result


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
    not_added = unadded_repos(after, out, errors)
    checked = checked_commits(old, after, out)
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
    if checked:
        lines += [f"### New commits checked but not added to a timeline ({len(checked)})", ""]
        lines += [f"- **{name}**: {n} commit{'s' if n != 1 else ''}, {why}" for name, n, why in checked]
        lines += ["", "If one of these deserves an entry, add it yourself: "
                  "`python -m agent.manage log PROJECT_ID \"What changed\"`.", ""]
    if not_added:
        lines += [f"### Found on GitHub but not added ({len(not_added)})", "",
                  *[f"- **{name}**: {why}" for name, why in not_added], ""]
    notes = []
    notes += [f"`{pr['project_id']}`: a change contained suspicious text and was not applied. Review it locally with `python -m agent.track show`." for pr in flagged]
    notes += [f"`{pid}`: the description may be out of date ({why}). Run `python -m agent.refresh run --project {pid}` locally." for pid, why in stale.items()]
    notes += [f"A step did not finish: {e}. It will be retried on the next run." for e in errors]
    if notes:
        lines += ["### Needs your attention", "", *[f"- {n}" for n in notes], ""]
    if not any(counts.values()):
        if checked:
            lines += ["Only commit-tracking positions moved forward. Nothing visible on the site changes, "
                      "so no pull request is opened for this.", ""]
        elif not notes and not not_added:
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
