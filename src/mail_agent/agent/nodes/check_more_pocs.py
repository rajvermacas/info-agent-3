"""
Check More POCs Node - Determines if more POCs need processing.

This node is called after a POC's conversation reaches a terminal state
(success, failed, redirected). It checks if there are more POCs pending
and routes accordingly:
- If more POCs pending: route to select_next_poc
- If all POCs complete: route to cross-POC validation
"""

import logging
from typing import Any

from mail_agent.agent.state import AgentState, all_conversations_complete, get_active_poc


logger = logging.getLogger(__name__)


async def check_more_pocs(state: AgentState) -> dict[str, Any]:
    """
    Check if more POCs need processing.

    This node is a routing checkpoint after each POC reaches a terminal
    state. It determines whether to:
    1. Continue to the next pending POC (via select_next_poc)
    2. Proceed to cross-POC validation (all individual POCs complete)

    Args:
        state: Current agent state.

    Returns:
        State update with:
        - _all_pocs_individual_complete: True if all POCs have reached
          individual terminal states (before cross-validation)
        - current_node: "check_more_pocs"
        - progress_messages: Status update

    Note:
        The routing decision is made by `route_after_check_more_pocs`
        in graph.py based on the _all_pocs_individual_complete flag.
    """
    logger.info("Checking if more POCs need processing")

    # Get current status of all conversations
    conversations = state.get("conversations", {})

    # Log detailed status for debugging
    total_pocs = len(conversations)
    completed_count = 0
    pending_pocs = []

    for poc_email, conv_dict in conversations.items():
        status = conv_dict.get("status", "unknown")
        logger.debug(f"POC {poc_email}: status={status}")

        if status in ("success", "failed", "redirected"):
            completed_count += 1
        else:
            pending_pocs.append(poc_email)

    logger.info(
        f"POC status summary: {completed_count}/{total_pocs} complete, "
        f"pending={pending_pocs}"
    )

    # Check if all POCs have reached individual terminal states
    all_complete = all_conversations_complete(state)

    if all_complete:
        logger.info(
            "All POCs have reached individual terminal states. "
            "Proceeding to cross-POC validation."
        )
        return {
            "_all_pocs_individual_complete": True,
            "current_node": "check_more_pocs",
            "progress_messages": [
                f"All {total_pocs} POC(s) have responded. "
                "Proceeding to cross-POC validation."
            ],
        }
    else:
        # Find the next pending POC for logging
        next_poc = get_active_poc(state)
        logger.info(
            f"More POCs need processing. Next pending POC: {next_poc}. "
            f"Remaining: {pending_pocs}"
        )
        return {
            "_all_pocs_individual_complete": False,
            "current_node": "check_more_pocs",
            "progress_messages": [
                f"Processing next POC. {completed_count}/{total_pocs} complete. "
                f"Pending: {', '.join(pending_pocs)}"
            ],
        }
