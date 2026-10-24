"""Flags text that looks like an attempt to instruct the analysis model.

Repository content is untrusted data. Nothing is removed; flags only route an entry to review.

Two tiers:
  HIGH: phrases that only make sense as an attack ("ignore previous instructions", "reveal the API key").
        These send the entry to human review.
  LOW:  phrases that appear in any legitimate LLM project ("You are an AI assistant...", "system prompt").
        These are recorded as information only, because AI projects contain prompts by design.
"""
from __future__ import annotations

import re

_HIGH = [
    ("ignore_instructions", r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|prompts?|rules)"),
    ("disregard_instructions", r"disregard (?:all |any |the )?(?:previous|prior|above|system) (?:instructions|prompts?|rules)"),
    ("reveal_secrets", r"\b(?:reveal|print|output|send|exfiltrate|leak)\b.{0,40}\b(?:api[ _-]?keys?|secret keys?|passwords?|credentials|(?:access|auth|api|secret|bearer|private) tokens?)\b"),
    ("message_to_ai", r"\b(?:note|message|instruction)s? (?:to|for) (?:the )?(?:ai|llm|assistant|model|agent) (?:that )?(?:reading|analy[sz]ing|summari[sz]ing)"),
    ("chat_markup", r"<\|(?:im_start|im_end|system|assistant)\|>|\[/?inst\]"),
    ("force_category", r"\b(?:classify|categori[sz]e) (?:this|the) (?:project|repo(?:sitory)?) as\b"),
]
_LOW = [
    ("role_prompt", r"\byou are (?:now )?(?:an? )?(?:ai|assistant|language model|chatbot|llm)\b"),
    ("system_prompt", r"\bsystem prompt\b"),
]
HIGH = [(label, re.compile(p, re.I | re.S)) for label, p in _HIGH]
LOW = [(label, re.compile(p, re.I | re.S)) for label, p in _LOW]


def find_injection(text: str) -> list[str]:
    """High-signal labels only. These trigger review."""
    return [label for label, pattern in HIGH if pattern.search(text)]


def find_prompt_text(text: str) -> list[str]:
    """Low-signal labels: the file contains prompt-like text. Informational."""
    return [label for label, pattern in LOW if pattern.search(text)]
