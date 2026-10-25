"""Optional LLM-assisted code review for higher-level architectural feedback."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"


class LLMReviewer:
    """Sends PR diff hunks to an LLM API for higher-level architectural & logic review."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.api_key = (
            api_key
            or os.environ.get("REVIEWBOT_LLM_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.base_url = (
            base_url or os.environ.get("REVIEWBOT_LLM_BASE_URL") or DEFAULT_LLM_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("REVIEWBOT_LLM_MODEL") or DEFAULT_LLM_MODEL
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self.api_key and self.api_key.strip())

    def review_diff(self, filename: str, patch: str) -> Optional[str]:
        """Request concise, high-level feedback on a diff patch from the LLM."""
        if not self.is_configured:
            logger.warning(
                "LLM review was requested (--llm-review), but no API key was found in "
                "REVIEWBOT_LLM_API_KEY or OPENAI_API_KEY. Skipping LLM review."
            )
            return None

        if not patch or not patch.strip():
            return None

        prompt = (
            f"Review the following Git unified diff for file '{filename}'. "
            "Focus only on high-level architecture, subtle logical bugs, or performance pitfalls. "
            "Do not comment on formatting or trivial style. Keep your feedback under 3 bullet points:\n\n"
            f"```diff\n{patch[:4000]}\n```"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a senior software engineer performing a code review.",
                },
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 500,
            "temperature": 0.2,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code >= 400:
                    logger.warning(
                        "LLM API returned status %d. LLM feedback skipped.",
                        resp.status_code,
                    )
                    return None

                data = resp.json()
                content: str = data["choices"][0]["message"]["content"]
                return content.strip()

        except Exception as exc:
            # Never log headers or API keys
            logger.warning(
                "Failed to retrieve LLM feedback for '%s': %s", filename, type(exc).__name__
            )
            return None
