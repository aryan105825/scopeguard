"""
agent/memory.py
------------------
AgentCore Memory read/write helpers with Dual-Stack Local Fallback.
"""

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List, Literal, Optional

try:
    from bedrock_agentcore.memory import MemoryClient
except ImportError:  # pragma: no cover
    MemoryClient = None

from agent import local_memory

FactType = Literal["declined_offer", "scope_precedent", "agreed_change"]

_ALLOWED_FACT_TYPES = {"declined_offer", "scope_precedent", "agreed_change"}
_AGENTCORE_MEMORY_ID_ENV = "AGENTCORE_MEMORY_ID"


@dataclass(frozen=True)
class LongTermFact:
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


def _is_agentcore_configured() -> bool:
    mode = os.environ.get("SCOPEGUARD_MODE", "aws").lower()
    return mode != "local" and MemoryClient is not None and bool(os.environ.get(_AGENTCORE_MEMORY_ID_ENV))


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
    if not _is_agentcore_configured():
        return local_memory.local_get_session_state(session_id)
        
    client = _get_memory_client()
    return client.get_session_state(session_id=session_id) or {}


def update_session_state(session_id: str, state: dict) -> None:
    if not _is_agentcore_configured():
        local_memory.local_update_session_state(session_id, state)
        return
        
    client = _get_memory_client()
    client.put_session_state(session_id=session_id, state=state)


def clear_session_state(session_id: str) -> None:
    if not _is_agentcore_configured():
        local_memory.local_clear_session_state(session_id)
        return
        
    client = _get_memory_client()
    client.delete_session_state(session_id=session_id)


# ---------------------------------------------------------------------------
# LONG-TERM SEMANTIC MEMORY (structured facts keyed by client_id)
# ---------------------------------------------------------------------------

def get_long_term_facts(client_id: str) -> List[LongTermFact]:
    if not _is_agentcore_configured():
        records = local_memory.local_get_long_term_facts(client_id)
        return [LongTermFact(**r) for r in records]

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
    if date is None:
        date = datetime.now(timezone.utc).date().isoformat()

    fact = LongTermFact(
        client_id=client_id,
        fact_type=fact_type,
        summary=summary,
        date=date,
        source_message_id=source_message_id,
    )

    if not _is_agentcore_configured():
        local_memory.local_append_long_term_fact(client_id, asdict(fact))
        return fact

    client = _get_memory_client()
    client.put_semantic_fact(
        namespace=f"client:{client_id}",
        fact=asdict(fact),
    )

    return fact