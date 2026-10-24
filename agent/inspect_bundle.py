"""Readable summary of a collected bundle. Shows structure and flags, never file contents."""
from __future__ import annotations


def render_bundle(b: dict) -> str:
    r, t = b["repo"], b["tree"]
    lines = [
        "=" * 72,
        f"{r['full_name']}" + ("  [FORK]" if r["fork"] else ""),
        f"  description : {r['description'] or '(none)'}",
        f"  language    : {r['primary_language']}   languages: {', '.join(b_lang for b_lang in list(r['languages'])[:6]) or '-'}",
        f"  head commit : {b['head_commit']['sha'][:7]} ({(b['head_commit']['date'] or '')[:10]})",
        f"  review flags: {', '.join(b['review_reasons']) or 'none'}",
    ]
    ev = b.get("evidence") or {}
    rd = ev.get("readme")
    if rd:
        lines.append(f"  README check: clear={rd['clear']} prose={rd['prose_chars']} chars, boilerplate={rd['boilerplate']}, "
                     f"unfinished hints={rd['unfinished'] or 'none'}")
    lines.append(f"  evidence mode: {ev.get('mode', '?')}"
                 + ("  (README trusted; code read lightly)" if ev.get("mode") == "readme_first" else "  (code read as well)"))
    if b.get("fork"):
        f = b["fork"]
        lines.append(f"  fork of     : {f['parent']}  status={f['status']}  commits ahead={f['ahead_by']}")
    lines += [
        "",
        f"  tree: {t['total_entries']} files, {t['kept_count']} usable. Skipped: {t['skipped'] or 'nothing'}",
        f"  tests={t['has_tests']} ci={t['has_ci']} docker={t['has_docker']} docs_dir={t['has_docs_dir']}",
        f"  top-level dirs: {', '.join(t['top_level_dirs']) or '(none)'}",
        "",
        "  files read (these are what the AI would see):",
    ]
    lines += [f"    {f['path']}  ({f['bytes']} bytes{', truncated' if f['truncated'] else ''}"
              f"{', REDACTED ' + str(f['redactions']) if f['redactions'] else ''})" for f in b["files"]] or ["    (none)"]
    if b["declared_dependencies"]:
        lines += ["", "  declared dependencies:"]
        lines += [f"    {p}: {', '.join(d[:12])}{' ...' if len(d) > 12 else ''}" for p, d in b["declared_dependencies"].items()]
    if b["warnings"]:
        lines += ["", "  warnings:"]
        lines += [f"    [{w['code']}] {w['detail']}" for w in b["warnings"]]
    lines += ["", "  first listed paths:"] + [f"    {p}" for p in t["listed_paths"][:25]]
    return "\n".join(lines) + "\n"
