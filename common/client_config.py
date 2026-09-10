"""
common/client_config.py
-------------------------
Single source of truth for client onboarding, shared by both
integration points that previously hardcoded their own empty,
comment-only Python dicts requiring a source edit + redeploy to
onboard a real client:

  - server/mcp_sow_retriever.py  (client_id -> SOW source)
  - slack_app/app.py             (Slack channel_id -> client_id)

Backed by a JSON config file, so onboarding a new client is a config
edit (or a CLI command -- see client_admin.py) rather than a code
change. The file is re-read whenever it changes (mtime-checked, cached
otherwise) so a running process picks up new clients without a
restart.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("scopeguard.client_config")

_CONFIG_PATH_ENV = "SCOPEGUARD_CLIENTS_CONFIG_PATH"
_DEFAULT_RELATIVE_PATH = Path("config") / "clients.json"
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Added "file" to support the local fallback sandbox
_VALID_SOW_SOURCE_TYPES = {"notion", "drive", "file"}

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[float] = None
_cache_path: Optional[Path] = None


def config_path() -> Path:
    override = os.environ.get(_CONFIG_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return _REPO_ROOT / _DEFAULT_RELATIVE_PATH


def _empty_config() -> Dict[str, Any]:
    return {"clients": {}}


def _validate(raw: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("clients"), dict):
        raise ValueError(
            "Client config must be a JSON object of the form "
            '{"clients": {"<client_id>": {...}, ...}}'
        )
    for client_id, entry in raw["clients"].items():
        if not isinstance(entry, dict):
            raise ValueError(f"Config entry for client_id {client_id!r} must be an object")
        sow_source = entry.get("sow_source")
        if sow_source is not None:
            if not isinstance(sow_source, dict) or "type" not in sow_source:
                raise ValueError(
                    f"sow_source for client_id {client_id!r} must be an object "
                    'with a "type" field'
                )
            if sow_source["type"] not in _VALID_SOW_SOURCE_TYPES:
                raise ValueError(
                    f"sow_source type {sow_source['type']!r} for client_id "
                    f"{client_id!r} must be one of {sorted(_VALID_SOW_SOURCE_TYPES)}"
                )
    return raw


def _load_from_disk(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_config()
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return _validate(raw)


def _config(force_reload: bool = False) -> Dict[str, Any]:
    global _cache, _cache_mtime, _cache_path
    path = config_path()
    with _lock:
        mtime = path.stat().st_mtime if path.exists() else None
        stale = (
            force_reload
            or _cache is None
            or _cache_path != path
            or _cache_mtime != mtime
        )
        if stale:
            _cache = _load_from_disk(path)
            _cache_mtime = mtime
            _cache_path = path
        return _cache


def _save(raw: Dict[str, Any]) -> None:
    global _cache, _cache_mtime, _cache_path
    raw = _validate(raw)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_path.replace(path)

    with _lock:
        _cache = raw
        _cache_mtime = path.stat().st_mtime
        _cache_path = path


def list_client_ids() -> list:
    return list(_config()["clients"].keys())


def get_sow_source(client_id: str) -> Optional[Dict[str, str]]:
    entry = _config()["clients"].get(client_id)
    if entry is None:
        return None
    return entry.get("sow_source")


def get_channel_map() -> Dict[str, str]:
    channel_map = {}
    for client_id, entry in _config()["clients"].items():
        channel_id = entry.get("slack_channel_id")
        if channel_id:
            channel_map[channel_id] = client_id
    return channel_map


def get_client_id_for_channel(channel_id: str) -> Optional[str]:
    return get_channel_map().get(channel_id)


def upsert_client(
    client_id: str,
    sow_source: Optional[Dict[str, str]] = None,
    slack_channel_id: Optional[str] = None,
) -> None:
    if not client_id:
        raise ValueError("client_id must be non-empty")
    if sow_source is not None and sow_source.get("type") not in _VALID_SOW_SOURCE_TYPES:
        raise ValueError(
            f'sow_source type must be one of {sorted(_VALID_SOW_SOURCE_TYPES)}'
        )

    raw = _config(force_reload=True)
    entry = dict(raw["clients"].get(client_id, {}))

    if sow_source is not None:
        entry["sow_source"] = sow_source
    if slack_channel_id is not None:
        entry["slack_channel_id"] = slack_channel_id

    raw = {"clients": {**raw["clients"], client_id: entry}}
    _save(raw)
    logger.info("Onboarded/updated client_id=%s", client_id)


def remove_client(client_id: str) -> bool:
    raw = _config(force_reload=True)
    if client_id not in raw["clients"]:
        return False
    remaining = {k: v for k, v in raw["clients"].items() if k != client_id}
    _save({"clients": remaining})
    logger.info("Removed client_id=%s", client_id)
    return True