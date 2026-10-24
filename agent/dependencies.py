"""Extracts declared dependency names from manifests. Deterministic evidence for the tech stack."""
from __future__ import annotations

import json
import posixpath
import re

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)")
MAX_DEPS = 60


def _req_name(spec: str) -> str | None:
    m = _REQ_NAME.match(spec)
    return m.group(1) if m else None


def parse_manifest(path: str, text: str) -> list[str]:
    name = posixpath.basename(path).lower()
    deps: list[str] = []
    try:
        if name in ("package.json", "composer.json"):
            data = json.loads(text)
            for key in ("dependencies", "devDependencies", "require", "require-dev"):
                deps += list((data.get(key) or {}).keys())
        elif name.startswith("requirements") and name.endswith(".txt"):
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith(("#", "-")):
                    n = _req_name(line)
                    if n:
                        deps.append(n)
        elif name in ("pyproject.toml", "cargo.toml", "pipfile") and tomllib:
            data = tomllib.loads(text)
            proj = data.get("project", {})
            deps += [n for n in (_req_name(s) for s in proj.get("dependencies", [])) if n]
            for group in proj.get("optional-dependencies", {}).values():
                deps += [n for n in (_req_name(s) for s in group) if n]
            deps += [k for k in data.get("tool", {}).get("poetry", {}).get("dependencies", {}) if k.lower() != "python"]
            for key in ("dependencies", "dev-dependencies", "packages", "dev-packages"):
                deps += list((data.get(key) or {}).keys())
        elif name == "go.mod":
            deps += re.findall(r"^\s*(?:require\s+)?([\w.\-]+\.[\w.\-]+/[\w./\-]+)\s+v", text, re.M)
        elif name == "gemfile":
            deps += re.findall(r"^\s*gem\s+['\"]([^'\"]+)['\"]", text, re.M)
    except Exception:
        return []
    seen: dict[str, None] = {}
    for d in deps:
        seen.setdefault(d, None)
    return list(seen)[:MAX_DEPS]
