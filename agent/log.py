from __future__ import annotations

import logging
import os
import sys

from .secrets import scrub


class ScrubFilter(logging.Filter):
    """Last line of defense: strip tokens and secret-shaped strings from every log line."""

    def filter(self, record: logging.LogRecord) -> bool:
        tokens = tuple(v for v in (os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_TOKEN"), os.environ.get("GEMINI_API_KEY")) if v)
        record.msg = scrub(record.getMessage(), tokens)
        record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", "%H:%M:%S"))
    handler.addFilter(ScrubFilter())
    root = logging.getLogger("agent")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False
