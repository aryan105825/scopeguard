"""
server/mcp_sow_retriever.py
-------------------------
Narrow FastMCP server acting as ScopeGuard's enterprise-data boundary.

Exposes exactly two tools:
    - get_active_sow(client_id: str) -> str
    - list_active_clients() -> list[str]

This server performs RETRIEVAL ONLY. It never reasons about, scores, or
drafts anything related to scope. It deliberately does NOT expose any
clause-search or chunked-retrieval tool (e.g. no `search_sow_clause`):
the Auditor sub-agent is designed to reason over the full SOW text in a
single pass, not over retrieved snippets. Do not add such a tool here,
even if it seems convenient.

All credentials are loaded from environment variables. Nothing is
hardcoded.
"""

import os
import re
import io
import sys
from pathlib import Path
from fastmcp import FastMCP

# Allow running this directly while finding the `common` package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import client_config

try:
    from notion_client import Client as NotionClient
except ImportError:  # pragma: no cover
    NotionClient = None

try:
    from googleapiclient.discovery import build as google_build
    from google.oauth2 import service_account
except ImportError:  # pragma: no cover
    google_build = None
    service_account = None

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


mcp = FastMCP("scopeguard-sow-retriever")

_NOTION_API_KEY_ENV = "NOTION_API_KEY"
_GOOGLE_CREDS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
_GOOGLE_DRIVE_FOLDER_ENV = "GOOGLE_DRIVE_SOW_FOLDER_ID"


def _get_notion_client():
    if NotionClient is None:
        raise RuntimeError(
            "notion-client package is not installed but a Notion SOW source "
            "was requested."
        )
    api_key = os.environ.get(_NOTION_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(
            f"{_NOTION_API_KEY_ENV} is not set in the environment."
        )
    return NotionClient(auth=api_key)


def _get_drive_service():
    if google_build is None or service_account is None:
        raise RuntimeError(
            "google-api-python-client / google-auth are not installed but "
            "a Drive SOW source was requested."
        )
    creds_path = os.environ.get(_GOOGLE_CREDS_ENV)
    if not creds_path:
        raise RuntimeError(
            f"{_GOOGLE_CREDS_ENV} is not set in the environment."
        )
    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )
    return google_build("drive", "v3", credentials=credentials)


def _notion_blocks_to_text(blocks) -> str:
    """Strip Notion block formatting down to plain text."""
    lines = []
    for block in blocks:
        block_type = block.get("type")
        content = block.get(block_type, {})
        rich_text = content.get("rich_text", []) if isinstance(content, dict) else []
        text_fragments = [
            rt.get("plain_text", "") for rt in rich_text if isinstance(rt, dict)
        ]
        line = "".join(text_fragments).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _fetch_notion_sow(page_id: str) -> str:
    client = _get_notion_client()
    all_blocks = []
    cursor = None
    while True:
        kwargs = {"block_id": page_id}
        if cursor:
            kwargs["start_cursor"] = cursor
        response = client.blocks.children.list(**kwargs)
        all_blocks.extend(response.get("results", []))
        if response.get("has_more"):
            cursor = response.get("next_cursor")
        else:
            break
    return _notion_blocks_to_text(all_blocks)


def _pdf_bytes_to_text(pdf_bytes: bytes) -> str:
    if PdfReader is None:
        raise RuntimeError(
            "pypdf is not installed but a Drive-hosted PDF SOW was requested."
        )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw_pages = [page.extract_text() or "" for page in reader.pages]
    raw_text = "\n".join(raw_pages)
    return _normalize_pdf_text(raw_text)


def _normalize_pdf_text(raw_text: str) -> str:
    """Strip common PDF layout artifacts (hyphenated line breaks, repeated
    whitespace, page-number cruft) down to clean plain text."""
    text = re.sub(r"-\n(?=\w)", "", raw_text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def _fetch_drive_sow(file_id: str) -> str:
    service = _get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloaded = request.execute()
    if isinstance(downloaded, bytes):
        buffer.write(downloaded)
    else:
        buffer.write(bytes(downloaded))
    buffer.seek(0)
    return _pdf_bytes_to_text(buffer.read())


def _fetch_local_file(file_path: str) -> str:
    """Fetch SOW from a local text file (for zero-cost local sandbox/demo)."""
    path = Path(file_path)
    if not path.is_absolute():
        # Resolve relative to the repository root
        path = Path(__file__).resolve().parent.parent / file_path
    if not path.exists():
        raise RuntimeError(f"Local file not found: {path}")
    return path.read_text(encoding="utf-8")


@mcp.tool()
def get_active_sow(client_id: str) -> str:
    """
    Retrieve the full, normalized plain-text Statement of Work for the
    given client_id. Looks up the configured source (Notion page,
    Drive-hosted PDF, or local file), fetches it, and strips formatting artifacts.

    Returns the complete SOW text in one pass — no chunking, no search.
    """
    source = client_config.get_sow_source(client_id)
    if source is None:
        raise ValueError(
            f"No active SOW configured for client_id: {client_id!r}. Onboard "
            f"it first, e.g.: python -m common.client_admin add --client-id "
            f"{client_id} --sow-type file --sow-ref <file-path>"
        )

    source_type = source.get("type")
    if source_type == "notion":
        return _fetch_notion_sow(source["page_id"])
    elif source_type == "drive":
        return _fetch_drive_sow(source["file_id"])
    elif source_type == "file":
        return _fetch_local_file(source["file_path"])
    else:
        raise ValueError(
            f"Unknown SOW source type {source_type!r} for client_id: {client_id!r}"
        )


@mcp.tool()
def list_active_clients() -> list[str]:
    """
    List all client_ids with an active SOW source configured.
    Intended for setup/debugging only.
    """
    return client_config.list_client_ids()


if __name__ == "__main__":
    mcp.run()