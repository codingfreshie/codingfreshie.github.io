"""Secret detection and redaction. Matches are replaced; secret values are never stored or logged."""
from __future__ import annotations

import re
from collections import Counter

_PLACEHOLDER = re.compile(r"(?i)your|example|placeholder|change.?me|x{4,}|\*{3,}|<|>|\.\.\.")

PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
]

_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b(api[_\-]?key|secret[_\-]?key|client[_\-]?secret|secret|access[_\-]?token|auth[_\-]?token|token|passwd|password)\b
    (\s*[:=]\s*)(["']?)([A-Za-z0-9_\-/+=]{16,})\3
    """
)

REDACTED = "[REDACTED]"


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return (clean_text, {kind: count}). Never returns matched secret values."""
    found: Counter = Counter()

    for kind, pattern in PATTERNS:
        def _sub(match, kind=kind):
            found[kind] += 1
            return REDACTED

        text = pattern.sub(_sub, text)

    def _assign(match):
        value = match.group(4)
        if _PLACEHOLDER.search(value):
            return match.group(0)
        found["credential_assignment"] += 1
        return f"{match.group(1)}{match.group(2)}{match.group(3)}{REDACTED}{match.group(3)}"

    text = _ASSIGNMENT.sub(_assign, text)
    return text, dict(found)


def scrub(text: str, extra_values: tuple[str, ...] = ()) -> str:
    """Remove secrets from a string destined for logs."""
    for value in extra_values:
        if value:
            text = text.replace(value, "***")
    return redact(text)[0]
