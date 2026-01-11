"""
Wait For Reply Node - Interrupt-based waiting for POC reply.

This node uses LangGraph's interrupt() function to pause execution and
save state to a checkpoint. The graph can be resumed later when a webhook
arrives with the POC's reply.

Supports two modes:
1. A2A mode (non-blocking): Uses interrupt() to checkpoint and return control
2. CLI mode (blocking): Uses WebhookServer queue for direct waiting
"""

import asyncio
import logging
from typing import Any, Optional

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from mail_agent.agent.state import AgentState, get_conversation, update_conversation
from mail_agent.webhook.server import WebhookEvent, WebhookServer


logger = logging.getLogger(__name__)


# Global webhook server instance (set by main.py or A2A server)
_webhook_server: Optional[WebhookServer] = None

# Flag to indicate A2A mode (non-blocking with interrupts)
_a2a_mode: bool = False


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


def set_a2a_mode(enabled: bool) -> None:
    """
    Enable or disable A2A mode (non-blocking with interrupts).

    Args:
        enabled: True for A2A mode (interrupt), False for CLI mode (blocking).
    """
    global _a2a_mode
    _a2a_mode = enabled
    logger.info(f"A2A mode {'enabled' if enabled else 'disabled'} for wait_for_reply")


def is_a2a_mode() -> bool:
    """Check if A2A mode is enabled."""
    return _a2a_mode


async def wait_for_reply(state: AgentState) -> dict[str, Any]:
    """
    Wait for a reply from the current POC.

    Behavior depends on mode:

    A2A Mode (non-blocking):
        - Calls interrupt() to save checkpoint and return control to caller
        - Graph execution pauses and SSE stream closes
        - Webhook triggers resumption with email_id
        - After resume, returns email_id from interrupt data

    CLI Mode (blocking):
        - Waits directly on WebhookServer's event queue
        - Returns when email arrives from expected POC

    Args:
        state: Current agent state with current_poc in waiting status.

    Returns:
        State update with pending webhook event (email_id).
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for wait_for_reply")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for waiting"],
        }

    task_id = state.get("task_id")
    logger.info(
        f"wait_for_reply: POC={current_poc}, mode={'A2A' if _a2a_mode else 'CLI'}, "
        f"task_id={task_id}"
    )

    try:
        # Get conversation state
        conversation = get_conversation(state, current_poc)

        if conversation.status != "waiting":
            logger.warning(
                f"Unexpected status for wait_for_reply: {conversation.status}"
            )

        progress_msg = f"Waiting for reply from {current_poc}..."
        logger.info(progress_msg)

        if _a2a_mode:
            # A2A MODE: Use interrupt for non-blocking checkpoint
            email_id = await _wait_for_reply_interrupt_mode(
                state, current_poc, task_id
            )
        else:
            # CLI MODE: Use blocking queue wait
            email_id = await _wait_for_reply_cli_mode(current_poc)

        # Update conversation status
        conversation.status = "fetching"

        progress_msg = f"Reply received from {current_poc} (email_id: {email_id})"
        logger.info(progress_msg)

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "wait_for_reply",
            "pending_webhooks": [str(email_id)],
            "progress_messages": [progress_msg],
        }

    except GraphInterrupt:
        # Re-raise GraphInterrupt to allow LangGraph to handle it properly
        # The graph engine catches this and saves checkpoint for resumption
        logger.debug(
            f"GraphInterrupt raised for {current_poc}, propagating to graph engine"
        )
        raise

    except asyncio.TimeoutError:
        error_msg = f"Timeout waiting for reply from {current_poc}"
        logger.error(error_msg)
        return _build_error_response(state, current_poc, error_msg)

    except Exception as e:
        error_msg = f"Error waiting for reply from {current_poc}: {e}"
        logger.error(error_msg)
        return _build_error_response(state, current_poc, error_msg)


async def _wait_for_reply_interrupt_mode(
    state: AgentState,
    poc_email: str,
    task_id: Optional[str],
) -> str:
    """
    Wait for reply using LangGraph interrupt (A2A non-blocking mode).

    This function:
    1. Prepares interrupt payload with context for resumption
    2. Calls interrupt() which saves checkpoint and returns control
    3. After resume, extracts email_id from the resumed data

    Args:
        state: Current agent state.
        poc_email: POC email address waiting for.
        task_id: A2A task identifier.

    Returns:
        Email ID from the webhook that triggered resumption.
    """
    logger.info(f"A2A mode: Preparing interrupt for task {task_id}, POC {poc_email}")

    # Get sent email info from conversation
    conversation = get_conversation(state, poc_email)
    sent_email_id = None
    if conversation.sent_emails:
        sent_email_id = str(conversation.sent_emails[-1].email_id)

    # Prepare interrupt payload
    # This data is passed to TaskManager for suspension tracking
    interrupt_payload = {
        "reason": "waiting_for_reply",
        "poc_email": poc_email,
        "task_id": task_id,
        "sent_email_id": sent_email_id,
        "attempt": conversation.attempt_count,
    }

    logger.info(f"A2A mode: Calling interrupt() with payload: {interrupt_payload}")

    # Call interrupt - this saves checkpoint and returns control to executor
    # When resumed, interrupt() returns with the resume data (webhook payload)
    resume_data = interrupt(interrupt_payload)

    # After resume - extract email_id from webhook data
    email_id = resume_data.get("email_id")
    if not email_id:
        logger.error(f"Resume data missing email_id: {resume_data}")
        raise ValueError("Resume data missing email_id")

    logger.info(
        f"A2A mode: Task {task_id} resumed with email_id={email_id} from {poc_email}"
    )
    return email_id


async def _wait_for_reply_cli_mode(poc_email: str) -> str:
    """
    Wait for reply in CLI mode using WebhookServer's event queue.

    This is the blocking mode used for CLI execution where the graph
    runs synchronously until completion.

    Args:
        poc_email: The POC email address to wait for.

    Returns:
        The email_id from the received event.
    """
    webhook_server = get_webhook_server()

    event: Optional[WebhookEvent] = None

    while event is None:
        # Wait for any webhook event
        event = await webhook_server.wait_for_event(timeout=5.0)

        if event is None:
            # Timeout, continue waiting
            logger.debug(f"Still waiting for reply from {poc_email}...")
            continue

        # Check if event is from expected POC
        if event.from_address.lower() != poc_email.lower():
            logger.info(
                f"Received email from {event.from_address}, "
                f"but waiting for {poc_email}. Ignoring."
            )
            # For now, we ignore emails from other senders
            event = None
            continue

        logger.info(
            f"CLI mode: Received reply from {poc_email}: "
            f"email_id={event.email_id}, subject={event.subject}"
        )

    return str(event.email_id)


def _build_error_response(
    state: AgentState, poc_email: str, error_msg: str
) -> dict[str, Any]:
    """Build error response for wait_for_reply failures."""
    try:
        conversation = get_conversation(state, poc_email)
        conversation.status = "failed"
        conversation.error_message = error_msg
        return {
            "conversations": update_conversation(state, poc_email, conversation),
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
    except Exception:
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
