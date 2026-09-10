"""
slack_app/blocks.py
----------------------
Block Kit template functions for ScopeGuard's Slack surfaces.

This file is PURE template/formatting logic. It takes already-decided
values (draft text, cited clause, original message) produced upstream
by agent/scopeguard_main.py and renders them as Block Kit JSON. It does
NOT decide whether a card should be shown, and it never calls into the
Auditor, guardrails, or memory modules.

Two distinct card types are provided:

1. The four-element review card (build_review_card), used ONLY for the
   "draft_pushback" routing outcome, where a client-facing draft
   genuinely exists. It contains exactly four elements:
     - the client's raw request
     - the exact SOW clause the Auditor cited
     - the drafted reply
     - three action buttons: [Send as-is], [Edit Draft],
       [Discard & Handle Manually]

2. A distinct, simpler ambiguous/freelancer-ping notification
   (build_ambiguous_ping), used for the "ping_freelancer" routing
   outcome. It must NOT reuse the four-element review card, since no
   client-facing draft exists in that case.
"""

from typing import Any, Dict, List


def build_review_card(
    client_request: str,
    cited_clause: str,
    drafted_reply: str,
    action_callback_id_prefix: str = "scopeguard_review",
) -> List[Dict[str, Any]]:
    """
    Build the four-element freelancer-facing review card for a
    "draft_pushback" routing outcome.

    Elements, exactly:
      1. The client's raw request.
      2. The exact SOW clause the Auditor cited (verbatim).
      3. The drafted reply.
      4. Three action buttons: [Send as-is], [Edit Draft],
         [Discard & Handle Manually].
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "ScopeGuard: Possible Out-of-Scope Request",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Client's request:*\n>{client_request}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Cited SOW clause:*\n>{cited_clause}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Drafted reply:*\n{drafted_reply}",
            },
        },
        {
            "type": "actions",
            "block_id": f"{action_callback_id_prefix}_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Send as-is",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": f"{action_callback_id_prefix}_send_as_is",
                    "value": "send_as_is",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Edit Draft",
                        "emoji": True,
                    },
                    "action_id": f"{action_callback_id_prefix}_edit_draft",
                    "value": "edit_draft",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Discard & Handle Manually",
                        "emoji": True,
                    },
                    "style": "danger",
                    "action_id": f"{action_callback_id_prefix}_discard",
                    "value": "discard_handle_manually",
                },
            ],
        },
    ]


def build_ambiguous_ping(
    client_request: str,
    reasoning: str,
    action_callback_id_prefix: str = "scopeguard_ambiguous",
) -> List[Dict[str, Any]]:
    """
    Build the distinct, simpler notification used for the "ambiguous"
    / ping_freelancer routing outcome. No client-facing draft exists in
    this case, so this must NOT reuse the four-element review card --
    there is nothing to show as a "drafted reply" and no verified
    citation to display.
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "ScopeGuard: Needs Your Judgment",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*Client's request:*\n>{client_request}\n\n"
                    "I couldn't confidently verify this against the SOW "
                    "(low confidence or no clean citation match), so I'm "
                    "flagging it for you instead of drafting anything."
                ),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_Notes: {reasoning}_",
                }
            ],
        },
        {
            "type": "actions",
            "block_id": f"{action_callback_id_prefix}_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Mark Handled",
                        "emoji": True,
                    },
                    "action_id": f"{action_callback_id_prefix}_mark_handled",
                    "value": "mark_handled",
                }
            ],
        },
    ]