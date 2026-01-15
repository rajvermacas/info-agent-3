"""
Aggregate POC Responses Node - Merge data from all completed POCs.

Collects extracted_data from all completed POCs and merges into
a unified aggregated_data structure for global validation.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_completed_pocs,
    get_execution_plan,
    get_poc_state,
)
from mail_agent.agent.multi_poc_state import POCStatus
from mail_agent.agent.state import AgentState


logger = logging.getLogger(__name__)


async def aggregate_poc_responses(state: AgentState) -> dict[str, Any]:
    """
    Aggregate data from all completed POC responses.

    This node:
    1. Collects extracted_data from all completed POCs
    2. Merges data into unified aggregated_data structure
    3. Handles data key collisions by prefixing with POC ID

    Args:
        state: Current agent state with poc_states.

    Returns:
        State update with aggregated_data containing merged POC data.
    """
    logger.info("Aggregating POC responses")

    try:
        execution_plan = get_execution_plan(state)
        completed_poc_ids = get_completed_pocs(state)

        if not completed_poc_ids:
            logger.warning("No completed POCs to aggregate")
            return {
                "aggregated_data": {},
                "current_node": "aggregate_poc_responses",
                "progress_messages": ["No completed POC data to aggregate"],
            }

        logger.info(f"Aggregating data from {len(completed_poc_ids)} completed POC(s)")

        # Collect data from each completed POC
        aggregated_data: dict[str, Any] = {}
        poc_data_summary: dict[str, list[str]] = {}

        for poc_id in completed_poc_ids:
            try:
                poc_state = get_poc_state(state, poc_id)

                if poc_state.status != POCStatus.COMPLETED:
                    logger.warning(
                        f"POC {poc_id} not completed (status={poc_state.status}). "
                        "Skipping."
                    )
                    continue

                extracted_data = poc_state.extracted_data or {}

                if not extracted_data:
                    logger.debug(f"POC {poc_id} has no extracted data")
                    poc_data_summary[poc_id] = []
                    continue

                # Track keys for this POC
                poc_data_summary[poc_id] = []

                # Merge into aggregated data
                # Use POC ID prefix for multi-POC scenarios to avoid collisions
                for key, value in extracted_data.items():
                    # Create prefixed key for traceability
                    prefixed_key = f"{poc_id}.{key}"
                    aggregated_data[prefixed_key] = value
                    poc_data_summary[poc_id].append(key)

                    # Also store under original key if no collision
                    if key not in aggregated_data:
                        aggregated_data[key] = value
                    else:
                        logger.debug(
                            f"Key collision for '{key}' - using prefixed key only"
                        )

                logger.debug(
                    f"Aggregated {len(extracted_data)} items from POC {poc_id}"
                )

            except (KeyError, ValueError) as e:
                logger.warning(f"Could not get data for POC {poc_id}: {e}")
                poc_data_summary[poc_id] = []

        # Create summary for progress
        total_items = sum(len(keys) for keys in poc_data_summary.values())
        poc_contributions = ", ".join(
            f"{poc_id}({len(keys)})"
            for poc_id, keys in poc_data_summary.items()
        )

        progress_msg = (
            f"Aggregated {total_items} data items from "
            f"{len(completed_poc_ids)} POC(s): {poc_contributions}"
        )

        logger.info(
            f"Aggregation complete: {total_items} items, "
            f"{len(aggregated_data)} unique keys"
        )

        return {
            "aggregated_data": aggregated_data,
            "current_node": "aggregate_poc_responses",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to aggregate POC responses: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def get_aggregated_data(state: AgentState) -> dict[str, Any]:
    """
    Helper to retrieve aggregated_data from state.

    Args:
        state: Current agent state.

    Returns:
        Dictionary of aggregated data.
    """
    return state.get("aggregated_data", {})
