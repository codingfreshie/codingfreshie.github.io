"""Turns a Jupyter notebook into plain text: markdown and code cells only. Outputs are dropped."""
from __future__ import annotations

import json


def notebook_to_text(raw: bytes) -> str | None:
    try:
        nb = json.loads(raw.decode("utf-8"))
        cells = nb["cells"]
    except Exception:
        return None
    lang = (nb.get("metadata", {}).get("language_info", {}) or {}).get("name", "python")
    parts: list[str] = []
    for cell in cells:
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        if not src.strip():
            continue
        if cell.get("cell_type") == "markdown":
            parts.append(src.strip())
        elif cell.get("cell_type") == "code":
            parts.append(f"```{lang}\n{src.strip()}\n```")
    return "\n\n".join(parts)
