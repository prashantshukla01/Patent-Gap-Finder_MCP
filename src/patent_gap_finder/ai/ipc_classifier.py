"""Gemini-powered IPC/CPC patent classification.

Maps AI-extracted claims to International Patent Classification (IPC)
and Cooperative Patent Classification (CPC) codes using Gemini's
JSON mode with inline reference examples.
"""

from __future__ import annotations

import logging
import re

from patent_gap_finder.ai.gemini_client import GeminiClient, get_gemini_client
from patent_gap_finder.models.ipc import (
    AIExtractedClaim,
    ClaimIPCMapping,
    IPCClassificationResponse,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# IPC validation
# ──────────────────────────────────────────────────────────────────────

_IPC_REGEX = re.compile(r"^[A-H]\d{2}[A-Z] \d+/\d+$")


def validate_ipc_code(code: str) -> bool:
    """Check whether an IPC code matches the standard format.

    Valid format: ``[A-H][0-9]{2}[A-Z] [0-9]+/[0-9]+``
    Examples: ``G06N 3/08``, ``H04L 9/30``

    Args:
        code: The IPC code string to validate.

    Returns:
        True if the code matches the IPC pattern.
    """
    return bool(_IPC_REGEX.match(code.strip()))


# ──────────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a patent classification expert. Your task is to assign IPC (International Patent Classification) and CPC (Cooperative Patent Classification) codes to patent claims extracted from a research paper.

**IPC Section Reference:**
- Section A: Human Necessities
- Section B: Performing Operations; Transporting
- Section C: Chemistry; Metallurgy
- Section D: Textiles; Paper
- Section E: Fixed Constructions
- Section F: Mechanical Engineering; Lighting; Heating; Weapons; Blasting
- Section G: Physics (includes computing: G06)
- Section H: Electricity (includes communications: H04)

**Key computing subclasses:**
- G06F - Electric digital data processing
- G06N - Computing; calculating; counting (neural networks, ML, AI)
- G06V - Image or video recognition
- G06T - Image data processing or generation
- H04L - Transmission of digital information

**Classification examples:**
1. "A method for training a transformer model using sparse attention..." → G06N 3/08, G06N 3/04
2. "A system for detecting objects in images using depthwise convolution..." → G06V 10/40, G06N 3/08
3. "A method for encrypting data with lattice-based cryptography..." → H04L 9/30
4. "A composition of nanoparticles for targeted drug delivery..." → A61K 9/51, B82Y 5/00
5. "A method for compressing genomic sequences using entropy coding..." → G16B 30/00, G06F 17/30

**IPC code format:** Each code MUST follow the pattern: [A-H][0-9][0-9][A-Z] [digits]/[digits]
Examples: "G06N 3/08", "H04L 9/30", "A61K 9/51"

**Rules:**
- Be conservative — if you are not confident in a code, assign confidence < 0.5 and note the uncertainty.
- Provide a primary IPC code and optionally secondary codes for each claim.
- The CPC code is often the same as or very similar to the IPC code.
- Generate 10–15 search_keywords: technical terms suitable for USPTO PatentsView full-text search.
- Deduplicate top_ipc_codes across all claims, ranked by frequency.

**Required JSON response schema:**
{
  "mappings": [
    {
      "claim_text": "The claim text...",
      "primary_ipc": "G06N 3/08",
      "secondary_ipc": ["G06N 3/04"],
      "cpc_code": "G06N 3/08",
      "confidence": 0.85,
      "rationale": "This claim describes neural network training which falls under G06N 3/08.",
      "is_valid_ipc": true
    }
  ],
  "top_ipc_codes": ["G06N 3/08", "G06N 3/04"],
  "search_keywords": ["transformer", "attention mechanism", "neural network training"],
  "classification_summary": "One paragraph summarizing the classification results."
}

Respond with valid JSON only matching the schema above."""


# ──────────────────────────────────────────────────────────────────────
# Prompt builder
# ──────────────────────────────────────────────────────────────────────

def _build_user_prompt(
    claims: list[AIExtractedClaim],
    primary_domain: str,
) -> str:
    """Build the user prompt for IPC classification.

    Args:
        claims: AI-extracted claims to classify.
        primary_domain: The paper's primary technical domain.

    Returns:
        Formatted user prompt string.
    """
    parts = [
        f"# Primary Technical Domain: {primary_domain}",
        f"\n# Claims to Classify ({len(claims)} total):\n",
    ]

    for i, claim in enumerate(claims, 1):
        parts.append(
            f"## Claim {i} (type: {claim.claim_type})\n"
            f"**Text:** {claim.claim_text}\n"
            f"**Domain:** {claim.technical_domain}\n"
            f"**Novelty:** {claim.novelty_basis}\n"
        )

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

async def classify_ipc(
    claims: list[AIExtractedClaim],
    primary_domain: str,
    *,
    client: GeminiClient | None = None,
) -> IPCClassificationResponse:
    """Classify claims into IPC/CPC codes using Gemini.

    After receiving the Gemini response, validates each IPC code against
    the standard regex pattern and sets ``is_valid_ipc`` accordingly.

    Args:
        claims: List of AI-extracted claims.
        primary_domain: Paper's primary technical domain.
        client: Optional Gemini client (uses singleton if not provided).

    Returns:
        :class:`IPCClassificationResponse` with validated mappings.

    Raises:
        GeminiRateLimitError: If rate limit persists after retries.
        GeminiDailyQuotaError: If daily quota is exhausted.
        GeminiResponseValidationError: If response fails validation.
    """
    if client is None:
        client = get_gemini_client()

    user_prompt = _build_user_prompt(claims, primary_domain)

    logger.info(
        "Classifying %d claims for domain '%s'",
        len(claims),
        primary_domain,
    )

    response = await client.complete_json(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        schema=IPCClassificationResponse,
        max_tokens=4000,
    )

    # Post-process: validate IPC codes against regex
    for mapping in response.mappings:
        mapping.is_valid_ipc = validate_ipc_code(mapping.primary_ipc)
        if not mapping.is_valid_ipc:
            logger.warning(
                "Invalid IPC code '%s' for claim: %s",
                mapping.primary_ipc,
                mapping.claim_text[:60],
            )

    valid_count = sum(1 for m in response.mappings if m.is_valid_ipc)
    logger.info(
        "IPC classification complete: %d/%d valid codes, %d top codes, %d keywords",
        valid_count,
        len(response.mappings),
        len(response.top_ipc_codes),
        len(response.search_keywords),
    )

    return response
