"""Merges drafts into projects.json, then runs the same validator CI uses. Restores the file if it fails."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .draft import unique_id
from .settings import ROOT


def node_validator() -> tuple[bool, str]:
    try:
        done = subprocess.run(["node", "scripts/validate-data.mjs"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "Node.js was not found, so the data could not be validated."
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def apply_drafts(drafts_dir: Path, projects_path: Path, validator=node_validator) -> dict:
    original = Path(projects_path).read_text("utf-8")
    data = json.loads(original)
    repo_ids = {p["repository_id"] for p in data["projects"]}
    ids = {p["id"] for p in data["projects"]}
    added, skipped = [], []

    for path in sorted(Path(drafts_dir).glob("draft-*.json")):
        project = json.loads(path.read_text("utf-8"))["project"]
        if project["repository_id"] in repo_ids:
            skipped.append(project["id"])
            continue
        project["id"] = unique_id(project["id"], ids)
        ids.add(project["id"])
        repo_ids.add(project["repository_id"])
        data["projects"].append(project)
        added.append(project["id"])

    if not added:
        return {"added": [], "skipped": skipped, "ok": True, "output": "Nothing new to add."}

    Path(projects_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    ok, output = validator()
    if not ok:
        Path(projects_path).write_text(original, "utf-8")   # never leave invalid data behind
        return {"added": [], "skipped": skipped, "ok": False, "output": output}
    return {"added": added, "skipped": skipped, "ok": True, "output": output}
