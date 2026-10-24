"""Checks what the model said against what the repository actually contains."""
from __future__ import annotations

import re

from pydantic import ValidationError

from .gemini import ValidationFailed
from .schemas import Analysis

_HTML = re.compile(r"<[^>]+>")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")


def clean_text(text: str, limit: int) -> str:
    """Plain text only: no HTML, links or URLs, single spaces, trimmed at a sentence or word boundary."""
    t = _MD_LINK.sub(r"\1", _HTML.sub("", text or ""))
    t = re.sub(r"\s+", " ", _URL.sub("", t)).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit]
    end = max(cut.rfind(". "), cut.rfind("; "))
    if end > limit * 0.5:
        return cut[: end + 1]
    return cut[: cut.rfind(" ")].rstrip(",;:- ") + "\u2026" if " " in cut else cut


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def known_paths(bundle: dict) -> dict[str, str]:
    paths = [f["path"] for f in bundle["files"]] + list(bundle["tree"]["listed_paths"])
    return {p.lower(): p for p in paths}


def normalize_source(source: str, paths: dict[str, str]) -> str | None:
    for candidate in re.split(r"\s*[,;]\s*", (source or "").strip().strip("`'\"")):
        c = candidate.strip().strip("`'\"")
        c = c[2:] if c.startswith("./") else c.lstrip("/")
        if c.lower() in paths:
            return paths[c.lower()]
    return None


def _haystack(bundle: dict) -> tuple[str, set[str]]:
    parts = [f["content"] for f in bundle["files"]]
    parts += [name for deps in bundle["declared_dependencies"].values() for name in deps]
    parts += list(bundle["repo"]["languages"]) + bundle["repo"]["topics"] + bundle["tree"]["listed_paths"]
    parts.append(bundle["repo"]["description"] or "")
    return _norm(" ".join(parts)), {_norm(l) for l in bundle["repo"]["languages"]}


def tech_supported(tech: str, hay: str, languages: set[str]) -> bool:
    """Heuristic: a technology is believable if its name (or a distinctive word of it) appears in the data."""
    n = _norm(tech)
    if not n:
        return False
    if len(n) < 3:
        return n in languages
    variants = {n}
    if n.endswith("js") and len(n) > 4:
        variants.add(n[:-2])
    if n.startswith("google") and len(n) > 8:
        variants.add(n[6:])
    variants |= {w for w in (_norm(x) for x in re.split(r"[\s/]+", tech)) if len(w) >= 4}
    return any(v in hay for v in variants)


def _unique(items: list[str], limit: int) -> list[str]:
    seen: dict[str, str] = {}
    for item in items:
        if item and item.lower() not in seen:
            seen[item.lower()] = item
    return list(seen.values())[:limit]


def validate_analysis(raw: str, bundle: dict, category_ids: list[str]) -> tuple[dict, dict]:
    """Return (cleaned analysis, dropped claims). Raises ValidationFailed for problems worth a retry."""
    try:
        a = Analysis.model_validate_json(raw)
    except ValidationError as exc:
        fields = sorted({".".join(str(x) for x in e["loc"]) for e in exc.errors()})
        raise ValidationFailed(f"the response did not match the required structure (problem fields: {', '.join(fields)[:200]})")

    problems = []
    if a.primary_category not in category_ids:
        problems.append(f"primary_category must be one of {category_ids}")
    if a.alternative_category not in category_ids + ["none"]:
        problems.append(f"alternative_category must be one of {category_ids + ['none']}")
    for field in ("category_confidence", "overall_confidence"):
        if not 0 <= getattr(a, field) <= 1:
            problems.append(f"{field} must be between 0 and 1")
    name = clean_text(a.name, 80)
    description = clean_text(a.description, 300)
    if not name:
        problems.append("name is empty")
    if len(description) < 10:
        problems.append("description is missing or too short")
    if problems:
        raise ValidationFailed("; ".join(problems))

    paths = known_paths(bundle)
    dropped: dict[str, list] = {"features": [], "tech": []}
    features, seen_text = [], set()
    for f in a.features:
        text = clean_text(f.text, 200)
        source = normalize_source(f.source, paths)
        if not text or text.lower() in seen_text:
            continue
        if source is None:
            dropped["features"].append({"text": text, "cited": f.source[:100]})
            continue
        seen_text.add(text.lower())
        features.append({"text": text, "source": source})

    hay, languages = _haystack(bundle)
    tech = []
    for t in a.tech_stack:
        t = clean_text(t, 40)
        if not t:
            continue
        (tech if tech_supported(t, hay, languages) else dropped["tech"]).append(t)

    cleaned = {
        "name": name,
        "description": description,
        "overview": clean_text(a.overview, 1200),
        "features": features[:12],
        "planned": _unique([clean_text(p, 200) for p in a.planned], 8),
        "development_status": a.development_status,
        "primary_category": a.primary_category,
        "category_confidence": a.category_confidence,
        "category_reasoning": clean_text(a.category_reasoning, 300),
        "alternative_category": "none" if a.alternative_category == a.primary_category else a.alternative_category,
        "tags": _unique([clean_text(t, 40) for t in a.tags], 8),
        "tech_stack": _unique(tech, 16),
        "overall_confidence": a.overall_confidence,
    }
    return cleaned, dropped
