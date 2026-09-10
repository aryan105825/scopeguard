"""
agent/scopeguard_main.py
---------------------------
Strands Supervisor Agent + AgentCore entrypoint.

This file owns ALL client-facing and freelancer-facing tone. It is
warm, professional, and unambiguously on the freelancer's side -- a
deliberate contrast to the cold, literal, contract-only Auditor
sub-agent. The Auditor's clinical output (verdict/confidence/citation/
reasoning) is treated as raw evidence, never surfaced unedited into a
client-facing draft.

Architecture notes:
  - The Auditor (agent/auditor.py) is wired in as a Strands tool using
    the agent-as-tool pattern: a plain, in-process, function-style
    call. This is deliberately NOT implemented as a separate A2A
    protocol server -- standing up a second protocol server for
    in-process reasoning would be unnecessary overhead.
  - The SOW is retrieved via an MCP client connected to
    server/mcp_sow_retriever.py (get_active_sow / list_active_clients
    only -- no chunked search tool exists or should be added).
  - guardrails.py is the sole arbiter of the final verdict. The
    Supervisor never second-guesses or bypasses it.
  - Nothing is ever auto-sent to a client without human review in
    Slack.

This module is structured to be pointed to directly by:
    agentcore configure -e agent/scopeguard_main.py
with no separate wrapper module required.
"""

import json
import os
from typing import Any, Dict, Optional

from strands import Agent, tool
from strands.tools.mcp import MCPClient
from mcp.client.stdio import stdio_client, StdioServerParameters

from agent.auditor import run_auditor
from agent.guardrails import apply_guardrails
from agent.memory import get_long_term_facts, append_long_term_fact
from agent.model_config import get_agent_kwargs
try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except ImportError:  # pragma: no cover
    BedrockAgentCoreApp = None


# ---------------------------------------------------------------------------
# Supervisor system prompt -- tone lives here, and ONLY here.
# ---------------------------------------------------------------------------

SUPERVISOR_SYSTEM_PROMPT = """You are ScopeGuard, an assistant that helps an \
independent freelancer protect their time and their contract without \
damaging the client relationship. You are warm, professional, and firmly on \
the freelancer's side. You are never cold, never robotic, and never \
adversarial toward the client -- you are diplomatic, but you do not let \
scope creep slide.

You will sometimes be given a raw, clinical audit finding (a verdict, a \
confidence score, a verbatim contract citation, and terse reasoning) \
produced by a separate literal-minded audit tool. That raw finding is \
evidence for you to reason from -- it is NOT client-facing language. Never \
paste the Auditor's raw reasoning or citation format directly into a \
message to a client. If you draft a client-facing pushback message, write \
it in your own warm, professional voice, referencing the relevant contract \
language naturally and briefly, and always proposing a constructive path \
forward (e.g. a change order) rather than simply saying no.

You will also sometimes be given prior negotiated facts about this client \
(declined offers, established scope precedents, or previously agreed \
changes). Use these to avoid re-offering something the client already \
declined, and to stay consistent with precedent you've already set with \
this client.

You never send anything to a client without a human freelancer reviewing \
and approving it first in Slack. Every draft you produce is a draft for \
review, not a sent message.
"""


# ---------------------------------------------------------------------------
# MCP client wiring -- connects to server/mcp_sow_retriever.py
# ---------------------------------------------------------------------------

def _build_sow_mcp_client() -> MCPClient:
    """
    Build the MCP client connected to the narrow SOW-retrieval server.
    Only two tools are ever exposed by that server: get_active_sow and
    list_active_clients. No chunked/search tool exists there, and none
    should be assumed here.
    """
    return MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="python",
                args=["-m", "server.mcp_sow_retriever"],
            )
        )
    )


def _fetch_sow_text(sow_mcp_client: MCPClient, client_id: str) -> str:
    with sow_mcp_client:
        tools = sow_mcp_client.list_tools_sync()
        get_sow_tool = next(t for t in tools if t.tool_name == "get_active_sow")
        result = sow_mcp_client.call_tool_sync(
            tool_use_id="scopeguard-sow-fetch",
            name=get_sow_tool.tool_name,
            arguments={"client_id": client_id},
        )
        return result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Auditor wired in as an in-process Strands tool (agent-as-tool pattern).
# Deliberately NOT an A2A server -- this stays a plain function call.
# ---------------------------------------------------------------------------

@tool
def run_scope_audit(sow_text: str, client_message: str) -> str:
    """
    Run the Auditor Sub-Agent against the given SOW text and client
    message, then pass its raw output through the deterministic
    guardrail layer. Returns the guardrail-verified JSON result as a
    string.

    This tool wraps the Auditor in-process (agent-as-tool), not over
    A2A or any second protocol server.
    """
    raw_verdict = run_auditor(sow_text, client_message)
    guarded_result = apply_guardrails(raw_verdict.model_dump(), sow_text)
    return json.dumps(guarded_result)


def build_supervisor_agent() -> Agent:
    kwargs = get_agent_kwargs()
    return Agent(
        system_prompt=SUPERVISOR_SYSTEM_PROMPT,
        tools=[run_scope_audit],
        **kwargs
    )

# ---------------------------------------------------------------------------
# Routing -- exact decision table applied after the guardrail verdict.
# ---------------------------------------------------------------------------

