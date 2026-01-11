"""
Handle Redirect Node - Process redirect when POC suggests another contact.

Creates a new conversation for the redirected POC and marks original as redirected.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
    RedirectInfo,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings


logger = logging.getLogger(__name__)


async def handle_redirect(state: AgentState) -> dict[str, Any]:
    """
    Handle redirect by creating new conversation for the redirect target.

    This node:
    1. Marks the original POC conversation as "redirected"
    2. Creates a new conversation for the redirect email
    3. Sets the current_poc to the new email for subsequent processing

    Args:
        state: Current agent state with redirect information.

    Returns:
        State update with new conversation and updated current_poc.
    """
    current_poc = state.get("current_poc")
    redirect_email = state.get("_redirect_email")
    redirect_reason = state.get("_redirect_reason", "Not the correct contact")

    if not current_poc:
        logger.error("No current POC set for handle_redirect")
        return {
            "error": "No current POC set",
            "current_node": "error",
            "progress_messages": ["ERROR: No current POC set for redirect handling"],
        }

    if not redirect_email:
        logger.error("No redirect email found in state")
        return {
            "error": "No redirect email found",
            "current_node": "error",
            "progress_messages": ["ERROR: No redirect email found in state"],
        }

    logger.info(
        f"Handling redirect from {current_poc} to {redirect_email}. "
        f"Reason: {redirect_reason}"
    )

    try:
        settings = get_settings()
        conversations = dict(state.get("conversations", {}))

        # Check if we've already created a conversation for this redirect email
        if redirect_email in conversations:
            redirect_status = conversations[redirect_email].get("status")
            if redirect_status in ("success", "failed", "redirected"):
                # Already processed this redirect target
                logger.warning(
                    f"Redirect target {redirect_email} already has terminal status: "
                    f"{redirect_status}. Marking original as failed."
                )
                # Mark original as failed to prevent infinite loops
                original_conv = get_conversation(state, current_poc)
                original_conv.status = "failed"
                original_conv.final_result = "failed_max_attempts"
                original_conv.error_message = (
                    f"Redirect loop detected: {redirect_email} already processed"
                )
                conversations[current_poc] = original_conv.to_dict()

                return {
                    "conversations": conversations,
                    "current_node": "handle_redirect",
                    "progress_messages": [
                        f"WARNING: Redirect target {redirect_email} already processed. "
                        f"Marking {current_poc} as failed."
                    ],
                    # Clear redirect data
                    "_redirect_detected": None,
                    "_redirect_email": None,
                    "_redirect_reason": None,
                }

        # Get and update the original conversation
        original_conv = get_conversation(state, current_poc)
        original_conv.status = "redirected"
        original_conv.final_result = "redirected"
        original_conv.redirected_to = redirect_email
        conversations[current_poc] = original_conv.to_dict()

        # Create redirect info for the new conversation
        redirect_info = RedirectInfo(
            original_poc=current_poc,
            redirect_email=redirect_email,
            redirect_reason=redirect_reason,
            redirected_at=datetime.now(timezone.utc),
        )

        # Create new conversation for redirect target
        new_conv = ConversationState(
            poc_email=redirect_email,
            status="pending",
            attempt_count=0,
            redirected_from=redirect_info,
        )
        conversations[redirect_email] = new_conv.to_dict()

        progress_msg = (
            f"REDIRECT: {current_poc} redirected to {redirect_email}. "
            f"Reason: {redirect_reason}. Creating new conversation."
        )

        logger.info(
            f"Created new conversation for {redirect_email}, "
            f"marked {current_poc} as redirected"
        )

        return {
            "conversations": conversations,
            "current_poc": redirect_email,  # Switch to new POC
            "current_node": "handle_redirect",
            "progress_messages": [progress_msg],
            # Clear redirect data
            "_redirect_detected": None,
            "_redirect_email": None,
            "_redirect_reason": None,
            # Clear validation data
            "_validation_is_valid": None,
            "_validation_feedback": None,
            "_validation_missing_items": None,
        }

    except Exception as e:
        error_msg = f"Failed to handle redirect from {current_poc}: {e}"
        logger.error(error_msg)

        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
