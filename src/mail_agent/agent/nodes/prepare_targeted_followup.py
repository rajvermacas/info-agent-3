"""
Prepare Targeted Followup Node - Prepares follow-ups for specific POCs.

This node is called when cross-POC validation finds issues. It identifies
which specific POC(s) need to provide missing data and resets their
conversation state for re-processing.

Key principle: Only bother POCs whose data has issues, not all POCs.
"""

import logging
from typing import Any

from mail_agent.agent.state import (
    AgentState,
    ConversationState,
)


logger = logging.getLogger(__name__)


async def prepare_targeted_followup(state: AgentState) -> dict[str, Any]:
    """
    Prepare targeted follow-ups for POCs with missing/invalid data.

    This node reads the cross-POC validation results and resets the
    conversation state for POCs that need to provide additional data.

    The follow-up context is stored in the conversation so that
    compose_email can generate a targeted request mentioning:
    - What specific data is missing
    - How it relates to data from other POCs
    - What corrections are needed

    Args:
        state: Current agent state with cross-POC validation results.

    Returns:
        State update with:
        - conversations: Updated with reset status and follow-up context
        - _cross_poc_followup_round: Incremented follow-up round counter
        - current_node: "prepare_targeted_followup"
        - progress_messages: Follow-up preparation status
    """
    logger.info("Preparing targeted follow-ups for POCs with cross-POC issues")

    # Get cross-POC validation results
    issues = state.get("_cross_poc_issues", [])
    missing_data = state.get("_cross_poc_missing_data", {})

    if not issues and not missing_data:
        logger.warning("No cross-POC issues found - nothing to follow up")
        return {
            "current_node": "prepare_targeted_followup",
            "progress_messages": ["No cross-POC issues to follow up."],
        }

    # Track which POCs need follow-up
    pocs_needing_followup: dict[str, dict[str, Any]] = {}

    # Process issues to identify target POCs
    for issue in issues:
        # The target_poc is the one who needs to provide missing data
        target_poc = issue.get("target_poc")
        if not target_poc:
            continue

        if target_poc not in pocs_needing_followup:
            pocs_needing_followup[target_poc] = {
                "issues": [],
                "missing_items": [],
                "related_pocs": set(),
            }

        pocs_needing_followup[target_poc]["issues"].append(issue)
        pocs_needing_followup[target_poc]["missing_items"].extend(
            issue.get("missing_items", [])
        )
        source_poc = issue.get("source_poc")
        if source_poc:
            pocs_needing_followup[target_poc]["related_pocs"].add(source_poc)

    # Also process explicit missing_data mapping
    for poc_email, missing_items in missing_data.items():
        if poc_email not in pocs_needing_followup:
            pocs_needing_followup[poc_email] = {
                "issues": [],
                "missing_items": [],
                "related_pocs": set(),
            }
        pocs_needing_followup[poc_email]["missing_items"].extend(missing_items)

    logger.info(
        f"Identified {len(pocs_needing_followup)} POC(s) needing follow-up: "
        f"{list(pocs_needing_followup.keys())}"
    )

    # Update conversations - reset status and add follow-up context
    conversations = dict(state.get("conversations", {}))

    for poc_email, followup_info in pocs_needing_followup.items():
        if poc_email not in conversations:
            logger.warning(f"POC {poc_email} not found in conversations - skipping")
            continue

        conv = ConversationState.from_dict(conversations[poc_email])

        # Reset status to pending for re-processing
        conv.status = "pending"

        # Store follow-up context in conversation (using a custom field via dict)
        conv_dict = conv.to_dict()
        conv_dict["_cross_poc_followup_context"] = {
            "issues": followup_info["issues"],
            "missing_items": list(set(followup_info["missing_items"])),  # Dedupe
            "related_pocs": list(followup_info["related_pocs"]),
            "is_cross_poc_followup": True,
        }

        conversations[poc_email] = conv_dict

        logger.debug(
            f"Reset POC {poc_email} for follow-up with {len(followup_info['issues'])} issues"
        )

    # Increment follow-up round counter (for tracking/limiting)
    current_round = state.get("_cross_poc_followup_round", 0)
    new_round = current_round + 1

    # Check if we've exceeded max follow-up rounds
    max_rounds = 3  # Configurable: max cross-POC follow-up attempts
    if new_round > max_rounds:
        logger.warning(
            f"Exceeded max cross-POC follow-up rounds ({max_rounds}). "
            "Marking remaining issues as unresolved."
        )
        # Could mark as failed here, but let's proceed anyway
        # The validation will fail again and eventually reach terminal state

    # Build progress message with details
    poc_list = ", ".join(pocs_needing_followup.keys())
    total_issues = sum(
        len(info["issues"]) for info in pocs_needing_followup.values()
    )

    progress_msg = (
        f"Preparing targeted follow-up (round {new_round}) for {len(pocs_needing_followup)} "
        f"POC(s): {poc_list}. Total issues: {total_issues}"
    )

    return {
        "conversations": conversations,
        "_cross_poc_followup_round": new_round,
        "current_node": "prepare_targeted_followup",
        "progress_messages": [progress_msg],
    }
