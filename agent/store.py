"""Safe writes to projects.json: backups, validation, rollback, undo."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path


def backup(projects_path: Path, out_dir: Path, keep: int = 30) -> Path:
    """Copy projects.json aside before any command changes it."""
    folder = Path(out_dir) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"projects-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
    shutil.copy2(projects_path, dest)
    for old in sorted(folder.glob("projects-*.json"))[:-keep]:
        old.unlink()
    return dest


def undo(projects_path: Path, out_dir: Path) -> Path | None:
    """Restore the most recent backup and discard it, so repeated undo steps further back."""
    files = sorted((Path(out_dir) / "backups").glob("projects-*.json"))
    if not files:
        return None
    shutil.copy2(files[-1], projects_path)
    files[-1].unlink()
    return files[-1]


def write_validated(projects_path: Path, data: dict, validator) -> tuple[bool, str]:
    """Write, run the real validator, and put the old file back if it fails."""
    original = Path(projects_path).read_text("utf-8")
    Path(projects_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    ok, output = validator()
    if not ok:
        Path(projects_path).write_text(original, "utf-8")
    return ok, output


def load(projects_path: Path) -> dict:
    return json.loads(Path(projects_path).read_text("utf-8"))
