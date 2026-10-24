"""Judges whether a README is clear enough to describe a project on its own."""
from __future__ import annotations

import re

_BOILERPLATE = [re.compile(p, re.I | re.M) for p in (
    r"bootstrapped with \[?`?create[ -]react[ -]app",
    r"getting started with create react app",
    r"this template provides a minimal setup to get react working in vite",
    r"expand the eslint configuration",
    r"bootstrapped with \[?`?create-next-app",
    r"welcome to your lovable project",
    r"^#\s*(?:react|vue|svelte) \+ (?:vite|typescript)\s*$",
)]

# Wording that suggests the project is unfinished, so the README may describe more than exists.
_UNFINISHED = [(label, re.compile(p, re.I | re.M)) for label, p in (
    ("work_in_progress", r"\b(?:work[ -]in[ -]progress|wip|under (?:active )?development|still in progress|in development)\b"),
    ("planned_features", r"\b(?:coming soon|planned features?|upcoming features?|not yet implemented|yet to be implemented|future (?:work|plans|improvements))\b"),
    ("todo_section", r"^#+\s*(?:to-?do|roadmap)\b"),
)]


def prose_of(markdown: str) -> str:
    """Readable sentences only: no code blocks, badges, tables, or bare URLs."""
    t = re.sub(r"```.*?```|~~~.*?~~~|<!--.*?-->", " ", markdown, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"(?m)^\s*\|.*$", " ", t)
    t = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "", t)
    t = re.sub(r"(?m)^\s*#+\s*", "", t)
    t = re.sub(r"https?://\S+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def assess_readme(markdown: str) -> dict:
    prose = prose_of(markdown)
    sentences = len(re.findall(r"[.!?](?:\s|$)", prose))
    boilerplate = any(p.search(markdown) for p in _BOILERPLATE)
    unfinished = [label for label, p in _UNFINISHED if p.search(markdown)]
    clear = not boilerplate and len(prose) >= 400 and sentences >= 4
    return {
        "clear": clear,
        "boilerplate": boilerplate,
        "prose_chars": len(prose),
        "sentences": sentences,
        "unfinished": unfinished,
        # Safe to rely on without reading the code: clear, and not hinting at unfinished work.
        "trustworthy": clear and not unfinished,
    }
