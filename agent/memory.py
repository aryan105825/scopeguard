"""
agent/memory.py
------------------
AgentCore Memory read/write helpers.

Two concerns are kept strictly separate and must never be conflated:

1. SESSION MEMORY
   Live Slack thread conversational state, scoped to the CURRENT
   negotiation only. This is short-lived, per-thread context (e.g. the
   back-and-forth while drafting a pushback message) and is not a
   source of durable facts about a client.

2. LONG-TERM SEMANTIC MEMORY
   Structured, negotiated facts keyed by `client_id`, persisting across
   separate conversations. This is the durable institutional memory the
   Supervisor consults so it never re-offers something a client already
   declined, or re-litigates an already-agreed scope precedent.

Long-term facts MUST conform exactly to this schema:
    client_id, fact_type, summary, date, source_message_id
where fact_type is one of: "declined_offer", "scope_precedent",
"agreed_change".

Raw transcript text is NEVER stored as a long-term fact. Every
long-term write goes through this structured schema, populated by the
Supervisor at the moment a draft is actually sent to the client (e.g.
after a human clicks "[Send as-is]" in Slack) -- never speculatively,
never on every turn.

Long-term facts are queried once at the start of a new audit, before
any drafting begins, so the Supervisor can avoid re-offering something
already declined.
"""

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Literal, Optional

try:
    from bedrock_agentcore.memory import MemoryClient
except ImportError:  # pragma: no cover
    MemoryClient = None


FactType = Literal["declined_offer", "scope_precedent", "agreed_change"]

_ALLOWED_FACT_TYPES = {"declined_offer", "scope_precedent", "agreed_change"}

_AGENTCORE_MEMORY_ID_ENV = "AGENTCORE_MEMORY_ID"


@dataclass(frozen=True)
class LongTermFact:
    """Structured schema for a long-term negotiated fact. This is the
    ONLY shape long-term memory is allowed to store -- never raw
    transcript text."""

    client_id: str
    fact_type: FactType
    summary: str
    date: str  # ISO 8601 date string
    source_message_id: str

    def __post_init__(self):
        if self.fact_type not in _ALLOWED_FACT_TYPES:
            raise ValueError(
                f"Invalid fact_type {self.fact_type!r}; must be one of "
                f"{sorted(_ALLOWED_FACT_TYPES)}"
            )
        if not self.client_id:
            raise ValueError("client_id must be non-empty")
        if not self.summary:
            raise ValueError("summary must be non-empty")
        if not self.source_message_id:
            raise ValueError("source_message_id must be non-empty")


def _get_memory_client() -> "MemoryClient":
    if MemoryClient is None:
        raise RuntimeError(
            "bedrock_agentcore is not installed but AgentCore Memory access "
            "was requested."
        )
    memory_id = os.environ.get(_AGENTCORE_MEMORY_ID_ENV)
    if not memory_id:
        raise RuntimeError(
            f"{_AGENTCORE_MEMORY_ID_ENV} is not set in the environment."
        )
    return MemoryClient(memory_id=memory_id)


# ---------------------------------------------------------------------------
# SESSION MEMORY (live Slack thread state, current negotiation only)
# ---------------------------------------------------------------------------

def get_session_state(session_id: str) -> dict:
    """
    Retrieve the live conversational state for the current Slack thread
    negotiation. Scoped strictly to `session_id` -- this is NOT where
    durable client facts live, and it is never queried in place of
    long-term memory.
    """
    client = _get_memory_client()
    return client.get_session_state(session_id=session_id) or {}


def update_session_state(session_id: str, state: dict) -> None:
    """
    Overwrite/update the live conversational state for the current
    Slack thread negotiation. Called freely during a single
    negotiation's turns. Never used to persist facts across
    conversations -- that is exclusively long-term memory's job.
    """
    client = _get_memory_client()
    client.put_session_state(session_id=session_id, state=state)


def clear_session_state(session_id: str) -> None:
    """
    Clear session state once a negotiation thread has concluded
    (accepted, declined, or otherwise closed out).
    """
    client = _get_memory_client()
    client.delete_session_state(session_id=session_id)


# ---------------------------------------------------------------------------
# LONG-TERM SEMANTIC MEMORY (structured facts keyed by client_id)
# ---------------------------------------------------------------------------

def get_long_term_facts(client_id: str) -> List[LongTermFact]:
    """
    Query all long-term negotiated facts for a given client_id.

    This should be called ONCE at the start of a new audit, before any
    drafting begins, so the Supervisor agent can check what has already
    been declined, agreed to, or established as scope precedent for
    this client -- and avoid re-offering or re-litigating it.
    """
    client = _get_memory_client()
    raw_records = client.list_semantic_facts(namespace=f"client:{client_id}") or []

    facts: List[LongTermFact] = []
    for record in raw_records:
        facts.append(
            LongTermFact(
                client_id=record["client_id"],
                fact_type=record["fact_type"],
                summary=record["summary"],
                date=record["date"],
                source_message_id=record["source_message_id"],
            )
        )
    return facts


def append_long_term_fact(
    client_id: str,
    fact_type: FactType,
    summary: str,
    source_message_id: str,
    date: Optional[str] = None,
) -> LongTermFact:
    """
    Append a new structured long-term fact for a client.

    MUST be called only at the moment a draft is actually sent to the
    client -- e.g. after a human reviewer clicks "[Send as-is]" in
    Slack. Never called speculatively, never called on every turn, and
    never called to store raw transcript text. `summary` must be a
    concise structured summary of the negotiated outcome, not a
    transcript excerpt.
    """
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    fact = LongTermFact(
        client_id=client_id,
        fact_type=fact_type,
        summary=summary,
        date=date,
        source_message_id=source_message_id,
    )

    client = _get_memory_client()
    client.put_semantic_fact(
        namespace=f"client:{client_id}",
        fact=asdict(fact),
    )

    return fact