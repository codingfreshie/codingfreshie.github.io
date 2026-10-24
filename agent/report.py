from __future__ import annotations


def render_summary(discovery: dict, results: list[dict]) -> str:
    d = discovery
    lines = [
        f"## Portfolio agent: {d['username']}",
        "",
        f"Checked {d['repos_seen']} public repositories "
        f"({'authenticated' if d['authenticated'] else 'unauthenticated, lower rate limit'}).",
        "",
        "| Result | Count |",
        "| --- | --- |",
        f"| New repositories | {len(d['new'])} |",
        f"| Collected this run | {sum(1 for r in results if r['status'] == 'collected')} |",
        f"| Deferred to a later run | {len(d['deferred'])} |",
        f"| Already in portfolio | {d['unchanged']} |",
        f"| Renamed | {len(d['renamed'])} |",
        f"| Newly archived | {len(d['newly_archived'])} |",
        f"| In portfolio but no longer visible | {len(d['missing'])} |",
        f"| Skipped | {len(d['skipped'])} |",
        "",
    ]
    if d["renamed"] or d["missing"]:
        lines += ["Some repositories were renamed or are no longer visible. Review them with `python -m agent.sync run`.", ""]
    if results:
        lines += ["### Collection results", "", "| Repository | Result | Files read | Review flags |", "| --- | --- | --- | --- |"]
        for r in results:
            lines.append(f"| {r['full_name']} | {r['status']}{(': ' + r['detail']) if r.get('detail') else ''} | "
                         f"{r.get('files_read', '')} | {', '.join(r.get('review_reasons', [])) or 'none'} |")
        lines.append("")
    if d["missing"]:
        lines += ["### Missing from GitHub", ""]
        lines += [f"- `{m['project_id']}` ({m['repository_url']})" for m in d["missing"]]
        lines.append("")
    if d["skipped"]:
        lines += ["### Skipped", ""]
        lines += [f"- {s['full_name']}: {s['reason']}" for s in d["skipped"]]
        lines.append("")
    return "\n".join(lines)
