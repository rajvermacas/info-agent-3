"""
Decide Next Node - Determine the next action based on validation result.

Routes to success, failure, or follow-up based on validation and attempt count.
"""

import logging
from typing import Any, Literal

from mail_agent.agent.state import (
    AgentState,
    get_conversation,
    update_conversation,
)
from mail_agent.config import get_settings


logger = logging.getLogger(__name__)


def decide_next(state: AgentState) -> Literal["success", "failure", "followup"]:
    """
    Determine the next action based on validation result.

    This is a routing function for conditional edges.

    Args:
        state: Current agent state with validation result.

    Returns:
        Next route: "success", "failure", or "followup".
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        logger.error("No current POC set for decide_next")
        return "failure"

    try:
        conversation = get_conversation(state, current_poc)
        settings = get_settings()

        # Check validation result
        is_valid = state.get("_validation_is_valid", False)

        if is_valid:
            logger.info(f"Routing {current_poc} to SUCCESS")
            return "success"

        # Check attempt count
        if conversation.attempt_count >= settings.max_attempts:
            logger.info(
                f"Routing {current_poc} to FAILURE (max attempts reached: "
                f"{conversation.attempt_count}/{settings.max_attempts})"
            )
            return "failure"

        # Need follow-up
        logger.info(
            f"Routing {current_poc} to FOLLOWUP "
            f"(attempt {conversation.attempt_count}/{settings.max_attempts})"
        )
        return "followup"

    except Exception as e:
        logger.error(f"Error in decide_next: {e}")
        return "failure"


async def handle_success(state: AgentState) -> dict[str, Any]:
    """
    Handle successful validation - mark conversation complete.

    Args:
        state: Current agent state.

    Returns:
        State update marking POC as success.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        return {"error": "No current POC", "current_node": "error"}

    logger.info(f"Handling SUCCESS for POC: {current_poc}")

    try:
        conversation = get_conversation(state, current_poc)
        conversation.status = "success"
        conversation.final_result = "success"

        progress_msg = f"SUCCESS: Request satisfied by {current_poc}"

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "success",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Error handling success: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


async def handle_failure(state: AgentState) -> dict[str, Any]:
    """
    Handle validation failure - mark conversation as failed.

    Args:
        state: Current agent state.

    Returns:
        State update marking POC as failed.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        return {"error": "No current POC", "current_node": "error"}

    logger.info(f"Handling FAILURE for POC: {current_poc}")

    try:
        conversation = get_conversation(state, current_poc)
        settings = get_settings()

        conversation.status = "failed"
        conversation.final_result = "failed_max_attempts"

        last_feedback = ""
        if conversation.validation_results:
            last_feedback = conversation.validation_results[-1].feedback

        progress_msg = (
            f"FAILED: Max attempts ({settings.max_attempts}) reached for {current_poc}. "
            f"Last feedback: {last_feedback[:100]}..."
        )

        return {
            "conversations": update_conversation(state, current_poc, conversation),
            "current_node": "failure",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Error handling failure: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


async def prepare_followup(state: AgentState) -> dict[str, Any]:
    """
    Prepare for follow-up email - reset status to composing.

    Args:
        state: Current agent state.

    Returns:
        State update preparing for follow-up.
    """
    current_poc = state.get("current_poc")
    if not current_poc:
        return {"error": "No current POC", "current_node": "error"}

    logger.info(f"Preparing FOLLOWUP for POC: {current_poc}")

    try:
        conversation = get_conversation(state, current_poc)

        progress_msg = (
            f"Preparing follow-up email for {current_poc} "
            f"(attempt {conversation.attempt_count + 1})"
        )

        # Status will be updated by compose_email
        return {
            "current_node": "prepare_followup",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Error preparing followup: {e}"
        logger.error(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }
