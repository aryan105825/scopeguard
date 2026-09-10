"""
slack_app/app.py
-------------------
Slack Bolt app (slack_bolt) using the Events API.

Listens ONLY in channels/DMs the freelancer has explicitly designated
as client channels via the dynamic client config -- not indiscriminately
across every channel the bot happens to belong to.

On each qualifying message:
  1. Resolve client_id from the channel -> client mapping.
  2. Call the Supervisor pipeline in agent/scopeguard_main.py.
  3. Post the appropriate Slack surface:
       - "draft_pushback" -> the four-element review card
         (slack_app/blocks.py: build_review_card)
       - "ping_freelancer" -> the simpler ambiguous notification
         (slack_app/blocks.py: build_ambiguous_ping)
       - "silent_log" -> no Slack post at all.

[Send as-is] posts the draft directly into whatever channel the client
actually messaged on. A more general Slack Connect or email-out send
path is explicitly out of scope for this v1 demo and is not built here.

NON-GOAL, STATED EXPLICITLY: this file does not and must not add any
email-based message intake. V1 is Slack-only. That limitation is
deliberate, not an oversight, and must not be "fixed" here.
"""

import os
import logging
from typing import Any, Dict, Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from agent.scopeguard_main import handle_incoming_message, record_sent_draft
from slack_app.blocks import build_review_card, build_ambiguous_ping
from common import client_config
from dotenv import load_dotenv
load_dotenv()
logger = logging.getLogger("scopeguard.slack_app")

# In-memory store of pending drafts, keyed by the Slack message timestamp
# of the review card itself, so button handlers can retrieve the full
# draft context. A production deployment would back this with AgentCore
# session memory instead of a process-local dict.
_PENDING_DRAFTS: Dict[str, Dict[str, Any]] = {}


app = App(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)


def _resolve_client_id(channel_id: str) -> Optional[str]:
    """Return the client_id for a designated client channel, or None if
    this channel is not one the freelancer has configured ScopeGuard
    for."""
    return client_config.get_client_id_for_channel(channel_id)


@app.event("message")
def handle_message_events(event: Dict[str, Any], say, logger=logger):
    """
    Handle inbound Slack message events, restricted to designated
    client channels only.
    """
    channel_id = event.get("channel")
    client_id = _resolve_client_id(channel_id)

    if client_id is None:
        # Not a designated client channel -- ignore entirely. ScopeGuard
        # does not act on arbitrary channels the bot happens to be in.
        return

    # Ignore bot's own messages, message edits/deletes, thread broadcasts
    # of subtypes we don't want to treat as new client requests, etc.
    if event.get("subtype") is not None:
        return
    if event.get("bot_id") is not None:
        return

    client_message = event.get("text", "")
    source_message_id = event.get("ts")

    if not client_message.strip():
        return

    result = handle_incoming_message(
        client_id=client_id,
        client_message=client_message,
        source_message_id=source_message_id,
    )

    action = result["action"]

    if action == "silent_log":
        logger.info(
            "ScopeGuard: silent_log for client_id=%s verdict=%s",
            client_id,
            result["verdict"],
        )
        return

    if action == "ping_freelancer":
        blocks = build_ambiguous_ping(
            client_request=client_message,
            reasoning=result.get("reasoning", ""),
        )
        say(
            channel=channel_id,
            text="ScopeGuard needs your judgment on a client message.",
            blocks=blocks,
            thread_ts=source_message_id,
        )
        return

    if action == "draft_pushback":
        blocks = build_review_card(
            client_request=client_message,
            cited_clause=result["cited_clause"],
            drafted_reply=result["client_facing_draft"],
        )
        post_response = say(
            channel=channel_id,
            text="ScopeGuard flagged a possible out-of-scope request.",
            blocks=blocks,
            thread_ts=source_message_id,
        )

        card_ts = post_response.get("ts")
        if card_ts:
            _PENDING_DRAFTS[card_ts] = {
                "client_id": client_id,
                "channel_id": channel_id,
                "client_message": client_message,
                "drafted_reply": result["client_facing_draft"],
                "cited_clause": result["cited_clause"],
                "source_message_id": source_message_id,
            }
        return

    logger.warning("ScopeGuard: unrecognized action %r from pipeline", action)


@app.action("scopeguard_review_send_as_is")
def handle_send_as_is(ack, body, client, logger=logger):
    """
    [Send as-is] handler.

    For this v1 demo, this posts the draft directly into whatever
    channel the client actually messaged on -- the same channel the
    review card itself was posted in. A more general Slack Connect or
    email-out send path is explicitly out of scope and is not built
    here.
    """
    ack()

    card_ts = body["message"]["ts"]
    pending = _PENDING_DRAFTS.get(card_ts)
    if pending is None:
        logger.warning(
            "ScopeGuard: no pending draft found for card_ts=%s", card_ts
        )
        return

    channel_id = pending["channel_id"]
    drafted_reply = pending["drafted_reply"]

    client.chat_postMessage(
        channel=channel_id,
        text=drafted_reply,
        thread_ts=pending["source_message_id"],
    )

    # Record the negotiated outcome in long-term memory now that the
    # draft has actually been sent -- never speculatively before this
    # point.
    record_sent_draft(
        client_id=pending["client_id"],
        fact_type="declined_offer",
        summary=(
            f"Pushed back on out-of-scope request: "
            f"{pending['client_message'][:200]}"
        ),
        source_message_id=pending["source_message_id"],
    )

    client.chat_update(
        channel=body["channel"]["id"],
        ts=card_ts,
        text="Sent to client. ✅",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Sent to client.* ✅",
                },
            }
        ],
    )

    _PENDING_DRAFTS.pop(card_ts, None)


@app.action("scopeguard_review_edit_draft")
def handle_edit_draft(ack, body, logger=logger):
    """
    [Edit Draft] handler. For v1, this simply acknowledges and lets the
    freelancer edit/send manually in-thread; a richer modal-based editor
    is a future enhancement, not part of this file's scope.
    """
    ack()
    logger.info("ScopeGuard: Edit Draft clicked for card_ts=%s", body["message"]["ts"])


@app.action("scopeguard_review_discard")
def handle_discard(ack, body, client, logger=logger):
    """[Discard & Handle Manually] handler. No message is sent; no
    long-term fact is recorded, since nothing was actually negotiated
    or sent."""
    ack()

    card_ts = body["message"]["ts"]
    _PENDING_DRAFTS.pop(card_ts, None)

    client.chat_update(
        channel=body["channel"]["id"],
        ts=card_ts,
        text="Discarded -- handling manually.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Discarded.* You're handling this one manually.",
                },
            }
        ],
    )


@app.action("scopeguard_ambiguous_mark_handled")
def handle_mark_ambiguous_handled(ack, body, client, logger=logger):
    """Freelancer acknowledges an ambiguous-case ping as handled."""
    ack()

    client.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text="Marked handled.",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Marked handled.*",
                },
            }
        ],
    )


if __name__ == "__main__":
    app_token = os.environ.get("SLACK_APP_TOKEN")
    if app_token:
        SocketModeHandler(app, app_token).start()
    else:
        app.start(port=int(os.environ.get("PORT", 3000)))