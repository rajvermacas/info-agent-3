"""
Detect Conflicts Node - Find contradicting data across POC responses.

Analyzes aggregated data to detect cases where multiple POCs
provided different values for the same data field.
"""

import logging
from typing import Any

from mail_agent.agent.multi_poc_helpers import (
    get_completed_pocs,
    get_poc_state,
)
from mail_agent.agent.multi_poc_state import DataConflict
from mail_agent.agent.state import AgentState


logger = logging.getLogger(__name__)


async def detect_conflicts(state: AgentState) -> dict[str, Any]:
    """
    Detect data conflicts between POC responses.

    This node:
    1. Analyzes aggregated_data for overlapping fields
    2. Identifies cases where POCs provided different values
    3. Creates DataConflict records for resolution

    Args:
        state: Current agent state with aggregated_data and poc_states.

    Returns:
        State update with conflicts list containing DataConflict objects.
    """
    logger.info("Detecting data conflicts")

    try:
        aggregated_data = state.get("aggregated_data", {})
        completed_poc_ids = get_completed_pocs(state)

        if len(completed_poc_ids) < 2:
            logger.info("Less than 2 completed POCs - no conflict detection needed")
            return {
                "conflicts": [],
                "current_node": "detect_conflicts",
                "progress_messages": ["No conflicts possible with single POC"],
            }

        # Build field-to-POC-values mapping
        # key: field_name -> {poc_id: value}
        field_values: dict[str, dict[str, Any]] = {}

        for poc_id in completed_poc_ids:
            try:
                poc_state = get_poc_state(state, poc_id)
                extracted_data = poc_state.extracted_data or {}

                for field, value in extracted_data.items():
                    if field not in field_values:
                        field_values[field] = {}
                    field_values[field][poc_id] = value

            except (KeyError, ValueError) as e:
                logger.warning(f"Could not get data for POC {poc_id}: {e}")
                continue

        # Detect conflicts: fields with different values from different POCs
        conflicts: list[DataConflict] = []

        for field, poc_values in field_values.items():
            if len(poc_values) < 2:
                # Only one POC has this field - no conflict
                continue

            # Check if values are actually different
            unique_values = set()
            for value in poc_values.values():
                # Convert to string for comparison (handles complex types)
                unique_values.add(str(value))

            if len(unique_values) > 1:
                # Conflict detected!
                conflict = DataConflict(
                    field=field,
                    poc_values={
                        poc_id: str(value) for poc_id, value in poc_values.items()
                    },
                )

                conflicts.append(conflict)
                logger.warning(
                    f"Conflict detected for field '{field}': "
                    f"{len(poc_values)} POCs with {len(unique_values)} unique values"
                )

        # Create progress message
        if conflicts:
            conflict_fields = [c.field for c in conflicts[:5]]
            fields_summary = ", ".join(conflict_fields)
            if len(conflicts) > 5:
                fields_summary += f" (+{len(conflicts) - 5} more)"
            progress_msg = (
                f"Detected {len(conflicts)} data conflict(s): {fields_summary}"
            )
        else:
            progress_msg = "No data conflicts detected"

        logger.info(f"Conflict detection complete: {len(conflicts)} conflict(s)")

        return {
            "conflicts": [c.to_dict() for c in conflicts],
            "current_node": "detect_conflicts",
            "progress_messages": [progress_msg],
        }

    except Exception as e:
        error_msg = f"Failed to detect conflicts: {e}"
        logger.error(error_msg, exc_info=True)
        return {
            "error": error_msg,
            "current_node": "error",
            "progress_messages": [f"ERROR: {error_msg}"],
        }


def has_conflicts(state: AgentState) -> bool:
    """Check if state has unresolved conflicts."""
    conflicts = state.get("conflicts", [])
    return len(conflicts) > 0


def get_conflicts(state: AgentState) -> list[DataConflict]:
    """Get list of DataConflict objects from state."""
    conflicts_raw = state.get("conflicts", [])
    return [DataConflict.from_dict(c) for c in conflicts_raw]
