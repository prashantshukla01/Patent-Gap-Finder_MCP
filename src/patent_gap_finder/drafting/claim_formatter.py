"""USPTO patent claim formatter and validator.

Converts raw DraftedClaim objects into properly formatted USPTO claim
sections and validates for common drafting issues.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from patent_gap_finder.models.drafts import DraftedClaim

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Antecedent basis validation — common preamble terms to skip
# ──────────────────────────────────────────────────────────────────────

COMMON_EXCEPTIONS = {
    "method",
    "system",
    "computing system",
    "processor",
    "network",
    "apparatus",
    "step",
    "steps",
    "present disclosure",
    "embodiment",
    "invention",
    "device",
    "computer",
    "memory",
    "server",
    "client",
    "user",
    "data",
    "input",
    "output",
    "result",
    "plurality",
}


def format_claim_set(raw_claims: list[DraftedClaim]) -> str:
    """Format drafted claims into a proper USPTO claims section.

    Produces output like:

        CLAIMS

        1. A method for training a neural network comprising:
           receiving, by a computing system, a training dataset;
           constructing a sparse attention mask; and
           updating model parameters using backpropagation.

        2. The method of claim 1, wherein the sparse attention mask
           has a sparsity ratio greater than 0.7.

    Args:
        raw_claims: List of DraftedClaim objects to format.

    Returns:
        Formatted claims section as a string.
    """
    if not raw_claims:
        return "CLAIMS\n\n(No claims drafted)"

    lines: list[str] = ["CLAIMS"]

    for claim in sorted(raw_claims, key=lambda c: c.claim_number):
        lines.append("")  # Blank line between claims

        claim_text = claim.claim_text.strip()

        # Ensure dependent claims have proper back-reference
        if claim.claim_type == "dependent" and claim.depends_on is not None:
            category = claim.patent_claim_category or "method"
            expected_prefix = f"The {category} of claim {claim.depends_on}"
            if not claim_text.startswith(expected_prefix) and not claim_text.startswith(f"{claim.claim_number}."):
                # Check if it starts with a number
                number_prefix = re.match(r"^\d+\.\s*", claim_text)
                if number_prefix:
                    claim_text = claim_text[number_prefix.end():]
                if not claim_text.startswith("The "):
                    claim_text = f"{expected_prefix}, wherein {claim_text}"

        # Remove leading claim number if Gemini included one
        number_prefix = re.match(r"^\d+\.\s*", claim_text)
        if number_prefix:
            claim_text = claim_text[number_prefix.end():]

        # Format with proper indentation
        # First line: "N. [claim text]"
        # Subsequent lines of multi-line claims: "   [continuation]"
        claim_lines = claim_text.split("\n")
        first_line = f"{claim.claim_number}. {claim_lines[0]}"
        lines.append(first_line)

        for continuation in claim_lines[1:]:
            continuation = continuation.strip()
            if continuation:
                lines.append(f"   {continuation}")

    return "\n".join(lines) + "\n"


def validate_claim_set(claims: list[DraftedClaim]) -> list[str]:
    """Validate a set of claims for common USPTO drafting issues.

    Returns a list of warning strings (not errors — claims are not
    rejected, just flagged). Uses simple heuristics that catch ~80%
    of common issues.

    Args:
        claims: List of DraftedClaim objects to validate.

    Returns:
        List of warning message strings.
    """
    warnings: list[str] = []

    independent_claims = [c for c in claims if c.claim_type == "independent"]
    dependent_claims = [c for c in claims if c.claim_type == "dependent"]
    claim_numbers = {c.claim_number for c in claims}

    # Check independent claims
    for claim in independent_claims:
        text = claim.claim_text.lower()

        # Check for overly broad claims without structural elements
        structural_terms = [
            "processor", "memory", "module", "component", "circuit",
            "sensor", "network", "layer", "matrix", "vector",
            "database", "storage", "interface", "controller",
        ]
        has_structure = any(term in text for term in structural_terms)
        functional_terms = [
            "configured to", "adapted to", "operable to",
            "comprising", "including", "receiving", "transmitting",
            "computing", "generating", "determining", "applying",
        ]
        has_function = any(term in text for term in functional_terms)

        if not has_structure and not has_function:
            warnings.append(
                f"Claim {claim.claim_number} may be too broad — "
                f"no structural elements or functional language specified"
            )

    # Check dependent claims
    for claim in dependent_claims:
        # Check that referenced parent claim exists
        if claim.depends_on is not None and claim.depends_on not in claim_numbers:
            warnings.append(
                f"Claim {claim.claim_number} references claim {claim.depends_on} "
                f"which does not exist in the set"
            )

        # Check for dependent-on-dependent chains
        if claim.depends_on is not None:
            parent = next(
                (c for c in claims if c.claim_number == claim.depends_on),
                None,
            )
            if parent and parent.claim_type == "dependent":
                warnings.append(
                    f"Claim {claim.claim_number} references claim {claim.depends_on} "
                    f"but claim {claim.depends_on} is also dependent — check chain"
                )

    # Check all claims for common issues
    for claim in claims:
        text = claim.claim_text

        # Check for "the invention" language
        if re.search(r"\bthe\s+invention\b", text, re.IGNORECASE):
            warnings.append(
                f"Claim {claim.claim_number} contains 'the invention' — "
                f"should be removed for USPTO filing"
            )

        # Check for "improves performance" vagueness
        vague_patterns = [
            r"\bimproves?\s+performance\b",
            r"\bimproves?\s+accuracy\b",
            r"\busing\s+AI\b",
            r"\busing\s+artificial\s+intelligence\b",
            r"\busing\s+machine\s+learning\b",
        ]
        for pattern in vague_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                warnings.append(
                    f"Claim {claim.claim_number} contains vague language "
                    f"matching '{pattern}' — consider more specific wording"
                )

        # Antecedent basis check (heuristic — catches ~80% of cases)
        _check_antecedent_basis(claim, warnings)

    return warnings


def _check_antecedent_basis(claim: DraftedClaim, warnings: list[str]) -> None:
    """Check for missing antecedent basis using simple regex heuristic.

    Finds all "the X" references and checks that "a/an X" was introduced
    earlier in the claim text. Skips common exceptions (terms that
    naturally appear in preambles without needing introduction).

    This is NOT a full coreference resolution — it catches about 80% of
    straightforward antecedent issues.
    """
    text = claim.claim_text

    # Find all "the X" references (1-2 word noun phrases)
    the_refs = re.findall(r"\bthe\s+(\w+(?:\s+\w+)?)", text, re.IGNORECASE)

    # Find all "a/an X" introductions
    a_refs = re.findall(r"\b(?:a|an)\s+(\w+(?:\s+\w+)?)", text, re.IGNORECASE)

    # Normalize for comparison
    a_refs_lower = {ref.lower() for ref in a_refs}

    seen_warnings = set()
    for ref in the_refs:
        ref_lower = ref.lower()

        # Skip common exceptions
        if ref_lower in COMMON_EXCEPTIONS:
            continue

        # Skip if introduced with a/an
        if ref_lower in a_refs_lower:
            continue

        # Skip single common words
        if ref_lower in {
            "first", "second", "third", "at", "least", "one", "each",
            "following", "above", "below", "same", "said", "claim",
        }:
            continue

        # Avoid duplicate warnings
        if ref_lower not in seen_warnings:
            seen_warnings.add(ref_lower)
            warnings.append(
                f"Claim {claim.claim_number}: Possible missing antecedent — "
                f"'the {ref}' used but 'a {ref}' not found in introduction"
            )
