"""
Wait For Reply Node - Wait for webhook notification of POC reply.

This is a blocking node that waits for webhook events from the embedded
FastAPI server.
"""

import logging
from typing import Any, Optional

from mail_agent.agent.state import AgentState, get_conversation, update_conversation
from mail_agent.webhook.server import WebhookEvent, WebhookServer


logger = logging.getLogger(__name__)


# Global webhook server instance (set by main.py)
_webhook_server: Optional[WebhookServer] = None


def set_webhook_server(server: WebhookServer) -> None:
    """Set the global webhook server instance."""
    global _webhook_server
    _webhook_server = server
    logger.debug("Webhook server instance set for wait_for_reply node")


def get_webhook_server() -> WebhookServer:
    """Get the global webhook server instance."""
    if _webhook_server is None:
        raise RuntimeError("Webhook server not initialized")
    return _webhook_server


async def wait_for_reply(state: AgentState) -> dict[str, Any]:
    """
    Wait for a reply from the current POC.

    This node:
    1. Waits for a webhook event on the event queue
    2. Validates the event is from the expected POC
    3. Adds the email ID to pending_webhooks for fetch_email

    Args:
        state: Current agent state with current_poc in waiting status.

    Returns:
        State update with pending webhook event.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for wait_for_reply")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for waiting"],
        }

    logger.info(f"Waiting for reply from POC: {current_poc}")

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)

        if conversation.status != "waiting":
            logger.warning(
                f"Unexpected status for wait_for_reply: {conversation.status}"
            )

        # Get webhook server
        webhook_server = get_webhook_server()

        # Check for designated queue in state
        webhook_queue = state.get("webhook_queue")

        progress_msg = f"Waiting for reply from {current_poc}..."
        logger.info(progress_msg)

        # Wait for webhook event (no timeout - indefinite wait)
        # In production, you might want a timeout
        event: Optional[WebhookEvent] = None

        while event is None:
            # Wait for any webhook event
            if webhook_queue:
                # Use designated queue
                try:
                    event = await asyncio.wait_for(webhook_queue.get(), timeout=5.0)
                    webhook_queue.task_done()
                except asyncio.TimeoutError:
                    event = None
            else:
                # Use legacy global server wait
                event = await webhook_server.wait_for_event(timeout=5.0)

            if event is None:
                # Timeout, continue waiting
                logger.debug(f"Still waiting for reply from {current_poc}...")
                continue

            # Check if event is from expected POC
            if event.from_address.lower() != current_poc.lower():
                logger.info(
                    f"Received email from {event.from_address}, "
                    f"but waiting for {current_poc}. Ignoring."
                )
                # Store for potential other POC processing
                # For now, we ignore emails from other senders
                event = None
                continue

            logger.info(
                f"Received reply from {current_poc}: "
                f"email_id={event.email_id}, subject={event.subject}"
            )

        # Update conversation status
        conversation.status = "fetching"

        progress_msg = (
            f"Reply received from {current_poc}: '{event.subject}' "
            f"(attachments: {event.attachment_count})"
        )

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "wait_for_reply",
            "pending_webhooks": [str(event.email_id)],
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Error waiting for reply from {current_poc}: {e}"
        logger.error(error_msg)

        try:
            conversation = get_conversation(state, current_poc)
            conversation.status = "failed"
            conversation.error_message = error_msg
            return {
                "conversations": update_conversation(state, current_poc, conversation),
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
        except Exception:
            return {
                "error": error_msg,
                "current_node": "error",
                "progress_messages": [f"ERROR: {error_msg}"],
            }
