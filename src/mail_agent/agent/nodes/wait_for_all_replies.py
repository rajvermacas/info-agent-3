"""
Wait For All Replies Node - Multi-POC interrupt-based waiting.

This node uses LangGraph's interrupt() function to pause execution while
waiting for replies from ALL POCs in parallel mode. The TaskManager
collects webhooks as they arrive and only resumes when all have responded.
"""

import logging
from typing import Any, Optional

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    get_conversation,
)


logger = logging.getLogger(__name__)


async def wait_for_all_replies(state: AgentState) -> dict[str, Any]:
    """
    Wait for replies from ALL waiting POCs (parallel mode).

    Uses a single LangGraph interrupt with multi-POC context.
    TaskManager handles webhook collection and batch resumption.

    Behavior:
    - Calls interrupt() with list of all waiting POC emails
    - Graph execution pauses and SSE stream closes
    - TaskManager collects webhooks from each POC
    - When ALL webhooks arrive, graph resumes with all webhook data
    - Returns combined webhook data for parallel processing

    Args:
        state: Current agent state with _waiting_pocs set.

    Returns:
        State update with _received_webhooks containing all webhook data.
    """
    waiting_pocs = state.get("_waiting_pocs", [])

    if not waiting_pocs:
        logger.error("No waiting POCs for wait_for_all_replies")
        return {
            "error": "No waiting POCs",
            "current_node": "error",
            "progress_messages": ["ERROR: No POCs waiting for replies"],
        }

    task_id = state.get("task_id")
    logger.info(
        f"wait_for_all_replies: Waiting for {len(waiting_pocs)} POCs, "
        f"task_id={task_id}"
    )
    logger.info(f"POCs waiting: {waiting_pocs}")

    try:
        progress_msg = f"Waiting for replies from {len(waiting_pocs)} POCs..."
        logger.info(progress_msg)

        # Prepare interrupt payload with ALL waiting POCs
        interrupt_payload = {
            "reason": "waiting_for_all_replies",
            "poc_emails": waiting_pocs,  # List of all POCs
            "task_id": task_id,
            "parallel_mode": True,
            "poc_count": len(waiting_pocs),
        }

        logger.info(
            f"Calling interrupt() for {len(waiting_pocs)} POCs in parallel mode"
        )

        # Call interrupt - graph pauses here
        # TaskManager.suspend_task_multi_poc() registers all POCs
        # TaskManager.handle_webhook() collects webhooks until all arrive
        # TaskManager._resume_task_multi_poc() resumes with all webhook data
        resume_data = interrupt(interrupt_payload)

        # After resume - resume_data contains all webhook payloads
        # Format: {"webhooks": {poc_email: webhook_data, ...}, "parallel_mode": True}
        received_webhooks = resume_data.get("webhooks", {})
        poc_count = len(received_webhooks)

        logger.info(
            f"Resumed after receiving {poc_count} webhook(s) from: "
            f"{list(received_webhooks.keys())}"
        )

        # Update all conversation statuses to "fetching"
        conversations = dict(state.get("conversations", {}))
        for poc_email in received_webhooks.keys():
            poc_email_key = _find_conversation_key(conversations, poc_email)
            if poc_email_key:
                conv = ConversationState.from_dict(conversations[poc_email_key])
                conv.status = "fetching"
                conversations[poc_email_key] = conv.to_dict()
                logger.debug(f"Updated {poc_email_key} status to 'fetching'")

        progress_msg = f"Received replies from all {poc_count} POCs"
        logger.info(progress_msg)

        return {
            "conversations": conversations,
            "current_node": "wait_for_all_replies",
            "progress_messages": [progress_msg],
            "_received_webhooks": received_webhooks,
            "_parallel_mode": True,
        }

    except GraphInterrupt:
        # Re-raise GraphInterrupt for LangGraph to handle checkpoint
        logger.debug(
            f"GraphInterrupt raised for {len(waiting_pocs)} POCs, "
            "propagating to graph engine"
        )
        raise

    except Exception as e:
        error_msg = f"Error waiting for all replies: {e}"
        logger.exception(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def _find_conversation_key(
    conversations: dict[str, dict[str, Any]],
    poc_email: str,
) -> Optional[str]:
    """
    Find conversation key by POC email (case-insensitive).

    Args:
        conversations: Dict of conversation states.
        poc_email: POC email to find.

    Returns:
        Conversation key or None if not found.
    """
    poc_email_lower = poc_email.lower()

    # Exact match first
    if poc_email in conversations:
        return poc_email

    # Case-insensitive search
    for key in conversations.keys():
        if key.lower() == poc_email_lower:
            return key

    return None
