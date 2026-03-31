"""Gemini prompts for Phase 4: cluster labeling and novelty assessment.

Two functions:
- label_cluster: name a cluster from its central patent titles
- assess_novelty: evaluate a claim's patentability vs nearest prior art
"""

from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def label_cluster(
    titles: list[str],
    patent_count: int,
) -> dict:
    """Ask Gemini to label a patent cluster.

    Args:
        titles: Titles of the 3 most central patents.
        patent_count: Total patents in the cluster.

    Returns:
        {"label": "3-5 word theme", "technical_domain": "field name"}
    """
    from patent_gap_finder.ai.gemini_client import get_gemini_client

    client = get_gemini_client()

    titles_text = "\n".join(f'- "{t}"' for t in titles if t)

    system = (
        "You are a patent classification expert. Given a list of patent titles "
        "from a cluster of related patents, identify the unifying technical theme."
    )
    user = (
        f"This cluster contains {patent_count} patents. "
        f"Representative titles:\n{titles_text}\n\n"
        f'Respond with ONLY a JSON object: '
        f'{{"label": "3-5 word theme", "technical_domain": "field name"}}'
    )

    raw = await client.complete(system=system, user=user, max_tokens=200)

    try:
        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        return {
            "label": data.get("label", "unknown cluster"),
            "technical_domain": data.get("technical_domain", ""),
        }
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to parse Gemini cluster label: %s", e)
        return {"label": "unknown cluster", "technical_domain": ""}


async def assess_novelty(
    claim,
    nearest_patents: list[dict],
    avg_similarity: float,
    nearest_cluster_label: str,
) -> dict:
    """Ask Gemini to assess a claim's novelty against nearest prior art.

    Only called for claims that pass quantitative white-space thresholds.

    Args:
        claim: ExtractedClaim ORM object.
        nearest_patents: List of {title, abstract} for top 3 neighbors.
        avg_similarity: Average cosine similarity to K nearest patents.
        nearest_cluster_label: Label of the closest patent cluster.

    Returns:
        NoveltyAssessment-compatible dict.
    """
    from patent_gap_finder.ai.gemini_client import get_gemini_client

    client = get_gemini_client()

    claim_text = getattr(claim, "claim_text", str(claim))
    claim_type = getattr(claim, "claim_type", "method")
    primary_ipc = getattr(claim, "primary_ipc", None)

    # Interpret similarity
    if avg_similarity < 0.4:
        sim_interp = "very different from existing patents"
    elif avg_similarity < 0.65:
        sim_interp = "somewhat similar to existing patents"
    else:
        sim_interp = "highly similar to existing patents"

    patents_text = ""
    for i, p in enumerate(nearest_patents[:3], 1):
        title = p.get("title", "Unknown")
        abstract = p.get("abstract", "")[:300]
        patents_text += f"\n{i}. \"{title}\"\n   Abstract: {abstract}\n"

    system = (
        "You are a patent attorney assessing whether a research contribution "
        "is novel enough to warrant a patent application. A claim is novel if "
        "no single prior patent discloses ALL elements of the claim in combination. "
        "Low similarity score alone does not guarantee novelty — assess whether "
        "the technical combination is genuinely new."
    )

    user = (
        f"Research claim ({claim_type}):\n\"{claim_text}\"\n\n"
        f"Average similarity to nearest patents: {avg_similarity:.3f} ({sim_interp})\n"
        f"Nearest technology cluster: {nearest_cluster_label}\n\n"
        f"Nearest prior art patents:{patents_text}\n\n"
        f"Respond with ONLY a JSON object:\n"
        f'{{\n'
        f'  "gemini_novelty_assessment": "2-3 sentence reasoning",\n'
        f'  "gemini_confidence": 0.0-1.0,\n'
        f'  "recommended_claim_scope": "broad" | "medium" | "narrow",\n'
        f'  "ipc_whitespace_codes": ["IPC codes where gap exists"],\n'
        f'  "key_differentiators": ["what makes this distinct"]\n'
        f'}}'
    )

    raw = await client.complete(system=system, user=user, max_tokens=1000)

    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        data = json.loads(cleaned)
        return {
            "gemini_novelty_assessment": data.get("gemini_novelty_assessment", ""),
            "gemini_confidence": float(data.get("gemini_confidence", 0.5)),
            "recommended_claim_scope": data.get("recommended_claim_scope", "medium"),
            "ipc_whitespace_codes": data.get("ipc_whitespace_codes", []),
            "key_differentiators": data.get("key_differentiators", []),
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to parse Gemini novelty assessment: %s", e)
        return {
            "gemini_novelty_assessment": "Assessment parsing failed",
            "gemini_confidence": 0.5,
            "recommended_claim_scope": "medium",
            "ipc_whitespace_codes": [primary_ipc] if primary_ipc else [],
            "key_differentiators": [],
        }
