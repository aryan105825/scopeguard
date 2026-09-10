"""
agent/guardrails.py
--------------------
Fully deterministic, LLM-free guardrail layer.

This module NEVER makes a model call. Every function here is a pure,
unit-testable transformation over plain data: it consumes the raw
four-field JSON object produced by agent/auditor.py plus the full SOW
text, and returns a (possibly modified) copy of that object.

Two independent gates must BOTH pass for a non-ambiguous verdict to
survive:
    1. Citation verification: `cited_clause` must appear as a verbatim
       (or fuzzy, if enabled) substring of the SOW text. Fails closed —
       never optimistically passes.
    2. Confidence threshold: `confidence_score` must be >= 0.85.

A verified citation does not exempt a verdict from the confidence gate.
A high confidence score does not exempt a verdict from the citation
gate. Either failure forces `verdict` to "ambiguous".

This module only classifies and annotates. It does not decide what
action to take next (that is Supervisor/routing logic elsewhere).
"""

from copy import deepcopy
from typing import Any, Dict, Optional

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ImportError:  # pragma: no cover
    _rapidfuzz_fuzz = None


CONFIDENCE_THRESHOLD = 0.85
FUZZY_MATCH_THRESHOLD = 95  # rapidfuzz partial_ratio score, 0-100 scale


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def verify_citation(
    cited_clause: str,
    sow_text: str,
    use_fuzzy: bool = True,
) -> bool:
    """
    Determine whether `cited_clause` genuinely appears in `sow_text`.

    Fails closed: any ambiguity, empty input, or missing dependency
    results in False, never an optimistic True.
    """
    if not isinstance(cited_clause, str) or not isinstance(sow_text, str):
        return False

    stripped_clause = cited_clause.strip()
    if not stripped_clause:
        return False

    # Exact substring check first (cheapest, most trustworthy).
    if stripped_clause in sow_text:
        return True

    # Whitespace-normalized exact check, to tolerate formatting/line-wrap
    # differences without resorting to fuzzy scoring.
    normalized_clause = _normalize_whitespace(stripped_clause)
    normalized_sow = _normalize_whitespace(sow_text)
    if normalized_clause and normalized_clause in normalized_sow:
        return True

    # Optional fuzzy fallback. Only used if explicitly enabled AND the
    # rapidfuzz dependency is available. Still fails closed: if
    # rapidfuzz is unavailable, we do NOT fall back to trusting the
    # claim, we simply return False.
    if use_fuzzy and _rapidfuzz_fuzz is not None:
        score = _rapidfuzz_fuzz.partial_ratio(normalized_clause, normalized_sow)
        if score >= FUZZY_MATCH_THRESHOLD:
            return True

    return False


def _append_reasoning_note(reasoning: str, note: str) -> str:
    """Append an explanatory note to existing reasoning without
    discarding the original text."""
    reasoning = reasoning or ""
    if reasoning.strip():
        return f"{reasoning.strip()} [{note}]"
    return f"[{note}]"


def apply_guardrails(
    auditor_output: Dict[str, Any],
    sow_text: str,
    use_fuzzy: bool = True,
) -> Dict[str, Any]:
    """
    Apply deterministic guardrail checks to the Auditor's raw output.

    Parameters
    ----------
    auditor_output:
        Dict with exactly the four fields produced by agent/auditor.py:
        `verdict`, `confidence_score`, `cited_clause`, `reasoning`.
    sow_text:
        The same full SOW text string that was given to the Auditor.
    use_fuzzy:
        Whether to allow rapidfuzz-based fuzzy matching as a fallback
        during citation verification.

    Returns
    -------
    A new dict (the input is not mutated) with `verdict` possibly
    forced to "ambiguous" and `reasoning` possibly annotated.
    """
    result = deepcopy(auditor_output)

    verdict = result.get("verdict")
    confidence_score = result.get("confidence_score")
    cited_clause = result.get("cited_clause", "")
    reasoning = result.get("reasoning", "")

    citation_verified = verify_citation(cited_clause, sow_text, use_fuzzy=use_fuzzy)

    confidence_ok = (
        isinstance(confidence_score, (int, float))
        and confidence_score >= CONFIDENCE_THRESHOLD
    )

    forced_to_ambiguous = False

    if not citation_verified:
        forced_to_ambiguous = True
        reasoning = _append_reasoning_note(
            reasoning,
            "citation could not be verified against the SOW text",
        )

    if not confidence_ok:
        forced_to_ambiguous = True
        reasoning = _append_reasoning_note(
            reasoning,
            "confidence_score below required threshold of "
            f"{CONFIDENCE_THRESHOLD}",
        )

    if forced_to_ambiguous:
        verdict = "ambiguous"

    result["verdict"] = verdict
    result["reasoning"] = reasoning
    result["_citation_verified"] = citation_verified
    result["_confidence_ok"] = confidence_ok

    return result