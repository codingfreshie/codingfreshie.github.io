from __future__ import annotations


def render_draft(d: dict) -> str:
    p, n = d["project"], d["notes"]
    lines = [
        "=" * 72,
        f"{p['name']}   ({p['repository_url']})",
        f"  category   : {p['primary_category']}  (confidence {p['confidence']})  because: {n['category_reasoning']}",
        f"  runner-up  : {n.get('alternative_category', 'none')}",
        f"  status     : {p.get('development_status', 'unclear')}   evidence mode: {n['evidence_mode']}   model: {n['model']}",
        f"  needs review: {p['needs_review']}" + (f"  [{', '.join(n['review_reasons'])}]" if n["review_reasons"] else ""),
        "",
        f"  description: {p['description']}",
        f"  overview   : {p['overview'] or '(none)'}",
        "",
        "  features (each backed by a file):",
    ]
    lines += [f"    - {e['claim']}   <{e['source']}>" for e in p["evidence"]] or ["    (none verified)"]
    if p.get("planned"):
        lines += ["", "  planned / not shown in code:"] + [f"    - {x}" for x in p["planned"]]
    lines += ["", f"  tech stack : {', '.join(p['tech_stack']) or '(none)'}", f"  tags       : {', '.join(p['tags']) or '(none)'}"]
    dropped = n["dropped"]
    if dropped["features"] or dropped["tech"]:
        lines += ["", "  removed because the repository did not support them:"]
        lines += [f"    feature: {x['text']}  (cited {x['cited']!r})" for x in dropped["features"]]
        lines += [f"    technology: {t}" for t in dropped["tech"]]
    return "\n".join(lines) + "\n"
