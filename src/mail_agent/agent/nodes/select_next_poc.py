"""
Select Next POC Node - Selects the next pending POC for processing.

This node iterates through POCs to find the next one that needs processing.
It enables multi-POC support by looping back through all POCs until all
conversations reach terminal states (success, failed, or redirected).
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, get_active_poc


logger = logging.getLogger(__name__)


async def select_next_poc(state: AgentState) -> dict[str, Any]:
    """
    Select the next POC that needs processing.

    Iterates through all conversations to find a POC that is not in a
    terminal state (success, failed, redirected). Sets current_poc to
    that POC for the next iteration of the email flow.

    Args:
        state: Current agent state.

    Returns:
        State update with:
        - current_poc: The next POC to process, or None if all complete
        - current_node: "select_next_poc"
        - progress_messages: Progress update

    Note:
        This node is called after a POC's conversation reaches a terminal
        state (success/failure) to check if more POCs need processing.
    """
    logger.info("Selecting next POC for processing")

    # Get all conversations for logging
    conversations = state.get("conversations", {})
    poc_statuses = {
        poc: conv.get("status", "unknown")
        for poc, conv in conversations.items()
    }
    logger.debug(f"Current POC statuses: {poc_statuses}")

    # Find next pending POC
    next_poc = get_active_poc(state)

    if next_poc:
        logger.info(f"Selected next POC for processing: {next_poc}")
        return {
            "current_poc": next_poc,
            "current_node": "select_next_poc",
            "progress_messages": [f"Switching to next POC: {next_poc}"],
        }
    else:
        # All POCs have been processed
        logger.info("All POCs have been processed (terminal states reached)")
        return {
            "current_poc": None,
            "current_node": "select_next_poc",
            "progress_messages": ["All POCs have been processed"],
        }
