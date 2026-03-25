"""Gemini-powered patent claim extraction from research papers.

Assembles a carefully structured prompt with few-shot examples
and uses Gemini's JSON mode to extract patent-quality claims.
"""

from __future__ import annotations

import logging

from patent_gap_finder.ai.gemini_client import GeminiClient, get_gemini_client
from patent_gap_finder.models.ipc import AIExtractedClaim, AIExtractedClaimsResponse
from patent_gap_finder.models.paper import ParsedPaper

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# System prompt
# ──────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a patent attorney's technical assistant specializing in identifying patentable inventions in research papers.

Your task is to extract 5–10 independent patent claims from the research paper provided below. Each claim must be a patent-quality statement following the standard structure:

**Patent Claim Structure:**
- **Preamble**: What is being claimed (e.g., "A method for…", "A system comprising…")
- **Transition word**: "comprising", "consisting of", or "including"
- **Body elements**: Specific technical steps, components, or features that define the invention

**GOOD claim examples (extract claims like these):**

1. "A method for training a neural network comprising: receiving a dataset of labeled examples; computing gradients using backpropagation with a novel sparse attention mask that reduces computation by O(n log n); and updating model parameters based on the computed sparse gradients."

2. "A system for real-time object detection comprising: a first processing unit configured to apply a sliding window at multiple scales; a feature extraction module implementing a depthwise separable convolution with channel-wise attention; and a classification head that outputs bounding box coordinates and class probabilities."

**BAD claim examples (do NOT extract claims like these):**

1. "We improve accuracy by 3% over baseline."
   → Reason: Not a claim, just a result statement with no structural novelty.

2. "The transformer architecture is well known and we use it here."
   → Reason: No novelty, describes a known technique without modification.

**Rules:**
- Extract 5–10 claims, not more.
- If confidence is below 0.5, omit the claim entirely.
- Ignore incremental improvements on known techniques with no structural novelty.
- Each claim must identify a specific novel technical contribution.
- For each claim, explain WHY it might be patentable in the novelty_basis field.
- Classify each claim as "method", "system", or "composition".

**Required JSON response schema:**
{
  "claims": [
    {
      "claim_text": "A method for ... comprising: ...",
      "claim_type": "method",
      "technical_domain": "natural language processing",
      "novelty_basis": "Introduces a novel sparse attention mechanism...",
      "source_section": "Section title",
      "confidence": 0.85
    }
  ],
  "paper_summary": "2-3 sentence technical summary of the paper",
  "primary_domain": "Main technical field"
}

Respond with valid JSON only matching the schema above."""


# ──────────────────────────────────────────────────────────────────────
# Prompt assembler
# ──────────────────────────────────────────────────────────────────────

def _build_user_prompt(paper: ParsedPaper) -> str:
    """Assemble the user prompt from paper content.

    Includes full abstract, introduction, and conclusion, plus the
    first 800 chars of each remaining section for context.

    Args:
        paper: A parsed research paper.

    Returns:
        Formatted user prompt string.
    """
    parts: list[str] = [
        f"# Paper Title: {paper.title}",
        f"## Authors: {', '.join(paper.authors) if paper.authors else 'Unknown'}",
    ]

    # Full abstract
    if paper.abstract:
        parts.append(f"\n## Abstract\n{paper.abstract}")

    # Separate sections by priority
    full_sections = ["abstract", "introduction", "conclusion"]
    truncated_types = ["methodology", "results", "other"]

    for section in paper.sections:
        if section.section_type in full_sections:
            parts.append(f"\n## {section.title}\n{section.content}")
        elif section.section_type in truncated_types:
            content = section.content
            if len(content) > 800:
                content = content[:800] + "... [truncated]"
            parts.append(f"\n## {section.title}\n{content}")

    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

async def extract_claims(
    paper: ParsedPaper,
    *,
    client: GeminiClient | None = None,
) -> AIExtractedClaimsResponse:
    """Extract patent-quality claims from a parsed paper using Gemini.

    Args:
        paper: A :class:`ParsedPaper` object from Phase 1 parsing.
        client: Optional Gemini client (uses singleton if not provided).

    Returns:
        :class:`AIExtractedClaimsResponse` with extracted claims.

    Raises:
        GeminiRateLimitError: If rate limit persists after retries.
        GeminiDailyQuotaError: If daily quota is exhausted.
        GeminiResponseValidationError: If response fails validation.
    """
    if client is None:
        client = get_gemini_client()

    user_prompt = _build_user_prompt(paper)

    logger.info(
        "Extracting claims for paper '%s' (prompt_chars=%d)",
        paper.title[:60],
        len(user_prompt),
    )

    response = await client.complete_json(
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        schema=AIExtractedClaimsResponse,
        max_tokens=4000,
    )

    logger.info(
        "Extracted %d AI claims for '%s' (domain=%s)",
        len(response.claims),
        paper.title[:60],
        response.primary_domain,
    )

    return response
