"""Turns a validated analysis into a project record that matches schema/project.schema.json."""
from __future__ import annotations

import re

BUNDLE_REVIEW_REASONS = {"injection_suspected", "fork_unmodified", "fork_status_unknown", "thin_evidence"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80].strip("-")
    return slug or "project"


def unique_id(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    n = 2
    while f"{base[:75]}-{n}" in taken:
        n += 1
    return f"{base[:75]}-{n}"


def build_project(bundle: dict, cleaned: dict, dropped: dict, taken_ids: set[str], min_confidence: float, model: str) -> dict:
    r = bundle["repo"]
    created = (r["created_at"] or "")[:10]
    last = ((bundle["head_commit"]["date"] or r["pushed_at"] or r["created_at"] or "")[:10])
    last = max(last, created)

    reasons: list[str] = []
    if cleaned["category_confidence"] < min_confidence:
        reasons.append("low_category_confidence")
    if cleaned["overall_confidence"] < min_confidence:
        reasons.append("low_overall_confidence")
    if cleaned["alternative_category"] != "none":
        reasons.append("ambiguous_category")
    reasons += [x for x in bundle["review_reasons"] if x in BUNDLE_REVIEW_REASONS]
    lost = len(dropped["features"])
    if lost >= 2 and lost * 2 > lost + len(cleaned["features"]):
        reasons.append("many_unsupported_claims")
    if not cleaned["features"]:
        reasons.append("no_verified_features")
    reasons = list(dict.fromkeys(reasons))

    homepage = r.get("homepage") or ""
    project = {
        "id": unique_id(slugify(r["full_name"].split("/", 1)[1]), taken_ids),
        "repository_id": r["id"],
        "name": cleaned["name"],
        "description": cleaned["description"],
        "overview": cleaned["overview"] or None,
        "features": [f["text"] for f in cleaned["features"]],
        "primary_category": cleaned["primary_category"],
        "tags": cleaned["tags"],
        "tech_stack": cleaned["tech_stack"],
        "repository_url": r["html_url"],
        "demo_url": homepage if homepage.startswith("https://") else None,
        "image": None,
        "status": "active",
        "created_at": created,
        "last_updated": last,
        "last_analyzed_commit": bundle["head_commit"]["sha"],
        "confidence": round(min(cleaned["overall_confidence"], cleaned["category_confidence"]), 2),
        "needs_review": bool(reasons),
        "evidence": [{"claim": f["text"], "source": f["source"]} for f in cleaned["features"]],
        "updates": [],
    }
    if cleaned["development_status"] != "unclear":
        project["development_status"] = cleaned["development_status"]
    if cleaned["planned"]:
        project["planned"] = cleaned["planned"]

    notes = {
        "model": model,
        "review_reasons": reasons,
        "category_reasoning": cleaned["category_reasoning"],
        "alternative_category": cleaned["alternative_category"],
        "evidence_mode": (bundle.get("evidence") or {}).get("mode"),
        "dropped": dropped,
    }
    return {"project": project, "notes": notes}
