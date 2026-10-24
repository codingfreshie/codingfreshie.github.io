"""Thin, throttled Gemini wrapper: retries transient errors, never logs the key."""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("agent.gemini")


class AnalysisError(Exception):
    """The analysis could not be completed."""


class ValidationFailed(AnalysisError):
    """The model answered, but the answer broke our rules. Worth one corrective retry."""


class GeminiClient:
    RETRY_CODES = {429, 500, 502, 503, 504}

    def __init__(self, model: str, api_key: str | None = None, min_interval: float = 7.0, max_retries: int = 4,
                 client=None, sleep=time.sleep, clock=time.monotonic):
        if client is None:
            key = api_key or os.environ.get("GEMINI_API_KEY")
            if not key:
                raise AnalysisError("GEMINI_API_KEY is not set. Create a key in Google AI Studio and export it.")
            from google import genai
            client = genai.Client(api_key=key)
        self._client = client
        self.model = model
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._sleep, self._clock = sleep, clock
        self._last_call: float | None = None

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self.min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def list_models(self) -> list[str]:
        """Model ids this key can call generateContent on."""
        names = []
        for m in self._client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions or not actions:
                names.append(str(m.name).removeprefix("models/"))
        return sorted(names)

    def generate_json(self, system: str, user: str, schema: dict) -> str:
        from google.genai import errors, types

        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0.2,
        )
        attempt = 0
        while True:
            self._throttle()
            try:
                response = self._client.models.generate_content(model=self.model, contents=user, config=config)
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code in self.RETRY_CODES and attempt < self.max_retries:
                    wait = min(90, 20 * (attempt + 1)) if code == 429 else 3 * 2 ** attempt
                    log.warning("event=retry reason=gemini_%s attempt=%d wait=%ds", code, attempt + 1, wait)
                    self._sleep(wait)
                    attempt += 1
                    continue
                if code == 404:
                    raise AnalysisError(f"Model '{self.model}' was not found for this key. "
                                        "Run `python -m agent.analyze models` and set gemini_model in agent/settings.json.") from exc
                if code == 429:
                    raise AnalysisError("Gemini rate limit or quota still exceeded after retries. Wait and re-run; finished drafts are kept.") from exc
                raise AnalysisError(f"Gemini API error {code}: {str(getattr(exc, 'message', exc))[:200]}") from exc
            text = getattr(response, "text", None)
            if not text:
                raise AnalysisError("Gemini returned no text (the response may have been blocked).")
            return text
