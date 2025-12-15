"""
Wait For Reply Node - Wait for webhook notification of POC reply.

This is a blocking node that waits for webhook events from the embedded
FastAPI server. Supports both CLI mode (single queue) and A2A mode
(task-aware routing via TaskRouter).
"""

import asyncio
import logging
from typing import Any, Optional

from mail_agent.agent.state import AgentState, get_conversation, update_conversation
from mail_agent.webhook.server import WebhookEvent, WebhookServer
from mail_agent.webhook.router import TaskRouter


logger = logging.getLogger(__name__)


# Global webhook server instance (set by main.py or A2A server)
_webhook_server: Optional[WebhookServer] = None

# Global task router instance (set by A2A server, None for CLI mode)
_task_router: Optional[TaskRouter] = None


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


def set_task_router(router: Optional[TaskRouter]) -> None:
    """
    Set the global task router instance for A2A mode.

    Args:
        router: TaskRouter instance for A2A mode, or None to disable A2A routing.
    """
    global _task_router
    _task_router = router
    logger.debug(f"TaskRouter {'set' if router else 'cleared'} for wait_for_reply node")


def get_task_router() -> Optional[TaskRouter]:
    """Get the global task router instance if configured."""
    return _task_router


async def wait_for_reply(state: AgentState) -> dict[str, Any]:
    """
    Wait for a reply from the current POC.

    This node supports two modes:
    1. CLI mode: Uses single shared event queue from WebhookServer
    2. A2A mode: Uses TaskRouter for task-specific event routing

    In A2A mode, the node registers with TaskRouter before waiting and
    unregisters after receiving the event (or on error).

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

    # Check for A2A mode (task_id present and TaskRouter configured)
    task_id = state.get("task_id")
    task_router = get_task_router()
    is_a2a_mode = task_id is not None and task_router is not None

    logger.info(
        f"Waiting for reply from POC: {current_poc} "
        f"(mode={'A2A' if is_a2a_mode else 'CLI'}, task_id={task_id})"
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

        if is_a2a_mode:
            # A2A MODE: Use TaskRouter for task-specific routing
            email_id = await _wait_for_reply_a2a_mode(
                task_id, current_poc, task_router
            )
        else:
            # CLI MODE: Use original single-queue behavior
            email_id = await _wait_for_reply_cli_mode(current_poc)

        # Update conversation status
        conversation.status = "fetching"

        progress_msg = f"Reply received from {current_poc} (email_id: {email_id})"

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "wait_for_reply",
            "pending_webhooks": [str(email_id)],
            "progress_messages": [progress_msg],
        }

    except asyncio.TimeoutError:
        error_msg = f"Timeout waiting for reply from {current_poc}"
        logger.error(error_msg)
        return _build_error_response(state, current_poc, error_msg)

    except Exception as e:
        error_msg = f"Error waiting for reply from {current_poc}: {e}"
        logger.error(error_msg)
        return _build_error_response(state, current_poc, error_msg)


async def _wait_for_reply_a2a_mode(
    task_id: str, poc_email: str, task_router: TaskRouter
) -> str:
    """
    Wait for reply in A2A mode using TaskRouter.

    Args:
        task_id: The A2A task identifier.
        poc_email: The POC email address to wait for.
        task_router: The TaskRouter instance.

    Returns:
        The email_id from the received event.

    Raises:
        asyncio.TimeoutError: If no reply received within timeout.
        Exception: For other errors.
    """
    logger.info(f"A2A mode: Registering task {task_id} for POC {poc_email}")

    try:
        # Register with TaskRouter to receive events from this POC
        await task_router.register(task_id, poc_email)
        logger.debug(f"Task {task_id} registered with TaskRouter for {poc_email}")

        # Wait for event from TaskRouter (5 minute timeout)
        # The TaskRouter will route webhook events to our task-specific queue
        event = await task_router.wait_for_event(task_id, timeout=300.0)

        email_id = event.get("email_id")
        logger.info(
            f"A2A mode: Task {task_id} received reply from {poc_email}, "
            f"email_id={email_id}"
        )
        return email_id

    finally:
        # Always unregister, even on error
        try:
            await task_router.unregister(task_id, poc_email)
            logger.debug(f"Task {task_id} unregistered from TaskRouter")
        except Exception as e:
            logger.warning(f"Failed to unregister task {task_id}: {e}")


async def _wait_for_reply_cli_mode(poc_email: str) -> str:
    """
    Wait for reply in CLI mode using WebhookServer's event queue.

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
