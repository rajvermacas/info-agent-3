"""Wait for reply node - async waits for webhook email notification."""

import asyncio
import logging
from typing import Optional

from mail_agent.agent.state import AgentState, ReceivedEmail

logger = logging.getLogger(__name__)


async def wait_for_reply_node(state: AgentState) -> AgentState:
    """Wait for email reply from POC.

    This node:
    1. Gets the current POC email
    2. Waits for webhook notification with new email from that POC
    3. On timeout: marks conversation as failed, moves to next POC
    4. On success: stores received email metadata and moves to fetch_email node
    5. Uses asyncio.wait_for with timeout from config

    Design:
    - Agent graph runs with polling interval
    - pending_webhooks list in state contains new webhook payloads
    - This node checks if any webhook matches the waiting POC
    - On match: records email metadata, removes from pending_webhooks
    - No match after timeout: marks as failed, proceeds

    Args:
        state: Current agent state (conversations must have POC in "waiting" status)

    Returns:
        AgentState: Updated state with received email or timeout error

    Raises:
        ValueError: If no POC is in "waiting" status
        asyncio.TimeoutError: If webhook not received within timeout
    """
    logger.info("wait_for_reply_node: Starting")

    # Validate inputs
    parsed_request = state.get("parsed_request")
    conversations = state.get("conversations", {})

    if not parsed_request:
        error_msg = "parsed_request is required in state"
        logger.error(f"wait_for_reply_node: {error_msg}")
        raise ValueError(error_msg)

    if not conversations:
        error_msg = "conversations is required in state"
        logger.error(f"wait_for_reply_node: {error_msg}")
        raise ValueError(error_msg)

    # Find POC in "waiting" status
    waiting_poc = None
    for poc_email in parsed_request["poc_emails"]:
        conv = conversations.get(poc_email, {})
        if conv.get("status") == "waiting":
            waiting_poc = poc_email
            break

    if not waiting_poc:
        error_msg = "No POC found in 'waiting' status"
        logger.error(f"wait_for_reply_node: {error_msg}")
        raise ValueError(error_msg)

    logger.info(f"wait_for_reply_node: Waiting for reply to {waiting_poc}")

    # Get timeout from settings
    from mail_agent.config import get_settings

    settings = get_settings()
    timeout_seconds = settings.webhook_wait_timeout or 300.0  # Default 5 minutes

    logger.debug(f"wait_for_reply_node: Using timeout: {timeout_seconds} seconds")

    try:
        # Wait for webhook to be received
        # The webhook server will add to pending_webhooks in state
        # We check if any webhook matches our waiting POC
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check for pending webhooks
            pending_webhooks = state.get("pending_webhooks", [])
            logger.debug(f"wait_for_reply_node: Checking {len(pending_webhooks)} pending webhooks")

            # Look for webhook matching waiting_poc
            received_email_payload = None
            for i, webhook_payload in enumerate(pending_webhooks):
                # Webhook payload: {"email_id", "from_address", "subject", ...}
                from_address = webhook_payload.get("from_address", "").lower()
                waiting_poc_lower = waiting_poc.lower()

                if from_address == waiting_poc_lower:
                    logger.info(
                        f"wait_for_reply_node: Found matching webhook from {from_address}"
                    )
                    received_email_payload = webhook_payload
                    # Remove from pending
                    pending_webhooks.pop(i)
                    break

            if received_email_payload:
                # Got a reply!
                received_email: ReceivedEmail = {
                    "email_id": str(received_email_payload.get("email_id", "")),
                    "from_address": received_email_payload.get("from_address", ""),
                    "subject": received_email_payload.get("subject", ""),
                    "received_at": received_email_payload.get("received_at", ""),
                    "has_attachment": received_email_payload.get("has_attachments", False),
                    "attachment_content": None,
                }

                logger.info(
                    f"wait_for_reply_node: Received email from {from_address}: "
                    f"subject={received_email['subject']}"
                )

                # Store in conversation
                conversation = conversations[waiting_poc]
                received_emails = conversation.get("received_emails", [])
                received_emails.append(received_email)
                conversation["received_emails"] = received_emails
                conversation["status"] = "validating"

                conversations[waiting_poc] = conversation

                # Update state
                state["conversations"] = conversations
                state["pending_webhooks"] = pending_webhooks
                state["_received_email"] = received_email  # Temporary for fetch_email node
                state["current_node"] = "wait_for_reply"
                state["progress_messages"].append(f"Received reply from {waiting_poc}")

                logger.info("wait_for_reply_node: Completed successfully")

                return state

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout_seconds:
                logger.warning(
                    f"wait_for_reply_node: Timeout waiting for reply from {waiting_poc} "
                    f"after {elapsed:.1f}s"
                )

                # Mark as failed
                conversation = conversations[waiting_poc]
                conversation["status"] = "failed"
                conversation["final_result"] = "failed_timeout"
                conversation["error"] = "No reply received within timeout"
                conversations[waiting_poc] = conversation

                state["conversations"] = conversations
                state["current_node"] = "wait_for_reply"
                state["progress_messages"].append(f"Timeout waiting for reply from {waiting_poc}")

                logger.info("wait_for_reply_node: Completed with timeout")

                return state

            # Wait before next check (poll every 2 seconds)
            await asyncio.sleep(2)

    except Exception as e:
        error_msg = f"Unexpected error waiting for reply: {str(e)}"
        logger.error(f"wait_for_reply_node: {error_msg}")
        raise
