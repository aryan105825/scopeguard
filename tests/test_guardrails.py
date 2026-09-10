"""
tests/test_guardrails.py
--------------------------
Unit tests for agent/guardrails.py.

guardrails.py is fully deterministic and LLM-free, so these tests run
purely against fixture data. No mocking, no stubbing, no network calls,
no LLM involvement anywhere in this file.

Covers the three non-negotiable behaviors from the spec:
  (a) valid, verified citation + high confidence -> accepted as-is.
  (b) valid, verified citation + low confidence -> downgraded to
      ambiguous regardless of citation status.
  (c) fabricated/unverifiable citation + high stated confidence ->
      downgraded to ambiguous, proving the guardrail does real work
      rather than naively trusting confidence_score alone.
"""

from pathlib import Path

import pytest

from agent.guardrails import (
    CONFIDENCE_THRESHOLD,
    apply_guardrails,
    verify_citation,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_sow_text(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def acme_sow_text():
    return _load_sow_text("sow_acme_website.txt")


def _extract_genuine_clause(sow_text: str) -> str:
    """Pull a real, verbatim line out of the SOW text to use as a
    genuinely-verifiable citation in tests."""
    for line in sow_text.splitlines():
        stripped = line.strip()
        if len(stripped) > 25:
            return stripped
    raise AssertionError("Fixture SOW did not contain a usable line")


# ---------------------------------------------------------------------
# (a) Valid, verified citation + high confidence -> accepted as-is.
# ---------------------------------------------------------------------
def test_valid_citation_with_high_confidence_passes_through_unchanged(acme_sow_text):
    genuine_clause = _extract_genuine_clause(acme_sow_text)

    auditor_output = {
        "verdict": "out_of_scope",
        "confidence_score": 0.93,
        "cited_clause": genuine_clause,
        "reasoning": "Directly excluded by Section 3.",
    }

    result = apply_guardrails(auditor_output, acme_sow_text)

    assert result["verdict"] == "out_of_scope"
    assert result["reasoning"] == "Directly excluded by Section 3."
    assert result["_citation_verified"] is True
    assert result["_confidence_ok"] is True


# ---------------------------------------------------------------------
# (b) Valid, verified citation + low confidence -> forced to ambiguous.
# ---------------------------------------------------------------------
def test_valid_citation_with_low_confidence_is_downgraded_to_ambiguous(acme_sow_text):
    genuine_clause = _extract_genuine_clause(acme_sow_text)

    auditor_output = {
        "verdict": "in_scope",
        "confidence_score": 0.60,
        "cited_clause": genuine_clause,
        "reasoning": "Matches the responsive layout clause.",
    }

    result = apply_guardrails(auditor_output, acme_sow_text)

    assert result["verdict"] == "ambiguous"
    assert result["_citation_verified"] is True
    assert result["_confidence_ok"] is False
    # Original reasoning must be preserved, not discarded.
    assert "Matches the responsive layout clause." in result["reasoning"]
    assert "confidence_score" in result["reasoning"].lower() or "threshold" in result["reasoning"].lower()


# ---------------------------------------------------------------------
# (c) Fabricated/unverifiable citation + high confidence -> downgraded.
# This is the case that proves the guardrail does real work: a naive
# implementation trusting confidence_score alone would wrongly accept
# this.
# ---------------------------------------------------------------------
def test_fabricated_citation_with_high_confidence_is_caught_and_downgraded(
    acme_sow_text,
):
    fabricated_clause = (
        "The Freelancer agrees to add a Careers page at no additional "
        "cost per the verbal agreement made during the kickoff call."
    )
    assert fabricated_clause not in acme_sow_text  # sanity check on fixture

    auditor_output = {
        "verdict": "in_scope",
        "confidence_score": 0.95,
        "cited_clause": fabricated_clause,
        "reasoning": "Client referenced a prior verbal agreement to add this page.",
    }

    result = apply_guardrails(auditor_output, acme_sow_text)

    assert result["verdict"] == "ambiguous"
    assert result["_citation_verified"] is False
    assert result["_confidence_ok"] is True  # confidence itself was high
    assert "citation could not be verified" in result["reasoning"].lower()
    # Original reasoning preserved, not discarded.
    assert "Client referenced a prior verbal agreement" in result["reasoning"]


# ---------------------------------------------------------------------
# Additional coverage: both gates are independent.
# ---------------------------------------------------------------------
def test_both_citation_and_confidence_failing_still_forces_ambiguous(acme_sow_text):
    auditor_output = {
        "verdict": "out_of_scope",
        "confidence_score": 0.40,
        "cited_clause": "This clause does not exist anywhere in the SOW text.",
        "reasoning": "Some reasoning.",
    }

    result = apply_guardrails(auditor_output, acme_sow_text)

    assert result["verdict"] == "ambiguous"
    assert result["_citation_verified"] is False
    assert result["_confidence_ok"] is False
    assert "citation could not be verified" in result["reasoning"].lower()
    assert "threshold" in result["reasoning"].lower() or "confidence_score" in result["reasoning"].lower()


def test_apply_guardrails_does_not_mutate_input(acme_sow_text):
    genuine_clause = _extract_genuine_clause(acme_sow_text)
    original = {
        "verdict": "in_scope",
        "confidence_score": 0.9,
        "cited_clause": genuine_clause,
        "reasoning": "Original reasoning.",
    }
    original_copy = dict(original)

    apply_guardrails(original, acme_sow_text)

    assert original == original_copy


# ---------------------------------------------------------------------
# verify_citation unit-level tests
# ---------------------------------------------------------------------
def test_verify_citation_exact_substring_match(acme_sow_text):
    genuine_clause = _extract_genuine_clause(acme_sow_text)
    assert verify_citation(genuine_clause, acme_sow_text) is True


def test_verify_citation_fails_closed_on_fabricated_text(acme_sow_text):
    assert verify_citation("Totally made up clause text.", acme_sow_text) is False


def test_verify_citation_fails_closed_on_empty_clause(acme_sow_text):
    assert verify_citation("", acme_sow_text) is False
    assert verify_citation("   ", acme_sow_text) is False


def test_verify_citation_tolerates_whitespace_differences(acme_sow_text):
    genuine_clause = _extract_genuine_clause(acme_sow_text)
    whitespace_mangled = "  " + "  ".join(genuine_clause.split()) + "  "
    assert verify_citation(whitespace_mangled, acme_sow_text) is True


def test_confidence_threshold_constant_matches_spec():
    assert CONFIDENCE_THRESHOLD == 0.85