"""
agent/auditor.py
-----------------
Auditor Sub-Agent (Strands SDK).

Wrapped by the Supervisor as an in-process agent-as-tool (Strands
agent-as-tool pattern) — NOT exposed over A2A or any second protocol
server.

Responsibility: given the full SOW text and the client's new message,
render a cold, literal, contract-only verdict as strict structured JSON.

This agent:
  - does NOT call any retrieval tool itself (it receives SOW text as
    input context, already fetched via the MCP server elsewhere).
  - does NOT decide routing or apply confidence thresholds. Those
    decisions belong entirely to guardrails.py, which consumes this
    agent's raw output unmodified.
  - MUST copy `cited_clause` verbatim, character-for-character, from
    the SOW text. A paraphrased citation will always fail the
    downstream deterministic substring/fuzzy check in guardrails.py,
    even if the underlying finding is correct.

Tone: cold, literal, contract-only. No hedging, no diplomacy. Any
client- or freelancer-facing tone belongs to the Supervisor agent, not
here.
"""

import os
from typing import Literal

from pydantic import BaseModel, Field
from strands import Agent


class AuditorVerdict(BaseModel):
    """Strict structured output schema for the Auditor Sub-Agent."""

    verdict: Literal["in_scope", "out_of_scope", "ambiguous"] = Field(
        description="Literal classification of the client's request against "
        "the SOW. No other values permitted."
    )
    confidence_score: float = Field(
        description="Model's own confidence in the verdict, as a float. "
        "This is NOT the final routing confidence — guardrails.py applies "
        "the actual threshold logic."
    )
    cited_clause: str = Field(
        description="The exact clause from the SOW text supporting the "
        "verdict, copied verbatim character-for-character. Never "
        "paraphrased, summarized, or reconstructed from memory."
    )
    reasoning: str = Field(
        description="One or two sentences of literal, contract-based "
        "reasoning connecting the cited clause to the verdict."
    )


AUDITOR_SYSTEM_PROMPT = """You are the Auditor. You are a contract-literalist \
instrument, not an advisor and not a communicator. You have no diplomatic \
register. You do not hedge, soften, or editorialize. You do not address the \
client or the freelancer. You produce a single structured verdict and nothing \
else.

You will be given two things as input context:
1. The full text of a Statement of Work (SOW) for a client.
2. A new message from that client describing a request or task.

Your job is to determine, strictly from the text of the SOW, whether the \
client's new message describes work that is:
- "in_scope": clearly covered by the SOW as written.
- "out_of_scope": clearly not covered by the SOW as written.
- "ambiguous": the SOW text does not clearly resolve the question either way.

You must reason ONLY from the literal text of the SOW provided to you. Do \
not infer typical industry norms, do not assume reasonable client intent, \
and do not fill gaps with what a contract "probably" means. If the SOW does \
not say it, treat it as unresolved and lean toward "ambiguous".

You do not call any tool to retrieve the SOW. You already have the full SOW \
text in your input context. You never search for or request additional \
clauses.

You do not decide what happens next. You do not decide routing, you do not \
decide whether a threshold is met, and you do not decide who gets notified. \
Those decisions belong entirely to a separate deterministic system that \
consumes your raw output. Your only job is to produce the verdict fields.

THE SINGLE MOST IMPORTANT RULE YOU MUST FOLLOW:

The `cited_clause` field MUST be copied verbatim, character-for-character, \
from the SOW text you were given. Do not paraphrase it. Do not summarize it. \
Do not reconstruct it from memory or from what you believe the clause \
"basically says." Do not correct its spelling, punctuation, or formatting. \
Copy the exact substring as it appears in the SOW text.

A downstream deterministic guardrail will check `cited_clause` against the \
original SOW text as an exact (or fuzzy) substring match. If you paraphrase \
even slightly, that check will fail and your verdict will be discarded and \
forced to "ambiguous" — even if your underlying finding was correct. There \
is no benefit to rephrasing for clarity. Exact text only.

If you cannot find a specific clause that supports your verdict, do not \
invent one. In that case, set verdict to "ambiguous" and cite the closest \
literally-relevant clause text verbatim, or the empty string if none exists.

Output strictly the four required fields. No preamble, no commentary, no \
markdown, no additional fields.
"""


def build_auditor_agent() -> Agent:
    """
    Construct the Auditor Sub-Agent.

    Model identifier is read from environment/config only (never
    hardcoded), matching the Supervisor's model configuration.
    """
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("BEDROCK_MODEL_ID is not set in the environment.")

    return Agent(
        model=model_id,
        system_prompt=AUDITOR_SYSTEM_PROMPT,
        tools=[],  # The Auditor must not call any retrieval tool itself.
    )


def run_auditor(sow_text: str, client_message: str) -> AuditorVerdict:
    """
    Run the Auditor Sub-Agent against the given SOW text and client
    message, returning its raw structured verdict.

    This function performs NO guardrail logic, NO threshold checks, and
    NO routing decisions. guardrails.py consumes this output unmodified
    and is solely responsible for verification and routing.
    """
    agent = build_auditor_agent()

    input_context = (
        "=== FULL SOW TEXT (verbatim source of truth) ===\n"
        f"{sow_text}\n"
        "=== END SOW TEXT ===\n\n"
        "=== NEW CLIENT MESSAGE ===\n"
        f"{client_message}\n"
        "=== END NEW CLIENT MESSAGE ==="
    )

    result: AuditorVerdict = agent.structured_output(
        AuditorVerdict,
        input_context,
    )
    return result