"""The shape the model must answer in. Hand-written JSON Schema (no $ref) for Gemini, Pydantic for parsing."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Feature(BaseModel):
    text: str
    source: str  # repository path that supports the claim


class Analysis(BaseModel):
    name: str
    description: str
    overview: str
    features: list[Feature]
    planned: list[str]
    development_status: Literal["complete", "in_progress", "unclear"]
    primary_category: str
    category_confidence: float
    category_reasoning: str
    alternative_category: str
    tags: list[str]
    tech_stack: list[str]
    overall_confidence: float


def response_schema(category_ids: list[str]) -> dict:
    string = {"type": "string"}
    number = {"type": "number"}
    return {
        "type": "object",
        "properties": {
            "name": {**string, "description": "Human-friendly project name"},
            "description": {**string, "description": "One or two factual sentences, at most 240 characters"},
            "overview": {**string, "description": "One short paragraph"},
            "features": {
                "type": "array",
                "description": "Implemented features only, each citing the file that shows it",
                "items": {
                    "type": "object",
                    "properties": {"text": string, "source": {**string, "description": "A file path from the supplied data"}},
                    "required": ["text", "source"],
                },
            },
            "planned": {"type": "array", "items": string, "description": "Goals or roadmap items not shown in the code"},
            "development_status": {"type": "string", "enum": ["complete", "in_progress", "unclear"]},
            "primary_category": {"type": "string", "enum": list(category_ids)},
            "category_confidence": {**number, "description": "0 to 1"},
            "category_reasoning": {**string, "description": "One sentence"},
            "alternative_category": {"type": "string", "enum": list(category_ids) + ["none"],
                                     "description": "Another category a reasonable reader could pick, or none if the choice is clear"},
            "tags": {"type": "array", "items": string, "description": "Topics or domains, not technologies"},
            "tech_stack": {"type": "array", "items": string},
            "overall_confidence": {**number, "description": "0 to 1; lower when evidence is thin"},
        },
        "required": list(Analysis.model_fields),
    }
