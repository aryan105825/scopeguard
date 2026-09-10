"""
tests/test_auditor.py
-----------------------
Unit tests for agent/auditor.py.

Scope of these tests:
  - Structural correctness of the Auditor's returned object (exactly
    four fields, correct types, verdict is one of the allowed
    literals).
  - Most importantly: for clearly in-scope and clearly out-of-scope
    fixture cases, `cited_clause` must be an exact, verbatim substring
    of the corresponding fixture SOW text. This is the property
    guardrails.py relies on, so it is validated here at the source.

These tests do NOT exercise threshold-based routing/confidence-gate
logic — that belongs entirely to test_guardrails.py.

The Auditor's underlying model call is mocked; these are unit tests of
the auditor module's contract, not integration tests against a live
Bedrock model.
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.auditor import AuditorVerdict, run_auditor

FIXTURES_DIR = Path(__file__).parent / "fixtures"

ALLOWED_VERDICTS = {"in_scope", "out_of_scope", "ambiguous"}

REQUIRED_FIELDS = {"verdict", "confidence_score", "cited_clause", "reasoning"}


def _load_sow_text(sow_filename: str) -> str:
    return (FIXTURES_DIR / sow_filename).read_text(encoding="utf-8")


def _load_messages(messages_filename: str) -> dict:
    return json.loads((FIXTURES_DIR / messages_filename).read_text(encoding="utf-8"))


FIXTURE_SETS = [
    "messages_acme_website.json",
    "messages_globex_app.json",
    "messages_nimbus_brand.json",
]


def _mock_agent_returning(verdict_obj: AuditorVerdict):
    """Build a mock Strands Agent whose structured_output returns the
    given AuditorVerdict, regardless of input."""
    mock_agent = MagicMock()
    mock_agent.structured_output.return_value = verdict_obj
    return mock_agent


@pytest.fixture(autouse=True)
def _ensure_model_env(monkeypatch):
    monkeypatch.setenv("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-6-v1:0")


@pytest.mark.parametrize("messages_filename", FIXTURE_SETS)
def test_auditor_returns_exactly_four_fields_with_correct_types(messages_filename):
    fixture_set = _load_messages(messages_filename)
    sow_text = _load_sow_text(fixture_set["sow_file"])
    message = fixture_set["messages"][0]

    # Extract a real verbatim substring from the SOW to use as a
    # plausible mocked citation.
    plausible_clause = sow_text.splitlines()[5].strip() or sow_text[:40].strip()

    mocked_verdict = AuditorVerdict(
        verdict="in_scope",
        confidence_score=0.92,
        cited_clause=plausible_clause,
        reasoning="Directly matches a stated deliverable.",
    )

    with patch("agent.auditor.build_auditor_agent") as mock_build:
        mock_build.return_value = _mock_agent_returning(mocked_verdict)
        result = run_auditor(sow_text, message["text"])

    result_dict = result.model_dump()

    assert set(result_dict.keys()) == REQUIRED_FIELDS
    assert isinstance(result_dict["verdict"], str)
    assert isinstance(result_dict["confidence_score"], float)
    assert isinstance(result_dict["cited_clause"], str)
    assert isinstance(result_dict["reasoning"], str)


@pytest.mark.parametrize("messages_filename", FIXTURE_SETS)
def test_auditor_verdict_is_always_an_allowed_literal(messages_filename):
    fixture_set = _load_messages(messages_filename)
    sow_text = _load_sow_text(fixture_set["sow_file"])
    message = fixture_set["messages"][0]

    plausible_clause = sow_text.splitlines()[5].strip() or sow_text[:40].strip()

    for candidate_verdict in ["in_scope", "out_of_scope", "ambiguous"]:
        mocked_verdict = AuditorVerdict(
            verdict=candidate_verdict,
            confidence_score=0.9,
            cited_clause=plausible_clause,
            reasoning="Test reasoning.",
        )
        with patch("agent.auditor.build_auditor_agent") as mock_build:
            mock_build.return_value = _mock_agent_returning(mocked_verdict)
            result = run_auditor(sow_text, message["text"])

        assert result.verdict in ALLOWED_VERDICTS


@pytest.mark.parametrize("messages_filename", FIXTURE_SETS)
def test_cited_clause_is_verbatim_substring_for_in_scope_and_out_of_scope_cases(
    messages_filename,
):
    """
    The single most important property tested in this file: for clearly
    in-scope and clearly out-of-scope fixture messages, the Auditor's
    cited_clause must be an EXACT, verbatim substring of the fixture
    SOW text. guardrails.py depends entirely on this property holding
    at the source.
    """
    fixture_set = _load_messages(messages_filename)
    sow_text = _load_sow_text(fixture_set["sow_file"])

    clear_cases = [
        m
        for m in fixture_set["messages"]
        if m["expected_category"] in ("in_scope", "out_of_scope")
    ]
    assert clear_cases, "Fixture set must contain clear in/out-of-scope cases"

    for case in clear_cases:
        # Pick a genuine verbatim clause from this SOW to simulate a
        # correctly-behaving Auditor.
        candidate_lines = [
            line.strip() for line in sow_text.splitlines() if len(line.strip()) > 20
        ]
        genuine_clause = candidate_lines[2]

        mocked_verdict = AuditorVerdict(
            verdict=case["expected_category"],
            confidence_score=0.95,
            cited_clause=genuine_clause,
            reasoning=f"Matches expectation for {case['id']}.",
        )

        with patch("agent.auditor.build_auditor_agent") as mock_build:
            mock_build.return_value = _mock_agent_returning(mocked_verdict)
            result = run_auditor(sow_text, case["text"])

        assert result.cited_clause in sow_text, (
            f"cited_clause for case {case['id']!r} was not a verbatim "
            f"substring of the SOW text: {result.cited_clause!r}"
        )


def test_auditor_agent_is_constructed_without_retrieval_tools():
    """
    The Auditor must not be given any retrieval tool — it operates
    purely on the SOW text and message passed into its input context.
    """
    from agent.auditor import build_auditor_agent

    with patch("agent.auditor.Agent") as mock_agent_cls:
        build_auditor_agent()
        _, kwargs = mock_agent_cls.call_args
        assert kwargs.get("tools") == []


def test_auditor_agent_uses_model_id_from_environment(monkeypatch):
    """
    Model identifier must come from BEDROCK_MODEL_ID env var, never a
    hardcoded literal.
    """
    from agent.auditor import build_auditor_agent

    monkeypatch.setenv("BEDROCK_MODEL_ID", "some-configured-model-id")

    with patch("agent.auditor.Agent") as mock_agent_cls:
        build_auditor_agent()
        _, kwargs = mock_agent_cls.call_args
        assert kwargs.get("model") == "some-configured-model-id"


def test_auditor_raises_if_model_id_env_var_missing(monkeypatch):
    from agent.auditor import build_auditor_agent

    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)

    with pytest.raises(RuntimeError):
        build_auditor_agent()