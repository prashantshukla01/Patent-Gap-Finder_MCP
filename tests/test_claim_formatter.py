import pytest

from patent_gap_finder.models.drafts import DraftedClaim
from patent_gap_finder.drafting.claim_formatter import format_claim_set, validate_claim_set


@pytest.fixture
def sample_drafts():
    return [
        DraftedClaim(
            claim_number=1,
            claim_text="first element;\nsecond element;\nand third element.",
            claim_type="independent",
            depends_on=None,
            patent_claim_category="method"
        ),
        DraftedClaim(
            claim_number=2,
            claim_text="the method of claim 1, wherein the first element is X.",
            claim_type="dependent",
            depends_on=1,
            patent_claim_category="method"
        ),
        DraftedClaim(
            claim_number=3,
            claim_text="the method of claim 2, wherein the second element is Y.",
            claim_type="dependent",
            depends_on=2,
            patent_claim_category="method"
        )
    ]


def test_format_claim_set(sample_drafts):
    formatted = format_claim_set(sample_drafts)
    
    assert "CLAIMS" in formatted
    assert "1." in formatted
    assert "   first element;" in formatted
    assert "and third element." in formatted
    assert "2. the method of claim 1" in formatted
    assert "\n\nthe method of claim" not in formatted  # Verify no extra line breaks inside claims


def test_validate_claim_set(sample_drafts):
    warnings = validate_claim_set(sample_drafts)
    assert len(warnings) == 0


def test_validate_claim_set_with_invention_phrase():
    drafts = [
        DraftedClaim(
            claim_number=1,
            claim_text="a method for the system of the invention comprising X.",
            claim_type="independent",
            depends_on=None,
            patent_claim_category="method"
        )
    ]
    warnings = validate_claim_set(drafts)
    assert any("the invention" in w for w in warnings)


def test_validate_claim_set_missing_antecedent():
    drafts = [
        DraftedClaim(
            claim_number=1,
            claim_text="a method comprising:\nreceiving data;\nprocessing the widget;",
            claim_type="independent",
            depends_on=None,
            patent_claim_category="method"
        )
    ]
    warnings = validate_claim_set(drafts)
    assert any("the widget" in w for w in warnings)

def test_validate_claim_set_antecedent_present():
    drafts = [
        DraftedClaim(
            claim_number=1,
            claim_text="a method comprising:\nreceiving a widget;\nprocessing the widget;",
            claim_type="independent",
            depends_on=None,
            patent_claim_category="method"
        )
    ]
    warnings = validate_claim_set(drafts)
    assert len(warnings) == 0