def route_guarded_result(guarded_result: Dict[str, Any]) -> str:
    """
    Determine the routing action for a guardrail-verified result.

    Returns one of: "silent_log", "draft_pushback", "ping_freelancer".

    Routing rules (exact):
      - "out_of_scope" with verified citation and confidence >= 0.85
        -> "draft_pushback" (drafted for freelancer review, never
        auto-sent).
      - "in_scope" -> "silent_log". This is expected to be the outcome
        for most messages and must NOT trigger any Slack notification.
      - "ambiguous" (including any case the guardrail downgraded from
        something else) -> "ping_freelancer" directly. Nothing is ever
        drafted to the client in this branch.
    """
    verdict = guarded_result.get("verdict")

    if verdict == "in_scope":
        return "silent_log"

    if verdict == "out_of_scope":
        # By construction, apply_guardrails() only allows "out_of_scope"
        # to survive when citation_verified and confidence_ok are both
        # True -- but we check explicitly here too, defensively, rather
        # than trusting that invariant blindly.
        if guarded_result.get("_citation_verified") and guarded_result.get(
            "_confidence_ok"
        ):
            return "draft_pushback"
        return "ping_freelancer"

    # "ambiguous" and any unexpected value both fail safe to pinging
    # the freelancer -- never to a client-facing draft.
    return "ping_freelancer"


# ---------------------------------------------------------------------------
# Turn-level orchestration
# ---------------------------------------------------------------------------

def handle_incoming_message(
    client_id: str,
    client_message: str,
    source_message_id: str,
) -> Dict[str, Any]:
    """
    Full per-turn orchestration:
      1. Query long-term facts for this client_id (before any drafting).
      2. Retrieve the SOW via the MCP client.
      3. Run the Auditor tool (agent-as-tool) + guardrails.
      4. Route according to the exact rules above.
      5. If routed to draft_pushback, produce a warm, professional
         draft using the Supervisor's own voice -- never the Auditor's
         raw phrasing -- for human review in Slack.

    Returns a dict describing the action taken, suitable for the Slack
    app layer to render as a review card or silent log entry.
    """
    long_term_facts = get_long_term_facts(client_id)

    sow_mcp_client = _build_sow_mcp_client()
    sow_text = _fetch_sow_text(sow_mcp_client, client_id)

    supervisor = build_supervisor_agent()

    audit_tool_result = run_scope_audit(sow_text, client_message)
    guarded_result = json.loads(audit_tool_result)

    action = route_guarded_result(guarded_result)

    if action == "silent_log":
        return {
            "action": "silent_log",
            "client_id": client_id,
            "verdict": guarded_result["verdict"],
            "notify_slack": False,
        }

    if action == "ping_freelancer":
        return {
            "action": "ping_freelancer",
            "client_id": client_id,
            "verdict": guarded_result["verdict"],
            "reasoning": guarded_result["reasoning"],
            "notify_slack": True,
            "client_facing_draft": None,
        }

    # action == "draft_pushback"
    facts_context = "\n".join(
        f"- [{f.fact_type}] {f.summary} ({f.date})" for f in long_term_facts
    ) or "No prior negotiated facts on file for this client."

    drafting_prompt = (
        "A client message has been flagged as out-of-scope work with a "
        "verified contract citation. Draft a warm, professional message "
        "to the client explaining that this request falls outside the "
        "current Statement of Work, referencing the relevant contract "
        "language naturally (do not quote the raw citation verbatim as a "
        "legal excerpt -- paraphrase it into natural language), and "
        "proposing a constructive next step such as a change order. This "
        "is a DRAFT for freelancer review only; it will not be sent "
        "automatically.\n\n"
        f"Prior negotiated facts for this client:\n{facts_context}\n\n"
        f"Client's message:\n{client_message}\n\n"
        f"Cited contract clause (for your reference, paraphrase, don't "
        f"quote raw):\n{guarded_result['cited_clause']}\n\n"
        f"Audit reasoning (for your reference only):\n"
        f"{guarded_result['reasoning']}"
    )

    draft_response = supervisor(drafting_prompt)
    client_facing_draft = str(draft_response)

    return {
        "action": "draft_pushback",
        "client_id": client_id,
        "verdict": guarded_result["verdict"],
        "cited_clause": guarded_result["cited_clause"],
        "confidence_score": guarded_result["confidence_score"],
        "client_facing_draft": client_facing_draft,
        "source_message_id": source_message_id,
        "notify_slack": True,
    }


def record_sent_draft(
    client_id: str,
    fact_type: str,
    summary: str,
    source_message_id: str,
) -> None:
    """
    Called ONLY at the moment a freelancer clicks "[Send as-is]" (or
    equivalent) in Slack for a drafted pushback -- never speculatively,
    never on every turn. Writes a structured long-term fact recording
    what was negotiated and its outcome.
    """
    append_long_term_fact(
        client_id=client_id,
        fact_type=fact_type,
        summary=summary,
        source_message_id=source_message_id,
    )


# ---------------------------------------------------------------------------
# AgentCore entrypoint
# ---------------------------------------------------------------------------

if BedrockAgentCoreApp is not None:
    app = BedrockAgentCoreApp()

    @app.entrypoint
    def invoke(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        AgentCore entrypoint. Expected payload shape:
            {
                "client_id": "...",
                "client_message": "...",
                "source_message_id": "..."
            }
        """
        payload = payload or {}
        return handle_incoming_message(
            client_id=payload["client_id"],
            client_message=payload["client_message"],
            source_message_id=payload["source_message_id"],
        )

    if __name__ == "__main__":
        app.run()
else:  # pragma: no cover
    if __name__ == "__main__":
        raise RuntimeError(
            "bedrock_agentcore is not installed; cannot start the AgentCore "
            "runtime entrypoint."
        )