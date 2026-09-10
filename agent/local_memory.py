"""
agent/local_memory.py
---------------------
Local JSON-based fallback for AgentCore Memory.
"""
import json
import os
import threading
from pathlib import Path

_LOCAL_STATE_DIR = Path(os.environ.get("SCOPEGUARD_LOCAL_STATE_DIR", ".scopeguard_state"))
_MEMORY_FILE = _LOCAL_STATE_DIR / "agent_memory.json"
_lock = threading.Lock()

def _read_state():
    if not _MEMORY_FILE.exists():
        return {"sessions": {}, "facts": {}, "digest_events": []}
    with _MEMORY_FILE.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {"sessions": {}, "facts": {}, "digest_events": []}

def _write_state(state):
    _LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    with _MEMORY_FILE.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def local_get_session_state(session_id: str) -> dict:
    with _lock:
        return _read_state()["sessions"].get(session_id, {})

def local_update_session_state(session_id: str, session_data: dict) -> None:
    with _lock:
        state = _read_state()
        state["sessions"][session_id] = session_data
        _write_state(state)

def local_clear_session_state(session_id: str) -> None:
    with _lock:
        state = _read_state()
        state["sessions"].pop(session_id, None)
        _write_state(state)

def local_get_long_term_facts(client_id: str) -> list:
    with _lock:
        return _read_state()["facts"].get(client_id, [])

def local_append_long_term_fact(client_id: str, fact: dict) -> None:
    with _lock:
        state = _read_state()
        if client_id not in state["facts"]:
            state["facts"][client_id] = []
        state["facts"][client_id].append(fact)
        _write_state(state)

def local_record_digest_event(session_id: str, event: dict) -> None:
    with _lock:
        state = _read_state()
        event["_session_id"] = session_id
        state["digest_events"].append(event)
        _write_state(state)

def local_get_digest_events(session_id: str) -> list:
    with _lock:
        state = _read_state()
        return [e for e in state["digest_events"] if e.get("_session_id") == session_id]