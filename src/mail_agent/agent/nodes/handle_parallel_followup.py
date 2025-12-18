"""
Handle Parallel Follow-up Node - Prepare follow-ups for invalid POC responses.

Used in parallel processing mode when some POC responses are invalid
and need follow-up emails. Sets up the state for re-entering the
compose_all_emails → send_all_emails → wait_for_all_replies loop.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
)
from mail_agent.config import get_settings


logger = logging.getLogger(__name__)


async def handle_parallel_followup(state: AgentState) -> dict[str, Any]:
    """
    Prepare follow-up for POCs with invalid responses.

    This node:
    1. Identifies POCs that need follow-up
    2. Checks max attempts
    3. Sets up _followup_pocs for compose_all_emails to use
    4. Updates conversation statuses

    Args:
        state: Current agent state with _poc_processing_results.

    Returns:
        State update with _followup_pocs set for next iteration.
    """
    logger.info("Handling parallel follow-up for invalid POC responses")

    try:
        poc_results = state.get("_poc_processing_results", {})
        conversations = dict(state.get("conversations", {}))
        settings = get_settings()
        max_attempts = settings.max_attempts

        followup_pocs: list[str] = []
        failed_max_attempts_pocs: list[str] = []

        for poc_email, result in poc_results.items():
            # Skip valid and redirected POCs
            if result.get("is_valid") or result.get("is_redirect"):
                continue

            # Find conversation
            conv_key = _find_conversation_key(conversations, poc_email)
            if not conv_key:
                logger.warning(f"No conversation for POC {poc_email}")
                continue

            conv = ConversationState.from_dict(conversations[conv_key])

            # Check if max attempts reached
            if conv.attempt_count >= max_attempts:
                logger.warning(
                    f"POC {poc_email} reached max attempts ({max_attempts})"
                )
                conv.status = "failed"
                conv.final_result = "failed_max_attempts"
                conv.error_message = (
                    f"Max attempts ({max_attempts}) reached without valid response"
                )
                failed_max_attempts_pocs.append(poc_email)
            else:
                # Needs follow-up
                logger.info(
                    f"POC {poc_email} needs follow-up "
                    f"(attempt {conv.attempt_count}/{max_attempts})"
                )
                conv.status = "pending"  # Reset to pending for next compose
                followup_pocs.append(poc_email)

            conversations[conv_key] = conv.to_dict()

        # Build progress message
        if followup_pocs and failed_max_attempts_pocs:
            progress_msg = (
                f"Follow-up needed for {len(followup_pocs)} POCs; "
                f"{len(failed_max_attempts_pocs)} failed max attempts"
            )
        elif followup_pocs:
            progress_msg = f"Follow-up needed for {len(followup_pocs)} POCs"
        elif failed_max_attempts_pocs:
            progress_msg = (
                f"All {len(failed_max_attempts_pocs)} invalid POCs "
                "reached max attempts - no more follow-ups"
            )
        else:
            progress_msg = "No follow-ups needed"

        logger.info(progress_msg)

        # If no follow-ups needed, clear the _followup_pocs
        result_followup_pocs = followup_pocs if followup_pocs else None

        return {
            "conversations": conversations,
            "current_node": "handle_parallel_followup",
            "progress_messages": [progress_msg],
            "_followup_pocs": result_followup_pocs,
            "_poc_processing_results": None,  # Clear results
            "_all_individual_valid": None,
        }

    except Exception as e:
        error_msg = f"Failed to handle parallel follow-up: {e}"
        logger.exception(error_msg)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def _find_conversation_key(
    conversations: dict[str, dict[str, Any]],
    poc_email: str,
) -> str | None:
    """Find conversation key by POC email (case-insensitive)."""
    poc_email_lower = poc_email.lower()

    if poc_email in conversations:
        return poc_email

    for key in conversations.keys():
        if key.lower() == poc_email_lower:
            return key

    return None
