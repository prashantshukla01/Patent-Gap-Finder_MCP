"""Async wrapper around the Google Generative AI (Gemini) SDK.

The google-generativeai SDK is synchronous. All blocking calls are
dispatched via ``asyncio.to_thread()`` to avoid freezing the FastMCP
event loop.  A module-level singleton ensures the ``asyncio.Semaphore``
rate-limiter is shared across all concurrent MCP tool calls.

Rate limiting:
    - asyncio.Semaphore(1) serialises all Gemini calls
    - 4-second sleep after each call → ≤15 RPM
    - Exponential backoff on 429 (10s / 20s / 40s)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Optional, TypeVar

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-1.5-flash"
_MIN_REQUEST_GAP_SECONDS = 4.0
_MAX_RETRIES = 3
_BASE_BACKOFF_SECONDS = 10.0

T = TypeVar("T", bound=BaseModel)

# ──────────────────────────────────────────────────────────────────────
# Custom exceptions
# ──────────────────────────────────────────────────────────────────────


class GeminiRateLimitError(Exception):
    """Raised when rate limit hit and all retries exhausted."""
    pass


class GeminiDailyQuotaError(Exception):
    """Raised when daily free tier quota is exhausted."""
    pass


class GeminiResponseValidationError(Exception):
    """Raised when Gemini response fails Pydantic validation after retry."""
    pass


# ──────────────────────────────────────────────────────────────────────
# Gemini client
# ──────────────────────────────────────────────────────────────────────


class GeminiClient:
    """Rate-limited async wrapper around the Gemini SDK.

    This class is designed as a singleton — use :func:`get_gemini_client`
    to obtain the shared instance.  The ``asyncio.Semaphore`` ensures
    only one Gemini call is in-flight at a time, and the 4-second post-call
    sleep enforces the 15 RPM free-tier limit.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError(
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com/app/apikey"
            )
        genai.configure(api_key=key)
        self._model = genai.GenerativeModel(GEMINI_MODEL)
        self._semaphore = asyncio.Semaphore(1)

        # Usage counters
        self.total_requests: int = 0
        self.total_prompt_chars: int = 0
        self.total_response_chars: int = 0

    # ── Core text completion ──────────────────────────────────────────

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 2000,
    ) -> str:
        """Send a text prompt to Gemini and return the response text.

        Combines *system* and *user* into a single prompt since Gemini
        Flash does not support a separate system role in basic calls.

        Args:
            system: Context / instruction text (prepended).
            user: The main task prompt.
            max_tokens: Maximum output tokens.

        Returns:
            Response text string.

        Raises:
            GeminiRateLimitError: If 429 persists after retries.
            GeminiDailyQuotaError: If daily quota is exhausted.
        """
        prompt = f"Context and Instructions:\n{system}\n\n---\n\nTask:\n{user}"
        config = genai.GenerationConfig(max_output_tokens=max_tokens)
        return await self._call_with_retry(prompt, config)

    # ── JSON completion with Pydantic validation ─────────────────────

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: type[T],
        *,
        max_tokens: int = 4000,
    ) -> T:
        """Send a prompt and parse the response as a Pydantic model.

        Uses Gemini's native JSON mode (``response_mime_type``) for
        guaranteed JSON output.  Validates against *schema* and retries
        once with a corrective prompt on validation failure.

        Args:
            system: Context / instruction text.
            user: The main task prompt.
            schema: Pydantic model class to validate against.
            max_tokens: Maximum output tokens.

        Returns:
            Validated Pydantic model instance.

        Raises:
            GeminiResponseValidationError: If validation fails after retry.
        """
        prompt = f"Context and Instructions:\n{system}\n\n---\n\nTask:\n{user}"
        config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
        )

        raw_text = await self._call_with_retry(prompt, config)
        cleaned = self._strip_markdown_fences(raw_text)

        try:
            data = json.loads(cleaned)
            return schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as first_error:
            logger.warning(
                "First JSON parse/validation failed: %s — retrying with correction",
                first_error,
            )
            # Retry with corrective prompt
            correction_prompt = (
                f"{prompt}\n\n---\n\n"
                f"CORRECTION: Your previous response had this validation error:\n"
                f"{first_error}\n\n"
                f"Please fix your response to match the required JSON schema exactly."
            )
            raw_text_2 = await self._call_with_retry(correction_prompt, config)
            cleaned_2 = self._strip_markdown_fences(raw_text_2)

            try:
                data_2 = json.loads(cleaned_2)
                return schema.model_validate(data_2)
            except (json.JSONDecodeError, ValidationError) as second_error:
                raise GeminiResponseValidationError(
                    f"Gemini response failed validation after retry: {second_error}"
                ) from second_error

    # ── Internal helpers ─────────────────────────────────────────────

    async def _call_with_retry(
        self,
        prompt: str,
        config: genai.GenerationConfig,
    ) -> str:
        """Execute a Gemini call with rate limiting and retry logic.

        Args:
            prompt: The full prompt string.
            config: Generation config.

        Returns:
            Response text.
        """
        last_error: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES + 1):
            async with self._semaphore:
                try:
                    start = time.monotonic()
                    response = await asyncio.to_thread(
                        self._model.generate_content,
                        prompt,
                        generation_config=config,
                    )
                    elapsed = time.monotonic() - start

                    text = response.text or ""

                    # Update counters
                    self.total_requests += 1
                    self.total_prompt_chars += len(prompt)
                    self.total_response_chars += len(text)

                    logger.info(
                        "Gemini call: model=%s prompt_chars=%d response_chars=%d "
                        "latency=%.1fs total_requests=%d",
                        GEMINI_MODEL,
                        len(prompt),
                        len(text),
                        elapsed,
                        self.total_requests,
                    )

                    # Enforce minimum gap between requests
                    await asyncio.sleep(_MIN_REQUEST_GAP_SECONDS)
                    return text

                except ResourceExhausted as e:
                    last_error = e
                    error_msg = str(e).lower()

                    if "quota" in error_msg and attempt >= 1:
                        raise GeminiDailyQuotaError(
                            "Gemini daily free-tier quota exhausted. "
                            "Try again tomorrow or upgrade to a paid plan."
                        ) from e

                    if attempt < _MAX_RETRIES:
                        backoff = _BASE_BACKOFF_SECONDS * (2 ** attempt)
                        logger.warning(
                            "Gemini 429 (attempt %d/%d) — backing off %.0fs",
                            attempt + 1,
                            _MAX_RETRIES,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        raise GeminiRateLimitError(
                            f"Gemini rate limit exceeded after {_MAX_RETRIES} retries"
                        ) from e

        # Should never reach here, but satisfy type checker
        raise GeminiRateLimitError(
            f"Gemini call failed after {_MAX_RETRIES} retries: {last_error}"
        )

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Strip markdown code fences that Gemini occasionally adds.

        Even with ``response_mime_type="application/json"``, Gemini Flash
        sometimes wraps output in ````json ... ``` ``.
        """
        text = text.strip()
        text = re.sub(r"^```json\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return text.strip()


# ──────────────────────────────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────────────────────────────

_client_instance: Optional[GeminiClient] = None


def get_gemini_client() -> GeminiClient:
    """Return the shared :class:`GeminiClient` singleton.

    Creates the instance on first call. The singleton pattern ensures
    the ``asyncio.Semaphore`` rate-limiter is shared across all MCP
    tool calls.

    Returns:
        The global GeminiClient instance.

    Raises:
        ValueError: If ``GEMINI_API_KEY`` is not set.
    """
    global _client_instance
    if _client_instance is None:
        _client_instance = GeminiClient()
    return _client_instance


def reset_gemini_client() -> None:
    """Reset the singleton (used in tests)."""
    global _client_instance
    _client_instance = None
